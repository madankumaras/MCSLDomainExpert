"""MCSL Domain Expert — Pipeline Dashboard.

Entry point: streamlit run pipeline_dashboard.py
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

import json
from pathlib import Path

# Load .env before any st.* calls — find_dotenv() walks up parent dirs so it
# works both from the project root and from git worktree subdirectories.
from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(raise_error_if_not_found=False), override=True)

import streamlit as st

# ── Pipeline module imports ────────────────────────────────────────────────────
from pipeline.domain_validator import validate_card, ValidationReport
from pipeline.release_analyser import analyse_release, CardSummary as RASummary, ReleaseAnalysis
from pipeline.card_processor import generate_acceptance_criteria, generate_test_cases, write_test_cases_to_card
from pipeline.sheets_writer import append_to_sheet
from pipeline.smart_ac_verifier import verify_ac
from pipeline.trello_client import TrelloClient
from pipeline.slack_client import post_signoff as slack_post_signoff, slack_configured, dm_token_configured
from pipeline.bug_reporter import notify_devs_of_bug

# ── History persistence helpers ────────────────────────────────────────────────

_HISTORY_FILE = Path(__file__).resolve().parent / "data" / "pipeline_history.json"


def _load_history() -> dict:
    """Load pipeline run history from disk. Returns {} if file absent or corrupt."""
    if _HISTORY_FILE.exists():
        try:
            return json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_history(runs: dict) -> None:
    """Persist pipeline run history to disk."""
    _HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    _HISTORY_FILE.write_text(json.dumps(runs, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Custom CSS ─────────────────────────────────────────────────────────────────
_CSS = """
<style>
/* Verdict pill badges */
.badge-pass      { background:#22c55e; color:#fff; padding:2px 10px; border-radius:12px; font-weight:600; font-size:0.82em; }
.badge-fail      { background:#ef4444; color:#fff; padding:2px 10px; border-radius:12px; font-weight:600; font-size:0.82em; }
.badge-partial   { background:#f59e0b; color:#fff; padding:2px 10px; border-radius:12px; font-weight:600; font-size:0.82em; }
.badge-qa_needed { background:#3b82f6; color:#fff; padding:2px 10px; border-radius:12px; font-weight:600; font-size:0.82em; }

/* Scenario result cards */
.scenario-card {
    border-left: 4px solid #00d4aa;
    background: #1a1d26;
    border-radius: 6px;
    padding: 12px 16px;
    margin-bottom: 10px;
}
.scenario-card.pass      { border-left-color: #22c55e; }
.scenario-card.fail      { border-left-color: #ef4444; }
.scenario-card.partial   { border-left-color: #f59e0b; }
.scenario-card.qa_needed { border-left-color: #3b82f6; }

/* Header */
.app-header { color: #00d4aa; font-size: 1.8em; font-weight: 700; letter-spacing: -0.5px; }
.app-subtitle { color: #8892a0; font-size: 0.95em; margin-top: -8px; }

/* App header — dark teal-navy gradient */
.pipeline-header {
    background: linear-gradient(135deg, #0f1723 0%, #1a2d2a 100%);
    padding: 20px 24px; border-radius: 8px; margin-bottom: 16px;
}
.pipeline-header h1 { color: #fff; font-weight: 700; margin: 0; }
.pipeline-header p  { color: #8892a0; margin: 4px 0 0 0; }

/* Sidebar status badges */
.status-badge {
    display: inline-flex; align-items: center; width: 100%;
    padding: 4px 10px; border-radius: 20px; font-size: 0.82em;
    font-weight: 500; margin-bottom: 4px;
}
.status-ok   { background: #d4edda; color: #155724; }
.status-warn { background: #fff3cd; color: #856404; }
.status-err  { background: #f8d7da; color: #721c24; }

/* Pipeline step chips */
.step-chip {
    display: inline-block; background: #00d4aa1a; color: #00d4aa;
    border: 1px solid #00d4aa44; border-radius: 14px;
    padding: 2px 12px; font-size: 0.82em; font-weight: 600;
    margin-right: 6px; margin-bottom: 4px;
}

/* Risk level badges */
.risk-low    { background: #d4edda; color: #155724; padding: 2px 10px; border-radius: 12px; font-size: 0.82em; }
.risk-medium { background: #fff3cd; color: #856404; padding: 2px 10px; border-radius: 12px; font-size: 0.82em; }
.risk-high   { background: #f8d7da; color: #721c24; padding: 2px 10px; border-radius: 12px; font-size: 0.82em; }

/* Card step headers */
.step-header { display: flex; align-items: center; gap: 10px; margin: 12px 0 6px 0; }
.step-num    { background: #00d4aa; color: #0f1117; border-radius: 50%; width: 24px; height: 24px; display: flex; align-items: center; justify-content: center; font-weight: 700; font-size: 0.85em; flex-shrink: 0; }
.step-title  { font-weight: 600; font-size: 0.95em; }

/* Streamlit overrides */
[data-testid="metric-container"] { background: #1a1d26; border-radius: 8px; padding: 12px; }
section[data-testid="stSidebar"] > div { padding-top: 1rem; }
button[data-baseweb="tab"] { font-weight: 600 !important; }
[data-testid="stExpander"] { border: 1px solid #2a2d3a; border-radius: 6px; }

/* Pipeline flow bar */
.pipeline-flow { display: flex; align-items: center; flex-wrap: wrap; gap: 4px; margin: 12px 0; }
.pf-step  { background: #2a2d3a; color: #8892a0; padding: 4px 12px; border-radius: 14px; font-size: 0.8em; font-weight: 500; }
.pf-step.done   { background: #22c55e22; color: #22c55e; }
.pf-step.active { background: #00d4aa22; color: #00d4aa; }
.pf-arrow { color: #4a5568; font-size: 0.9em; }

/* Bug severity badges */
.sev-p1 { background: #ef4444; color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 0.78em; font-weight: 700; }
.sev-p2 { background: #f97316; color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 0.78em; font-weight: 700; }
.sev-p3 { background: #eab308; color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 0.78em; font-weight: 700; }
.sev-p4 { background: #22c55e; color: #fff; padding: 2px 8px; border-radius: 10px; font-size: 0.78em; font-weight: 700; }
</style>
"""

# Verdict badge HTML helpers (for CSS pill badges in unsafe_allow_html blocks)
STATUS_BADGE: dict[str, str] = {
    "pass":      '<span class="badge-pass">PASS</span>',
    "fail":      '<span class="badge-fail">FAIL</span>',
    "partial":   '<span class="badge-partial">PARTIAL</span>',
    "qa_needed": '<span class="badge-qa_needed">QA NEEDED</span>',
}

# Streamlit markdown fallback (used in expander titles where unsafe_allow_html is unavailable)
STATUS_BADGE_MD: dict[str, str] = {
    "pass":      ":green[PASS]",
    "fail":      ":red[FAIL]",
    "partial":   ":orange[PARTIAL]",
    "qa_needed": ":blue[QA NEEDED]",
}


# ── Session state ──────────────────────────────────────────────────────────────

def _init_state() -> None:
    """Initialise all session state keys. Idempotent."""
    defaults: dict[str, Any] = {
        # Phase 4 — preserved
        "sav_running": False,
        "sav_stop":    threading.Event(),
        "sav_result":  None,
        "sav_prog":    {"current": 0, "total": 0, "label": ""},
        # Phase 5 — new
        "pipeline_runs":          {},
        "trello_connected":       False,
        "ac_drafts_loaded":       False,
        "code_paths_initialized": False,
        "rqa_cards":              [],
        "rqa_approved":           {},
        "rqa_test_cases":         {},
        "rqa_release":            "",
        # Phase 6 — User Story tab
        "us_request_input":  "",
        "us_result":         "",
        "us_history":        [],
        "us_card_title":     "",
        "us_list_mode":      "Existing list",
        "us_existing_list":  "",
        "us_new_list_name":  "",
        "us_assign_members": [],
        # Phase 6 — Move Cards tab (tab_devdone)
        "dd_list_select":  "Dev Done",
        "dd_move_target":  "Ready for QA",
        "dd_cards":        [],
        "dd_checked":      {},
        "dd_select_all":   False,
        # Phase 7 — Release QA tab
        "rqa_list_name":   "",
        "rqa_board_id":    "",
        "rqa_board_name":  "",
        "release_analysis": None,
        # Phase 8 — Sign Off tab
        "signoff_message": "",
        "signoff_sent":    False,
        # Phase 9 — Write Automation tab
        "auto_feature":        "",
        "auto_test_cases":     "",
        "auto_result":         None,
        "auto_exploration":    None,
        "auto_explore_running": False,
        # Phase 10 — Run Automation tab
        "run_running":        False,
        "run_result":         None,
        "run_selected_specs": [],
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val

    # Load history from disk on first initialisation
    if not st.session_state.get("pipeline_runs"):
        st.session_state["pipeline_runs"] = _load_history()


# ── Progress callback (written to by worker thread — no st.* calls) ────────────

def _progress_cb(
    scenario_idx: int,
    scenario_title: str,
    step_num: int,
    step_desc: str,
) -> None:
    """Update sav_prog in session state. Called from background thread."""
    total = st.session_state.sav_prog.get("total", 0)
    st.session_state.sav_prog = {
        "current": scenario_idx,
        "total":   total,
        "label":   f"[{scenario_idx}/{total}] {scenario_title[:50]} — {step_desc}",
    }


# ── Stop button callback factory ───────────────────────────────────────────────

def _make_stop_callback(session_state: Any):
    """Return an on_click callback that sets the stop event on the given session_state."""
    def _stop():
        session_state.sav_stop.set()
    return _stop


# ── Thread worker (implemented in 04-02) ──────────────────────────────────────

def _run_pipeline(
    ac_text: str,
    card_name: str,
    headless: bool,
    max_scenarios: int,
) -> None:
    """Worker function — runs in background thread. MUST NOT call any st.* functions."""
    from pipeline.smart_ac_verifier import verify_ac  # lazy import keeps startup fast

    try:
        report = verify_ac(
            ac_text=ac_text,
            card_name=card_name,
            stop_flag=lambda: st.session_state.sav_stop.is_set(),
            progress_cb=_progress_cb,
            headless=headless,
            max_scenarios=max_scenarios,
        )
        # CRITICAL: set result FIRST, then clear running flag (avoid race condition)
        st.session_state.sav_result = report.to_dict()
    except Exception as exc:  # noqa: BLE001
        st.session_state.sav_result = {
            "error": str(exc),
            "card_name": card_name,
            "total": 0,
            "summary": {"pass": 0, "fail": 0, "partial": 0, "qa_needed": 0},
            "duration_seconds": 0.0,
            "scenarios": [],
        }
    finally:
        st.session_state.sav_running = False


# ── Thread launch (implemented in 04-02) ──────────────────────────────────────

def start_run(
    ac_text: str,
    card_name: str,
    n_scenarios: int = 1,
    headless: bool = True,
    max_scenarios: int = 10,
) -> None:
    """Launch verify_ac() in a background daemon thread."""
    st.session_state.sav_running = True
    st.session_state.sav_stop.clear()
    st.session_state.sav_result = None
    st.session_state.sav_prog = {
        "current": 0,
        "total":   n_scenarios,
        "label":   "Starting\u2026",
    }
    t = threading.Thread(
        target=_run_pipeline,
        args=(ac_text, card_name, headless, max_scenarios),
        daemon=True,
    )
    t.start()


# ── Report render (implemented in 04-04) ──────────────────────────────────────

def render_report(result: dict) -> None:
    """Render VerificationReport.to_dict() as styled scenario cards."""
    import base64
    import io

    # Handle error result (from _run_pipeline exception handler)
    if "error" in result:
        st.error(f"Pipeline error: {result['error']}")
        return

    # ── Summary header ──────────────────────────────────────────────────────
    st.subheader(f"Report: {result.get('card_name', 'Unknown card')}")
    summary = result.get("summary", {})
    dur = result.get("duration_seconds", 0.0)

    cols = st.columns(5)
    cols[0].metric("Total",     result.get("total", 0))
    cols[1].metric("Pass",      summary.get("pass", 0))
    cols[2].metric("Fail",      summary.get("fail", 0))
    cols[3].metric("Partial",   summary.get("partial", 0))
    cols[4].metric("QA Needed", summary.get("qa_needed", 0))
    st.caption(f"Duration: {dur:.1f}s")
    st.divider()

    # ── Per-scenario cards ──────────────────────────────────────────────────
    for sc in result.get("scenarios", []):
        status       = sc.get("status", "qa_needed")
        badge_md     = STATUS_BADGE_MD.get(status, status.upper())
        scenario_title = sc.get("scenario", "")[:80]

        with st.expander(f"{badge_md}  {scenario_title}"):
            # Badge pill (HTML — unsafe_allow_html works inside expander body)
            badge_html  = STATUS_BADGE.get(status, f"<span>{status.upper()}</span>")
            carrier_tag = sc.get("carrier", "")
            finding     = sc.get("finding", "No finding recorded")
            steps_taken = sc.get("steps_taken", 0)

            card_html = (
                f'<div class="scenario-card {status}">'
                f"  {badge_html}"
                + (f"  &nbsp;&nbsp;<strong>{carrier_tag}</strong>" if carrier_tag else "")
                + '  <hr style="margin:8px 0; border-color:#2a2d3a;">'
                f'  <p style="margin:4px 0;">{finding}</p>'
                f"</div>"
            )
            st.markdown(card_html, unsafe_allow_html=True)
            st.caption(f"Steps taken: {steps_taken}")

            # Screenshot thumbnail
            scr = sc.get("evidence_screenshot", "")
            if scr:
                try:
                    img_bytes = base64.b64decode(scr)
                    st.image(io.BytesIO(img_bytes), use_container_width=True)
                except Exception:  # noqa: BLE001
                    st.caption("(screenshot decode error)")


# ── Status badge helper ───────────────────────────────────────────────────────

def _status_badge(label: str, ok: bool, err_hint: str = "") -> str:
    """Return an HTML status badge string. Rendered via st.markdown(unsafe_allow_html=True)."""
    if ok:
        return f'<div class="status-badge status-ok">✅ &nbsp;{label}</div>'
    else:
        hint = f" — {err_hint}" if err_hint else ""
        return f'<div class="status-badge status-err">❌ &nbsp;{label}{hint}</div>'


# ── Page config ───────────────────────────────────────────────────────────────
# MUST be the first Streamlit call

st.set_page_config(
    page_title="MCSL QA Pipeline",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(_CSS, unsafe_allow_html=True)


# ── Main entry point ──────────────────────────────────────────────────────────

def main() -> None:
    """Main app — sidebar + tab scaffold. Implemented fully in plans 05-02 and 05-03."""
    import os
    import config  # lazy import — keeps dotenv load inside main() only

    _init_state()

    # ── Connection check flags ──────────────────────────────────────────────
    api_ok    = bool(config.ANTHROPIC_API_KEY)
    trello_ok = all([
        os.getenv("TRELLO_API_KEY"),
        os.getenv("TRELLO_TOKEN"),
        os.getenv("TRELLO_BOARD_ID"),
    ])
    slack_ok  = bool(
        os.getenv("SLACK_WEBHOOK_URL", "").strip()
        or (os.getenv("SLACK_BOT_TOKEN", "").strip() and os.getenv("SLACK_CHANNEL", "").strip())
    )
    sheets_ok = bool(os.path.exists(config.GOOGLE_CREDENTIALS_PATH))
    try:
        import urllib.request as _ur
        _ur.urlopen(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=2)
        ollama_ok = True
    except Exception:  # noqa: BLE001
        ollama_ok = False

    # ── code_paths_initialized guard ───────────────────────────────────────
    if not st.session_state.get("code_paths_initialized"):
        if config.MCSL_AUTOMATION_REPO_PATH:
            st.session_state["automation_code_path"] = config.MCSL_AUTOMATION_REPO_PATH
        if config.STOREPEPSAAS_SERVER_PATH:
            st.session_state["mcsl_code_path"] = config.STOREPEPSAAS_SERVER_PATH
        if getattr(config, "WIKI_PATH", ""):
            st.session_state["wiki_path"] = config.WIKI_PATH
        st.session_state["code_paths_initialized"] = True

    # ── Sidebar ────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown(
            '<div class="pipeline-header">'
            '<h1>🚚 MCSL QA Pipeline</h1>'
            '<p>AI-powered QA orchestration</p>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.divider()

        # ── System Status ─────────────────────────────────────────────────
        st.subheader("System Status")
        st.markdown(
            _status_badge("Claude API",     api_ok,    "Set ANTHROPIC_API_KEY in .env")
            + _status_badge("Trello",        trello_ok, "Set TRELLO_API_KEY / TOKEN / BOARD_ID")
            + _status_badge("Slack",         slack_ok,  "Set SLACK_WEBHOOK_URL or BOT_TOKEN+CHANNEL")
            + _status_badge("Google Sheets", sheets_ok, "Add credentials.json to project root")
            + _status_badge("Ollama",        ollama_ok, "Start Ollama locally on port 11434"),
            unsafe_allow_html=True,
        )
        st.divider()

        # ── Release Progress ──────────────────────────────────────────────
        st.subheader("Release Progress")
        cards    = st.session_state.get("rqa_cards", [])
        approved = st.session_state.get("rqa_approved", {})
        tc_store = st.session_state.get("rqa_test_cases", {})
        current_release = st.session_state.get("rqa_release", "")
        n_cards    = len(cards)
        n_approved = sum(1 for c in cards if approved.get(getattr(c, "id", c)))
        n_tc       = sum(1 for c in cards if getattr(c, "id", c) in tc_store)

        if current_release:
            st.markdown(f"**Release:** `{current_release}`")
            st.markdown(
                f'<div style="display:flex;gap:16px;font-size:0.85em;margin:8px 0;">'
                f'<span>Cards: <strong>{n_cards}</strong></span>'
                f'<span>Approved: <strong>{n_approved}</strong></span>'
                f'<span>TCs: <strong>{n_tc}</strong></span>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if n_cards > 0:
                st.progress(n_approved / n_cards, text=f"{n_approved}/{n_cards} approved")
        else:
            st.caption("Load a release in Release QA to see progress.")
        st.divider()

        # ── Code Knowledge Base ───────────────────────────────────────────
        st.subheader("🗂️ Code Knowledge Base")
        st.caption("RAG over source code — TCs + automation scripts use real patterns.")

        # Load index stats once for all sections
        try:
            from rag.code_indexer import get_index_stats
            _idx_stats = get_index_stats()
        except Exception:
            _idx_stats = {}

        def _sync_badge(cnt, sync):
            if cnt == 0:
                return "⬜ Not indexed"
            commit = sync.get("commit", "")
            synced = sync.get("synced_at", "")
            tag = f" · `{commit}`" if commit else ""
            ts  = f" · {synced}" if synced else ""
            return f"✅ {cnt} chunks{tag}{ts}"

        _auto_cnt   = _idx_stats.get("automation", 0)
        _mcsl_cnt   = _idx_stats.get("storepepsaas_server", 0)
        _auto_sync  = _idx_stats.get("automation_sync", {})
        _mcsl_sync  = _idx_stats.get("server_sync", {})

        # Wiki chunk count lives in the knowledge collection (not code collection)
        _wiki_cnt = 0
        try:
            import chromadb as _chromadb
            _kb_client = _chromadb.PersistentClient(path=config.CHROMA_PATH)
            _kb_col = _kb_client.get_collection(config.CHROMA_COLLECTION)
            _wiki_cnt = len(_kb_col.get(where={"source_type": "wiki"}, include=[])["ids"])
        except Exception:
            pass

        def _wiki_badge(cnt):
            return f"✅ {cnt} chunks" if cnt > 0 else "⬜ Not indexed"

        st.markdown(
            f"<div style='font-size:0.75rem;line-height:1.8'>"
            f"<b>✍️ Automation:</b> {_sync_badge(_auto_cnt, _auto_sync)}<br>"
            f"<b>🏪 MCSL App:</b> {_sync_badge(_mcsl_cnt, _mcsl_sync)}<br>"
            f"<b>📖 Wiki:</b> {_wiki_badge(_wiki_cnt)}"
            f"</div>",
            unsafe_allow_html=True,
        )

        # ── Automation Code ───────────────────────────────────────────────
        with st.expander("✍️ Automation Code"):
            auto_path = st.text_input(
                "Automation repo path", key="automation_code_path",
                value=st.session_state.get("automation_code_path", ""),
                placeholder="/path/to/mcsl-test-automation",
            )
            auto_info = {}
            if auto_path:
                try:
                    from rag.code_indexer import get_repo_info
                    auto_info = get_repo_info(auto_path)
                except Exception:  # noqa: BLE001
                    pass
            auto_branches = auto_info.get("branches", [])
            auto_current  = auto_info.get("current_branch", "")
            auto_commit   = auto_info.get("commit", "")
            if auto_branches:
                _auto_idx = auto_branches.index(auto_current) if auto_current in auto_branches else 0
                st.selectbox("Branch to pull", auto_branches, index=_auto_idx, key="auto_branch_select")
                st.caption(f"Current: `{auto_current}` @ `{auto_commit}`")
            elif auto_path:
                st.caption(f"Current: `{auto_current or 'unknown'}` @ `{auto_commit}`" if auto_current else "⚠️ Branch info unavailable")
            col_sync, col_idx = st.columns(2)
            with col_sync:
                if st.button("Pull & Sync", key="auto_sync_btn"):
                    from rag.code_indexer import sync_from_git
                    branch = st.session_state.get("auto_branch_select", auto_current or "main")
                    with st.spinner("Syncing…"):
                        sync_from_git(auto_path, "automation", branch)
                    st.success("Synced.")
                    st.rerun()
            with col_idx:
                if st.button("Full Re-index", key="auto_reindex_btn"):
                    from rag.code_indexer import index_codebase
                    with st.spinner("Re-indexing…"):
                        index_codebase(auto_path, "automation", clear_existing=True)
                    st.success("Re-indexed.")
                    st.rerun()

        # ── MCSL App Code (single repo — server + client) ─────────────────
        with st.expander("🏪 MCSL App Code"):
            mcsl_code_path = st.text_input(
                "Repo path", key="mcsl_code_path",
                value=st.session_state.get("mcsl_code_path", ""),
                placeholder="/path/to/storepep-react/storepepSAAS/server/src/shared",
            )
            mcsl_info = {}
            if mcsl_code_path:
                try:
                    from rag.code_indexer import get_repo_info
                    mcsl_info = get_repo_info(mcsl_code_path)
                except Exception:  # noqa: BLE001
                    pass
            mcsl_branches = mcsl_info.get("branches", [])
            mcsl_current  = mcsl_info.get("current_branch", "")
            mcsl_commit   = mcsl_info.get("commit", "")
            if mcsl_branches:
                _mcsl_idx = mcsl_branches.index(mcsl_current) if mcsl_current in mcsl_branches else 0
                st.selectbox("Branch to pull", mcsl_branches, index=_mcsl_idx, key="mcsl_branch_select")
                st.caption(f"Current: `{mcsl_current}` @ `{mcsl_commit}`")
            elif mcsl_code_path:
                st.caption(f"Current: `{mcsl_current or 'unknown'}` @ `{mcsl_commit}`" if mcsl_current else "⚠️ Branch info unavailable")
            col_sync, col_idx = st.columns(2)
            with col_sync:
                if st.button("Pull & Sync", key="mcsl_sync_btn"):
                    from rag.code_indexer import sync_from_git
                    branch = st.session_state.get("mcsl_branch_select", mcsl_current or "main")
                    with st.spinner("Syncing…"):
                        sync_from_git(mcsl_code_path, "storepepsaas_server", branch)
                    st.success("Synced.")
                    st.rerun()
            with col_idx:
                if st.button("Full Re-index", key="mcsl_reindex_btn"):
                    from rag.code_indexer import index_codebase
                    with st.spinner("Re-indexing…"):
                        index_codebase(mcsl_code_path, "storepepsaas_server", clear_existing=True)
                    st.success("Re-indexed.")
                    st.rerun()

        # ── MCSL Wiki (documents) ─────────────────────────────────────────
        with st.expander("📖 MCSL Wiki"):
            wiki_path = st.text_input(
                "Wiki path", key="wiki_path",
                value=st.session_state.get("wiki_path", getattr(config, "WIKI_PATH", "")),
                placeholder="/path/to/mcsl-wiki/wiki",
            )
            if wiki_path:
                from pathlib import Path as _Path
                _wiki_exists = _Path(wiki_path).exists()
                if _wiki_exists:
                    _md_count = len(list(_Path(wiki_path).rglob("*.md")))
                    st.caption(f"{_md_count} markdown files found")
                else:
                    st.warning("⚠️ Wiki path not found")
            if st.button("Re-index Wiki", key="wiki_reindex_btn", disabled=not wiki_path):
                with st.spinner("Indexing wiki docs…"):
                    try:
                        import os as _os
                        _orig_wiki = _os.environ.get("WIKI_PATH", "")
                        _os.environ["WIKI_PATH"] = wiki_path
                        from ingest.wiki_loader import load_wiki_docs
                        from rag.vectorstore import get_vectorstore
                        _docs = load_wiki_docs()
                        if _docs:
                            _vs = get_vectorstore()
                            _vs.add_documents(_docs)
                            st.success(f"✅ Indexed {len(_docs)} wiki chunks.")
                            st.rerun()
                        else:
                            st.warning("No wiki documents found.")
                        if _orig_wiki:
                            _os.environ["WIKI_PATH"] = _orig_wiki
                    except Exception as _wiki_err:
                        st.error(f"Wiki index failed: {_wiki_err}")

        st.divider()

        # ── Dry Run toggle ────────────────────────────────────────────────
        dry_run = st.toggle("🧪 Dry Run (no writes)", key="dry_run", value=False)
        st.caption("Generates output without writing to Trello, repo, or Sheets.")

    # ── Pipeline header ────────────────────────────────────────────────────
    st.markdown(
        '<div class="pipeline-header">'
        '<h1>🚚 MCSL QA Pipeline</h1>'
        '<p>AI-powered QA orchestration for MCSL carriers</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # ── 7-tab layout ───────────────────────────────────────────────────────
    tab_us, tab_devdone, tab_release, tab_history, tab_signoff, tab_manual, tab_run = st.tabs([
        "📝 User Story",
        "🔀 Move Cards",
        "🚀 Release QA",
        "📋 History",
        "✅ Sign Off",
        "✍️ Write Automation",
        "▶️ Run Automation",
    ])

    with tab_us:
        st.subheader("📝 User Story Writer")
        st.caption("Generate User Story + Acceptance Criteria from a plain-English feature description.")

        # ── Generate ──────────────────────────────────────────────────────
        request_text = st.text_area(
            "What do you want to build?",
            key="us_request_input",
            height=120,
            placeholder="e.g. Allow merchants to configure UPS SurePost as a shipping option...",
        )

        if st.button("✨ Generate", key="us_generate_btn", type="primary"):
            if not request_text.strip():
                st.warning("Enter a feature description first.")
            else:
                with st.spinner("Generating User Story…"):
                    try:
                        from pipeline.user_story_writer import generate_user_story
                        result = generate_user_story(request_text.strip())
                        st.session_state["us_result"] = result
                        st.session_state.setdefault("us_history", []).append(result)
                    except Exception as exc:
                        st.error(f"Generation failed: {exc}")

        # ── Result display + Refine ───────────────────────────────────────
        if st.session_state.get("us_result"):
            st.divider()
            st.markdown(st.session_state["us_result"])

            st.subheader("🔁 Refine")
            change_req = st.text_area(
                "What should change?",
                key="us_change_input",
                height=80,
                placeholder="e.g. Add a scenario for when the carrier account is inactive...",
            )
            if st.button("🔁 Refine", key="us_refine_btn"):
                if not change_req.strip():
                    st.warning("Describe what to change.")
                else:
                    with st.spinner("Refining…"):
                        try:
                            from pipeline.user_story_writer import refine_user_story
                            refined = refine_user_story(
                                st.session_state["us_result"], change_req.strip()
                            )
                            st.session_state["us_result"] = refined
                            st.session_state.setdefault("us_history", []).append(refined)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Refine failed: {exc}")

            # ── Push to Trello ─────────────────────────────────────────────
            st.divider()
            st.subheader("📌 Push to Trello")

            col_title, col_mode = st.columns([3, 2])
            with col_title:
                st.text_input("Card title", key="us_card_title",
                              placeholder="Feature: UPS SurePost support")
            with col_mode:
                st.radio("List", ["Existing list", "Create new list"],
                         key="us_list_mode", horizontal=True)

            # Fetch board lists for selectors
            try:
                from pipeline.trello_client import TrelloClient
                _tc = TrelloClient()
                _all_lists = _tc.get_lists()
                _list_names = [l.name for l in _all_lists]
                _list_id_map = {l.name: l.id for l in _all_lists}
                _members = _tc.get_board_members()
                _member_names = [m["fullName"] for m in _members]
                _member_id_map = {m["fullName"]: m["id"] for m in _members}
            except Exception as exc:
                st.warning(f"Could not connect to Trello: {exc}")
                _list_names = []
                _list_id_map = {}
                _members = []
                _member_names = []
                _member_id_map = {}

            if st.session_state["us_list_mode"] == "Existing list":
                st.selectbox("Target list", _list_names or ["(no lists found)"],
                             key="us_existing_list")
            else:
                st.text_input("New list name", key="us_new_list_name",
                              placeholder="Sprint 43 Backlog")

            st.multiselect("Assign members", _member_names, key="us_assign_members")

            if st.button("📌 Create Trello Card", key="us_push_btn", type="primary"):
                card_title = st.session_state.get("us_card_title", "").strip()
                if not card_title:
                    st.warning("Enter a card title.")
                elif not trello_ok:
                    st.error("Trello credentials not configured. Set TRELLO_API_KEY, TRELLO_TOKEN, TRELLO_BOARD_ID in .env")
                else:
                    with st.spinner("Creating Trello card…"):
                        try:
                            from pipeline.trello_client import TrelloClient
                            tc = TrelloClient()

                            # Resolve list_id
                            if st.session_state["us_list_mode"] == "Create new list":
                                new_name = st.session_state.get("us_new_list_name", "").strip()
                                if not new_name:
                                    st.warning("Enter a name for the new list.")
                                    st.stop()
                                tlist = tc.create_list(new_name)
                                list_id = tlist.id
                                list_name = tlist.name
                            else:
                                chosen = st.session_state.get("us_existing_list", "")
                                list_id = _list_id_map.get(chosen, "")
                                list_name = chosen
                                if not list_id:
                                    st.warning(f"List '{chosen}' not found on board.")
                                    st.stop()

                            # Resolve member IDs
                            selected_members = st.session_state.get("us_assign_members", [])
                            member_ids = [_member_id_map[n] for n in selected_members
                                          if n in _member_id_map]

                            card = tc.create_card_in_list(
                                list_id=list_id,
                                name=card_title,
                                desc=st.session_state["us_result"],
                                member_ids=member_ids,
                            )

                            # Save to history
                            from datetime import datetime
                            runs = st.session_state.get("pipeline_runs", {})
                            runs[card.id] = {
                                "card_name":   card_title,
                                "approved_at": datetime.now().isoformat(timespec="seconds"),
                                "card_url":    card.url,
                                "release":     st.session_state.get("rqa_release", ""),
                                "test_cases":  "",
                                "rag_chunks":  0,
                            }
                            st.session_state["pipeline_runs"] = runs
                            if not dry_run:
                                _save_history(runs)

                            st.success(
                                f"Card created: [{card_title}]({card.url}) in list **{list_name}**"
                            )
                        except Exception as exc:
                            st.error(f"Failed to create Trello card: {exc}")

    with tab_devdone:
        st.subheader("🔀 Move Cards")
        st.caption("Move Trello cards between lists in bulk with an audit comment.")

        # ── List selectors ───────────────────────────────────────────────
        # Fetch board lists (show empty selects if Trello not configured)
        try:
            from pipeline.trello_client import TrelloClient
            _dd_tc = TrelloClient()
            _dd_lists = _dd_tc.get_lists()
            _dd_list_names = [l.name for l in _dd_lists]
            _dd_list_id_map = {l.name: l.id for l in _dd_lists}
        except Exception as exc:
            st.warning(f"Could not connect to Trello: {exc}")
            _dd_list_names = []
            _dd_list_id_map = {}

        col_src, col_tgt, col_load = st.columns([3, 3, 1])
        with col_src:
            source_list = st.selectbox(
                "Source list",
                _dd_list_names or ["Dev Done"],
                key="dd_list_select",
                index=0,
            )
        with col_tgt:
            # Default target: "Ready for QA" if present, else first list
            default_tgt_idx = 0
            if "Ready for QA" in _dd_list_names:
                default_tgt_idx = _dd_list_names.index("Ready for QA")
            st.selectbox(
                "Target list",
                _dd_list_names or ["Ready for QA"],
                key="dd_move_target",
                index=default_tgt_idx,
            )
        with col_load:
            st.write("")  # vertical align
            load_btn = st.button("📥 Load", key="dd_load_btn")

        if load_btn:
            source_id = _dd_list_id_map.get(source_list, "")
            if not source_id:
                st.warning(f"List '{source_list}' not found on board.")
            else:
                with st.spinner("Loading cards…"):
                    try:
                        from pipeline.trello_client import TrelloClient
                        tc = TrelloClient()
                        cards = tc.get_cards_in_list(source_id)
                        st.session_state["dd_cards"] = cards
                        st.session_state["dd_checked"] = {c.id: False for c in cards}
                        st.session_state["dd_select_all"] = False
                    except Exception as exc:
                        st.error(f"Failed to load cards: {exc}")

        # ── Card list with checkboxes ────────────────────────────────────
        cards = st.session_state.get("dd_cards", [])
        if cards:
            st.divider()
            # Select-all toggle
            select_all = st.checkbox(
                f"Select all ({len(cards)} cards)",
                key="dd_select_all",
                value=st.session_state.get("dd_select_all", False),
            )
            if select_all:
                for c in cards:
                    st.session_state["dd_checked"][c.id] = True

            # Per-card checkboxes
            checked = st.session_state.get("dd_checked", {})
            for card in cards:
                checked[card.id] = st.checkbox(
                    card.name,
                    key=f"dd_chk_{card.id}",
                    value=checked.get(card.id, False),
                )
            st.session_state["dd_checked"] = checked

            # ── Move button ───────────────────────────────────────────────
            n_checked = sum(1 for v in checked.values() if v)
            move_target = st.session_state.get("dd_move_target", "")
            if st.button(f"➡️ Move {n_checked} cards", key="dd_move_btn",
                         type="primary", disabled=(n_checked == 0)):
                target_id = _dd_list_id_map.get(move_target, "")
                if not target_id:
                    st.warning(f"Target list '{move_target}' not found.")
                else:
                    moved = 0
                    errors = []
                    with st.spinner(f"Moving {n_checked} cards…"):
                        try:
                            from pipeline.trello_client import TrelloClient
                            tc = TrelloClient()
                            for card in cards:
                                if not checked.get(card.id):
                                    continue
                                try:
                                    if not dry_run:
                                        tc.move_card_to_list_by_id(card.id, target_id)
                                        tc.add_comment(
                                            card.id,
                                            f"Moved to {move_target} by MCSL QA Pipeline",
                                        )
                                    moved += 1
                                except Exception as exc:
                                    errors.append(f"{card.name}: {exc}")
                        except Exception as exc:
                            st.error(f"Trello error: {exc}")

                    if moved:
                        st.success(
                            f"{'(dry run) ' if dry_run else ''}Moved {moved} card(s) to **{move_target}**."
                        )
                        # Clear loaded cards after move
                        st.session_state["dd_cards"] = []
                        st.session_state["dd_checked"] = {}
                    for err in errors:
                        st.warning(err)
        elif st.session_state.get("dd_cards") == []:
            pass  # Not yet loaded — show nothing

    with tab_release:
        st.markdown("## 🔬 Release QA Pipeline")

        # ── Board / list selector ────────────────────────────────────────────
        try:
            trello = TrelloClient()
            all_lists = trello.get_lists()
        except Exception as _e:
            st.error(f"Trello connection failed: {_e}")
            all_lists = []

        list_options = {lst.name: lst.id for lst in all_lists} if all_lists else {}
        list_names = list(list_options.keys())

        col_list, col_release, col_load = st.columns([3, 2, 1])
        with col_list:
            selected_list_name = st.selectbox(
                "Select Trello List",
                options=list_names,
                index=list_names.index(st.session_state["rqa_list_name"])
                if st.session_state["rqa_list_name"] in list_names else 0,
                key="rqa_list_selector",
            )
        with col_release:
            release_label = st.text_input(
                "Release Label",
                value=st.session_state.get("rqa_release", ""),
                placeholder="e.g. MCSLapp 1.2.3",
                key="rqa_release_input",
            )
        with col_load:
            st.markdown("<br>", unsafe_allow_html=True)
            load_clicked = st.button("Load Cards", type="primary", key="rqa_load_btn")

        if load_clicked and selected_list_name and list_options:
            selected_list_id = list_options[selected_list_name]
            with st.spinner(f"Loading cards from '{selected_list_name}'…"):
                try:
                    cards = trello.get_cards_in_list(selected_list_id)
                    st.session_state["rqa_cards"] = cards
                    st.session_state["rqa_list_name"] = selected_list_name
                    st.session_state["rqa_board_id"] = selected_list_id
                    st.session_state["rqa_release"] = release_label

                    # Validate each card
                    for card in cards:
                        vr = validate_card(
                            card_name=card.name,
                            card_desc=card.desc or "",
                            acceptance_criteria=st.session_state.get(f"ac_suggestion_{card.id}", card.desc or ""),
                        )
                        st.session_state[f"validation_{card.id}"] = vr

                    # Release intelligence analysis
                    ra_cards = [RASummary(card_id=c.id, card_name=c.name, card_desc=c.desc or "") for c in cards]
                    st.session_state["release_analysis"] = analyse_release(
                        release_name=release_label or selected_list_name,
                        cards=ra_cards,
                    )
                    st.rerun()
                except Exception as _load_err:
                    st.error(f"Failed to load cards: {_load_err}")

        cards: list = st.session_state.get("rqa_cards", [])

        if not cards:
            st.info("Select a Trello list and click **Load Cards** to begin Release QA.")
        else:
            # ── Health summary ───────────────────────────────────────────────
            approved_store: dict = st.session_state.get("rqa_approved", {})
            val_statuses = [st.session_state.get(f"validation_{c.id}") for c in cards]
            n_pass   = sum(1 for v in val_statuses if v and v.overall_status == "PASS")
            n_review = sum(1 for v in val_statuses if v and v.overall_status == "NEEDS_REVIEW")
            n_fail   = sum(1 for v in val_statuses if v and v.overall_status == "FAIL")
            approved_count = sum(1 for v in approved_store.values() if v)

            hcols = st.columns(5)
            hcols[0].metric("Total Cards", len(cards))
            hcols[1].metric("✅ Pass", n_pass)
            hcols[2].metric("⚠️ Needs Review", n_review)
            hcols[3].metric("❌ Fail", n_fail)
            hcols[4].metric("🏆 Approved", approved_count)

            st.divider()

            # ── Release Intelligence ─────────────────────────────────────────
            ra: ReleaseAnalysis | None = st.session_state.get("release_analysis")
            if ra and not ra.error:
                risk_emoji = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(ra.risk_level, "⚪")
                with st.expander(f"{risk_emoji} Release Intelligence — {ra.risk_level} RISK: {ra.risk_summary}", expanded=False):
                    if ra.conflicts:
                        st.markdown("**⚡ Conflicts:**")
                        for conflict in ra.conflicts:
                            st.markdown(f"- **{conflict.get('area','')}**: {conflict.get('description','')} ({', '.join(conflict.get('cards',[]))})")
                    if ra.ordering:
                        st.markdown("**📋 Suggested Test Order:**")
                        for item in ra.ordering:
                            st.markdown(f"{item.get('position','')}. **{item.get('card_name','')}** — {item.get('reason','')}")
                    if ra.coverage_gaps:
                        st.markdown("**🔍 Coverage Gaps:**")
                        for gap in ra.coverage_gaps:
                            st.markdown(f"- {gap}")
                    if ra.kb_context_summary:
                        st.caption(f"KB: {ra.kb_context_summary}")

            st.divider()

            # ── Per-card accordions ──────────────────────────────────────────
            tc_store: dict = st.session_state.get("rqa_test_cases", {})

            for card in cards:
                _vr: ValidationReport | None = st.session_state.get(f"validation_{card.id}")
                _status_icon = {"PASS": "✅", "NEEDS_REVIEW": "⚠️", "FAIL": "❌"}.get(
                    _vr.overall_status if _vr else "", "🔵"
                )
                _approved_badge = " 🏆" if approved_store.get(card.id) else ""

                with st.expander(f"{_status_icon} {card.name}{_approved_badge}", expanded=False):

                    # ── Step 1a: Card details ────────────────────────────────
                    st.markdown("### Step 1: Card Details & Validation")
                    st.markdown(f"**Card:** [{card.name}]({card.url})")
                    if card.desc:
                        with st.expander("Card Description", expanded=False):
                            st.markdown(card.desc)

                    # ── Step 1b: Validation display ──────────────────────────
                    if _vr:
                        if _vr.error:
                            st.warning(f"Validation error: {_vr.error}")
                        else:
                            _badge_color = {"PASS": "green", "NEEDS_REVIEW": "orange", "FAIL": "red"}.get(_vr.overall_status, "gray")
                            st.markdown(f"**Domain Validation:** :{_badge_color}[{_vr.overall_status}] — {_vr.summary}")
                            if _vr.requirement_gaps or _vr.ac_gaps or _vr.accuracy_issues:
                                with st.expander("🔍 Validation Issues", expanded=_vr.overall_status == "FAIL"):
                                    if _vr.requirement_gaps:
                                        st.markdown("**Requirement Gaps:**")
                                        for g in _vr.requirement_gaps:
                                            st.markdown(f"- {g}")
                                    if _vr.ac_gaps:
                                        st.markdown("**AC Gaps:**")
                                        for g in _vr.ac_gaps:
                                            st.markdown(f"- {g}")
                                    if _vr.accuracy_issues:
                                        st.markdown("**Accuracy Issues:**")
                                        for g in _vr.accuracy_issues:
                                            st.markdown(f"- {g}")
                            if _vr.suggestions:
                                with st.expander("💡 Suggestions"):
                                    for s in _vr.suggestions:
                                        st.markdown(f"- {s}")
                            if _vr.kb_insights:
                                st.caption(f"KB Insights: {_vr.kb_insights}")
                    else:
                        st.info("Validation not yet run. Reload cards to validate.")

                    # ── Step 1c: AC generation ───────────────────────────────
                    st.markdown("#### AC Generation")
                    _ac_key = f"ac_suggestion_{card.id}"
                    _ac_saved_key = f"ac_saved_{card.id}"

                    if st.button("✨ Generate AC", key=f"gen_ac_{card.id}"):
                        with st.spinner("Generating Acceptance Criteria…"):
                            try:
                                ac_text = generate_acceptance_criteria(
                                    raw_request=card.desc or card.name,
                                    attachments=card.attachments or None,
                                    checklists=card.checklists or None,
                                )
                                st.session_state[_ac_key] = ac_text
                                st.session_state[_ac_saved_key] = False
                            except Exception as _ac_err:
                                st.error(f"AC generation failed: {_ac_err}")

                    if st.session_state.get(_ac_key):
                        _edited_ac = st.text_area(
                            "Acceptance Criteria",
                            value=st.session_state[_ac_key],
                            height=200,
                            key=f"ac_editor_{card.id}",
                        )
                        st.session_state[_ac_key] = _edited_ac

                        if not st.session_state.get(_ac_saved_key):
                            if st.button("💾 Save AC to Trello", key=f"save_ac_{card.id}"):
                                try:
                                    trello.update_card_description(card.id, _edited_ac)
                                    st.session_state[_ac_saved_key] = True
                                    st.success("AC saved to Trello card description.")
                                except Exception as _save_err:
                                    st.error(f"Failed to save AC: {_save_err}")
                        else:
                            st.success("✅ AC saved to Trello")

                    st.divider()

                    # ── Step 2: AI QA Agent ──────────────────────────────────
                    st.markdown("### Step 2: AI QA Agent")

                    _sav_running_key    = f"sav_running_{card.id}"
                    _sav_stop_key       = f"sav_stop_{card.id}"
                    _sav_stop_event_key = f"sav_stop_event_{card.id}"
                    _sav_result_key     = f"sav_result_{card.id}"
                    _sav_prog_key       = f"sav_prog_{card.id}"
                    _sav_report_key     = f"sav_report_{card.id}"
                    _sav_url_key        = f"sav_url_{card.id}"
                    _sav_complexity_key = f"sav_complexity_{card.id}"

                    _is_running = st.session_state.get(_sav_running_key, False)

                    url_val = st.text_input(
                        "App URL",
                        value=st.session_state.get(_sav_url_key, ""),
                        placeholder="https://admin.shopify.com/store/YOUR-STORE/apps/mcsl-app",
                        key=_sav_url_key,
                        disabled=_is_running,
                    )
                    complexity_val = st.number_input(
                        "Max Scenarios",
                        min_value=1, max_value=10,
                        value=st.session_state.get(_sav_complexity_key, 3),
                        key=_sav_complexity_key,
                        disabled=_is_running,
                    )

                    ac_for_agent = st.session_state.get(_ac_key, card.desc or "")

                    _btn_col, _stop_col = st.columns([3, 1])
                    with _btn_col:
                        run_clicked = st.button(
                            "🤖 Run AI QA Agent",
                            key=f"run_sav_{card.id}",
                            disabled=_is_running or not url_val,
                            type="primary",
                        )
                    with _stop_col:
                        stop_clicked = st.button(
                            "⏹ Stop",
                            key=f"stop_sav_{card.id}",
                            disabled=not _is_running,
                        )

                    if stop_clicked and _is_running:
                        st.session_state[_sav_stop_key] = True
                        _ev = st.session_state.get(_sav_stop_event_key)
                        if _ev:
                            _ev.set()

                    if run_clicked and url_val and not _is_running:
                        import threading as _threading
                        _stop_event = _threading.Event()
                        st.session_state[_sav_running_key]    = True
                        st.session_state[_sav_stop_key]       = False
                        st.session_state[_sav_stop_event_key] = _stop_event
                        st.session_state[_sav_result_key]     = {"done": False}
                        st.session_state.pop(_sav_prog_key, None)

                        def _run_sav_thread(
                            _url=url_val,
                            _ac=ac_for_agent,
                            _max=int(complexity_val),
                            _event=_stop_event,
                            _rk=_sav_result_key,
                            _sk=_sav_stop_key,
                            _sek=_sav_stop_event_key,
                            _pk=_sav_prog_key,
                            _repk=_sav_report_key,
                        ):
                            try:
                                def _prog_cb(sc_idx, sc_title, step_num, step_desc):
                                    pct = min(0.05 + sc_idx * 0.3 + step_num * 0.05, 0.95)
                                    st.session_state[_pk] = {
                                        "pct": pct,
                                        "text": f"[{sc_title}] Step {step_num}: {step_desc}",
                                    }

                                report = verify_ac(
                                    app_url=_url,
                                    ac_text=_ac,
                                    stop_flag=lambda: _event.is_set() or st.session_state.get(_sk, False),
                                    progress_callback=_prog_cb,
                                    max_scenarios=_max,
                                )
                                st.session_state[_repk] = report
                                st.session_state[_rk] = {"done": True, "report": report, "error": None}
                            except Exception as _ex:
                                st.session_state[_rk] = {"done": True, "report": None, "error": str(_ex)}
                            finally:
                                st.session_state.pop(_sek, None)
                                st.session_state[_sav_running_key] = False

                        _threading.Thread(target=_run_sav_thread, daemon=True).start()
                        st.rerun()

                    # Progress display
                    if _is_running:
                        _prog = st.session_state.get(_sav_prog_key, {})
                        st.progress(_prog.get("pct", 0.05), text=_prog.get("text", "Running AI QA Agent…"))
                        st.caption("Agent is running. Results appear when complete.")
                        import time as _time
                        _time.sleep(3)
                        st.rerun()

                    # Results display
                    _result = st.session_state.get(_sav_result_key, {})
                    if _result.get("done"):
                        if _result.get("error"):
                            st.error(f"Agent error: {_result['error']}")
                        elif _result.get("report"):
                            _rpt = _result["report"]
                            _verdict_icon = {"pass": "✅", "fail": "❌", "partial": "⚠️"}.get(
                                getattr(_rpt, "verdict", "").lower(), "🔵"
                            )
                            st.success(f"{_verdict_icon} Agent completed — verdict: {getattr(_rpt, 'verdict', 'N/A')}")
                            with st.expander("📋 Full QA Agent Report", expanded=False):
                                st.json(_rpt.to_dict() if hasattr(_rpt, "to_dict") else str(_rpt))

                    st.divider()

                    # ── Step 3: Test Case Generation ─────────────────────────
                    st.markdown("### Step 3: Test Cases")

                    _tc_key  = f"tc_text_{card.id}"
                    _regen_key = f"force_regen_{card.id}"
                    _existing_tc_key = f"show_existing_tc_{card.id}"
                    _existing_tcs_in_store = tc_store.get(card.id, "")

                    # Show AI QA Agent results if available
                    _sav_rpt = st.session_state.get(f"sav_report_{card.id}")
                    if _sav_rpt:
                        with st.expander("🤖 AI QA Agent Results (reference)", expanded=False):
                            st.json(_sav_rpt.to_dict() if hasattr(_sav_rpt, "to_dict") else str(_sav_rpt))

                    _has_tc = bool(st.session_state.get(_tc_key, "").strip())
                    _force_regen = st.session_state.get(_regen_key, False)

                    _gen_col, _regen_col = st.columns([3, 1])
                    with _gen_col:
                        _gen_tc_clicked = st.button(
                            "📋 Generate Test Cases",
                            key=f"gen_tc_{card.id}",
                            disabled=_has_tc and not _force_regen,
                        )
                    with _regen_col:
                        if _has_tc:
                            if st.button("🔄 Regenerate", key=f"regen_tc_{card.id}"):
                                st.session_state[_regen_key] = True
                                st.session_state[_tc_key] = ""
                                st.rerun()

                    if _gen_tc_clicked or (_force_regen and not _has_tc):
                        with st.spinner("Generating test cases…"):
                            try:
                                generated_tcs = generate_test_cases(card)
                                st.session_state[_tc_key] = generated_tcs
                                tc_store[card.id] = generated_tcs
                                st.session_state["rqa_test_cases"] = tc_store
                                st.session_state[_regen_key] = False
                                st.rerun()
                            except Exception as _tc_err:
                                st.error(f"TC generation failed: {_tc_err}")

                    if st.session_state.get(_tc_key, "").strip():
                        _edited_tc = st.text_area(
                            "Test Cases (editable)",
                            value=st.session_state[_tc_key],
                            height=300,
                            key=f"tc_editor_{card.id}",
                        )
                        # Sync edits back to state
                        st.session_state[_tc_key] = _edited_tc
                        tc_store[card.id] = _edited_tc
                        st.session_state["rqa_test_cases"] = tc_store
                    elif _existing_tcs_in_store:
                        st.session_state[_tc_key] = _existing_tcs_in_store

                    st.divider()

                    # ── Step 4: Approval ─────────────────────────────────────
                    st.markdown("### Step 4: Approve & Save")

                    _tc_markdown = st.session_state.get(_tc_key, "").strip()
                    _is_approved = approved_store.get(card.id, False)

                    if _is_approved:
                        st.success("🏆 Approved — Test cases saved to Trello and Google Sheets.")
                    elif _tc_markdown:
                        if st.button(
                            "✅ Approve & Save to Trello + Sheets",
                            key=f"approve_{card.id}",
                            type="primary",
                        ):
                            with st.spinner("Saving to Trello and Google Sheets…"):
                                _approve_errors = []

                                # Write to Trello
                                try:
                                    write_test_cases_to_card(
                                        card_id=card.id,
                                        test_cases=_tc_markdown,
                                        trello=trello,
                                        release=st.session_state.get("rqa_release", ""),
                                        card_name=card.name,
                                    )
                                except Exception as _trello_err:
                                    _approve_errors.append(f"Trello: {_trello_err}")

                                # Write to Google Sheets
                                _sheet_result = None
                                try:
                                    _sheet_result = append_to_sheet(
                                        card_name=card.name,
                                        test_cases_markdown=_tc_markdown,
                                        release=st.session_state.get("rqa_release", ""),
                                    )
                                except Exception as _sheet_err:
                                    _approve_errors.append(f"Sheets: {_sheet_err}")

                                # Mark approved + save history
                                approved_store[card.id] = True
                                st.session_state["rqa_approved"] = approved_store
                                _save_history({
                                    **_load_history(),
                                    card.id: {
                                        "card_name": card.name,
                                        "card_url": card.url,
                                        "approved_at": __import__("datetime").datetime.now().isoformat(),
                                        "release": st.session_state.get("rqa_release", ""),
                                    },
                                })

                                # Show results
                                if _approve_errors:
                                    for _err in _approve_errors:
                                        st.warning(f"⚠️ {_err}")
                                else:
                                    st.success("✅ Saved to Trello!")

                                if _sheet_result:
                                    if _sheet_result.get("rows_added"):
                                        st.success(
                                            f"📊 Saved {_sheet_result['rows_added']} test case(s) "
                                            f"to sheet tab **'{_sheet_result['tab']}'**"
                                        )
                                    if _sheet_result.get("duplicates"):
                                        st.warning(
                                            f"⚠️ {len(_sheet_result['duplicates'])} potential duplicate(s) detected in sheet"
                                        )

                                st.rerun()
                    else:
                        st.info("Generate test cases in Step 3 before approving.")

                    st.divider()

                    # ── Step 5: Write Automation ──────────────────────────────
                    st.markdown("### Step 5: Write Automation")

                    _auto_tc_src = st.session_state.get(f"tc_text_{card.id}", "").strip()
                    _is_approved_for_auto = approved_store.get(card.id, False)

                    if not _is_approved_for_auto:
                        st.info("Approve test cases in Step 4 before writing automation.")
                    else:
                        with st.expander("⚙️ Generate Playwright automation for this card", expanded=False):
                            _auto_feat_key = f"auto_feat_{card.id}"
                            _auto_res_key = f"auto_res_{card.id}"
                            _auto_feat_val = st.text_input(
                                "Feature name",
                                value=st.session_state.get(_auto_feat_key, card.name),
                                key=f"auto_feat_input_{card.id}",
                            )
                            st.session_state[_auto_feat_key] = _auto_feat_val
                            _auto_tc_display = st.text_area(
                                "Test cases (from Step 3)",
                                value=_auto_tc_src,
                                height=150,
                                key=f"auto_tc_display_{card.id}",
                            )
                            if st.button("⚙️ Generate", key=f"auto_gen_{card.id}", type="primary"):
                                with st.spinner("Generating automation..."):
                                    try:
                                        from pipeline.automation_writer import write_automation
                                        _card_auto_result = write_automation(
                                            feature_name=_auto_feat_val.strip() or card.name,
                                            test_cases_markdown=_auto_tc_display.strip(),
                                        )
                                        st.session_state[_auto_res_key] = _card_auto_result
                                    except Exception as _ae:
                                        st.error(f"Automation generation failed: {_ae}")
                                st.rerun()

                            _card_auto_result = st.session_state.get(_auto_res_key)
                            if _card_auto_result:
                                if _card_auto_result.error:
                                    st.error(f"❌ {_card_auto_result.error}")
                                else:
                                    st.success("✅ Code generated")
                                    _pt, _st = st.tabs(["POM", "Spec"])
                                    with _pt:
                                        st.code(_card_auto_result.pom_code, language="typescript")
                                    with _st:
                                        st.code(_card_auto_result.spec_code, language="typescript")

                    # Phase 8: Auto-DM developers on failed verdict
                    _result_done = st.session_state.get(f"sav_result_{card.id}", {})
                    _rpt_done = st.session_state.get(f"sav_report_{card.id}")
                    if (
                        _result_done.get("done")
                        and _rpt_done is not None
                        and getattr(_rpt_done, "verdict", "").lower() == "fail"
                        and slack_configured()
                        and not st.session_state.get(f"bug_dm_sent_{card.id}", False)
                    ):
                        try:
                            _bug_desc = "; ".join(getattr(_rpt_done, "errors", []) or ["Verdict: fail"])
                            _dm_result = notify_devs_of_bug(
                                card_id=card.id,
                                card_name=card.name,
                                bug_description=_bug_desc,
                                trello_client=trello,
                                slack_client=__import__("pipeline.slack_client", fromlist=["SlackClient"]).SlackClient(),
                            )
                            if _dm_result.get("sent_count", 0) > 0:
                                st.caption(f"Bug DM sent to {_dm_result['sent_count']} developer(s)")
                            st.session_state[f"bug_dm_sent_{card.id}"] = True
                        except Exception as _dm_err:
                            logger.warning("Bug DM failed for card %s: %s", card.id, _dm_err)

    with tab_history:
        st.subheader("📋 Pipeline History")
        st.caption("All approved pipeline runs persisted to data/pipeline_history.json.")

        runs = st.session_state.get("pipeline_runs", {})

        col_count, col_clear = st.columns([4, 1])
        col_count.markdown(f"**{len(runs)} run(s) recorded**")
        with col_clear:
            if st.button("🗑️ Clear history", key="hist_clear_btn"):
                st.session_state["pipeline_runs"] = {}
                _save_history({})
                st.rerun()

        if not runs:
            st.info("No history yet. Approved cards appear here after being pushed via User Story tab or Release QA.")
        else:
            for card_id, run in runs.items():
                approved_at = run.get("approved_at", "")
                card_name   = run.get("card_name", card_id)
                label       = f"✅ {card_name}  ·  {approved_at}"
                with st.expander(label, expanded=False):
                    col1, col2 = st.columns(2)
                    col1.markdown(f"**Release**  \n{run.get('release', '—')}")
                    col2.markdown(f"**Approved at**  \n{approved_at or '—'}")
                    if run.get("card_url"):
                        st.markdown(f"[Open in Trello]({run['card_url']})")
                    tc_text = run.get("test_cases", "")
                    if tc_text:
                        with st.expander("Test Cases preview", expanded=False):
                            st.markdown(tc_text[:800] + ("…" if len(tc_text) > 800 else ""))

    with tab_signoff:
        st.markdown("## Sign Off")

        # Instantiate TrelloClient for list fetching and card moves
        try:
            trello = TrelloClient()
        except Exception:
            trello = None

        cards_so: list = st.session_state.get("rqa_cards", [])
        approved_so: dict = st.session_state.get("rqa_approved", {})
        tc_store_so: dict = st.session_state.get("rqa_test_cases", {})
        release_so: str = st.session_state.get("rqa_release", "")

        if not cards_so:
            st.info("Load cards in the **Release QA** tab first, then return here to sign off.")
        else:
            # ── Slack configuration gate ─────────────────────────────────
            if not slack_configured():
                st.warning(
                    "Slack not configured. Set `SLACK_WEBHOOK_URL` or "
                    "`SLACK_BOT_TOKEN` + `SLACK_CHANNEL` in `.env` to enable sign-off posting."
                )

            st.markdown(f"**Release:** `{release_so or '(no release label)'}`")
            st.divider()

            # ── Card approval summary ─────────────────────────────────────
            st.markdown("### Cards Verified")
            verified_cards = []
            backlog_cards  = []
            for card in cards_so:
                is_approved = approved_so.get(card.id, False)
                _verdict = getattr(
                    st.session_state.get(f"sav_report_{card.id}"), "verdict", ""
                ).lower()
                icon = "Yes" if is_approved else ("No" if _verdict == "fail" else "")
                st.checkbox(
                    f"{icon} {card.name}",
                    value=is_approved,
                    disabled=True,
                    key=f"so_check_{card.id}",
                )
                if is_approved:
                    verified_cards.append({"name": card.name, "url": card.url})

            st.divider()

            # ── Bug list ──────────────────────────────────────────────────
            st.markdown("### Bugs / Backlog Items")
            _auto_bugs = []
            for card in cards_so:
                _rpt = st.session_state.get(f"sav_report_{card.id}")
                if _rpt and getattr(_rpt, "verdict", "").lower() == "fail":
                    _errs = getattr(_rpt, "errors", []) or []
                    bug_text = f"[{card.name}] " + ("; ".join(_errs) if _errs else "Verdict: fail")
                    _auto_bugs.append(bug_text)

            _bugs_default = "\n".join(_auto_bugs) if _auto_bugs else ""
            bugs_text = st.text_area(
                "Bug / backlog items (one per line)",
                value=st.session_state.get("signoff_bugs", _bugs_default),
                height=120,
                key="signoff_bugs_input",
                placeholder="Bug title 1\nBug title 2",
            )
            st.session_state["signoff_bugs"] = bugs_text
            backlog_cards = [{"name": b.strip()} for b in bugs_text.splitlines() if b.strip()]

            st.divider()

            # ── Sign-off message composer ─────────────────────────────────
            st.markdown("### Sign-Off Message")
            _mentions_input = st.text_input(
                "Mention users (comma-separated Slack usernames, no @)",
                value=st.session_state.get("signoff_mentions", ""),
                key="signoff_mentions_input",
                placeholder="john, jane",
            )
            st.session_state["signoff_mentions"] = _mentions_input
            _mentions_list = [m.strip() for m in _mentions_input.split(",") if m.strip()]

            _cc_input = st.text_input(
                "CC (Slack username, no @)",
                value=st.session_state.get("signoff_cc", ""),
                key="signoff_cc_input",
            )
            st.session_state["signoff_cc"] = _cc_input

            _qa_lead = st.text_input(
                "QA Lead name",
                value=st.session_state.get("signoff_qa_lead", ""),
                key="signoff_qa_lead_input",
            )
            st.session_state["signoff_qa_lead"] = _qa_lead

            # Preview
            _preview_lines = []
            if _mentions_list:
                _preview_lines.append("  ".join(f"@{m}" for m in _mentions_list))
                _preview_lines.append("")
            _preview_lines.append(
                f"We've completed testing *{release_so}* and it's good for the release"
            )
            _preview_lines.append("")
            _preview_lines.append("*Cards Verified:*")
            for vc in verified_cards:
                _preview_lines.append(f"{vc['name']}\n{vc.get('url','')}")
            _preview_lines.append("")
            _preview_lines.append(f"*Cards added to backlog ({len(backlog_cards)}):*")
            for bc in backlog_cards:
                _preview_lines.append(bc["name"])
            _preview_lines.append("")
            _preview_lines.append("*QA Signed off*")
            if _cc_input:
                _preview_lines.append(f"CC: @{_cc_input.lstrip('@')}")
            if _qa_lead:
                _preview_lines.append(f"Signed by: {_qa_lead}")

            _preview_msg = "\n".join(_preview_lines)
            st.session_state["signoff_message"] = _preview_msg

            with st.expander("Preview Sign-Off Message", expanded=True):
                st.code(_preview_msg, language="")

            st.divider()

            # ── Send Sign-Off ─────────────────────────────────────────────
            _signoff_sent = st.session_state.get("signoff_sent", False)

            if _signoff_sent:
                st.success("Sign-Off sent! Release marked as QA-done.")
            else:
                _channel_override = st.text_input(
                    "Post to channel (leave blank for default)",
                    value="",
                    key="signoff_channel_override",
                    placeholder="C09F65XF4ER",
                )

                # QA-done Trello list selector
                _qa_done_list_id = ""
                if trello:
                    try:
                        _all_lists = trello.get_lists()
                        _list_opts = {lst.name: lst.id for lst in _all_lists}
                        _qa_done_name = st.selectbox(
                            "Move approved cards to list",
                            options=list(_list_opts.keys()),
                            key="signoff_qa_done_list",
                        )
                        _qa_done_list_id = _list_opts.get(_qa_done_name, "")
                    except Exception:
                        st.caption("Trello list selector unavailable.")
                else:
                    st.caption("Trello list selector unavailable.")

                _send_disabled = not slack_configured() or not verified_cards
                if st.button(
                    "Send Sign-Off",
                    type="primary",
                    disabled=_send_disabled,
                    key="send_signoff_btn",
                ):
                    with st.spinner("Sending Sign-Off to Slack..."):
                        _errors = []

                        # Post to Slack
                        try:
                            _slack_result = slack_post_signoff(
                                release=release_so,
                                verified_cards=verified_cards,
                                backlog_cards=backlog_cards,
                                mentions=_mentions_list or None,
                                cc=_cc_input,
                                qa_lead=_qa_lead,
                                channel=_channel_override.strip() or None,
                            )
                            if not _slack_result.get("ok"):
                                _errors.append(f"Slack: {_slack_result.get('error', 'unknown error')}")
                        except Exception as _se:
                            _errors.append(f"Slack: {_se}")

                        # Move approved cards to QA-done list
                        if _qa_done_list_id and trello:
                            for card in cards_so:
                                if approved_so.get(card.id):
                                    try:
                                        trello.move_card_to_list_by_id(card.id, _qa_done_list_id)
                                    except Exception as _te:
                                        _errors.append(f"Trello move {card.name}: {_te}")

                        if _errors:
                            for _err in _errors:
                                st.warning(f"{_err}")
                        else:
                            st.session_state["signoff_sent"] = True
                            st.rerun()

    with tab_manual:
        st.markdown("## ✍️ Write Automation")
        st.markdown("Generate Playwright TypeScript POM + spec files from test cases.")
        st.divider()

        _auto_feature = st.text_input(
            "Feature Name",
            value=st.session_state.get("auto_feature", ""),
            placeholder="e.g. Label Generation, Carrier Configuration",
            key="auto_feature_input",
        )
        st.session_state["auto_feature"] = _auto_feature

        _auto_tcs = st.text_area(
            "Test Cases (markdown)",
            value=st.session_state.get("auto_test_cases", ""),
            height=200,
            placeholder="## TC-01\nGiven...\nWhen...\nThen...",
            key="auto_tc_input",
        )
        st.session_state["auto_test_cases"] = _auto_tcs

        # Optional Chrome Agent exploration
        with st.expander("🔍 Explore live app (optional — captures element selectors)", expanded=False):
            st.markdown("Run the Chrome Agent to capture live MCSL app elements for better selector generation.")
            _explore_clicked = st.button(
                "🤖 Run Chrome Agent",
                key="btn_chrome_explore",
                disabled=not _auto_feature.strip() or st.session_state.get("auto_explore_running", False),
            )
            if _explore_clicked and _auto_feature.strip():
                st.session_state["auto_explore_running"] = True
                with st.spinner("Exploring MCSL app..."):
                    try:
                        from pipeline.chrome_agent import explore_feature
                        _exploration = explore_feature(_auto_feature.strip())
                        st.session_state["auto_exploration"] = _exploration
                    except Exception as _exp_err:
                        st.warning(f"Chrome Agent failed: {_exp_err}")
                st.session_state["auto_explore_running"] = False
                st.rerun()

            _exploration_result = st.session_state.get("auto_exploration")
            if _exploration_result:
                if _exploration_result.error:
                    st.warning(f"⚠️ Exploration error: {_exploration_result.error}")
                else:
                    st.success(f"✅ Explored: {_exploration_result.nav_destination}")
                    st.caption(f"AX tree captured ({len(_exploration_result.ax_tree_text)} chars)")

        st.divider()

        _gen_auto_clicked = st.button(
            "⚙️ Generate Automation Code",
            key="btn_gen_auto",
            type="primary",
            disabled=not (_auto_feature.strip() and _auto_tcs.strip()),
        )

        if _gen_auto_clicked:
            with st.spinner("Generating Playwright automation..."):
                try:
                    from pipeline.automation_writer import write_automation
                    _exploration_data = ""
                    _exp = st.session_state.get("auto_exploration")
                    if _exp and not _exp.error:
                        _exploration_data = _exp.elements_json
                    _auto_result = write_automation(
                        feature_name=_auto_feature.strip(),
                        test_cases_markdown=_auto_tcs.strip(),
                        exploration_data=_exploration_data,
                    )
                    st.session_state["auto_result"] = _auto_result
                except Exception as _auto_err:
                    st.error(f"Code generation failed: {_auto_err}")
            st.rerun()

        _auto_result = st.session_state.get("auto_result")
        if _auto_result:
            if _auto_result.error:
                st.error(f"❌ Generation failed: {_auto_result.error}")
            else:
                st.success("✅ Automation code generated!")
                _pom_tab, _spec_tab = st.tabs(["📄 POM", "🧪 Spec"])
                with _pom_tab:
                    st.caption(f"Path: `{_auto_result.pom_path}`")
                    st.code(_auto_result.pom_code, language="typescript")
                    st.download_button(
                        "⬇️ Download POM",
                        data=_auto_result.pom_code,
                        file_name=_auto_result.pom_path.split("/")[-1] if _auto_result.pom_path else "page.ts",
                        mime="text/plain",
                        key="dl_pom",
                    )
                with _spec_tab:
                    st.caption(f"Path: `{_auto_result.spec_path}`")
                    st.code(_auto_result.spec_code, language="typescript")
                    st.download_button(
                        "⬇️ Download Spec",
                        data=_auto_result.spec_code,
                        file_name=_auto_result.spec_path.split("/")[-1] if _auto_result.spec_path else "spec.ts",
                        mime="text/plain",
                        key="dl_spec",
                    )

                st.divider()
                st.markdown("### 🚀 Push to Git Branch")
                _repo_path = getattr(__import__("config"), "MCSL_AUTOMATION_REPO_PATH", "")
                if not _repo_path:
                    st.warning("⚠️ MCSL_AUTOMATION_REPO_PATH not set in config.py — cannot push.")
                else:
                    _branch_preview = "automation/" + __import__("re").sub(r"[^a-z0-9]+", "-", _auto_feature.lower()).strip("-")
                    st.caption(f"Branch: `{_branch_preview}`")
                    if st.button("🚀 Push to Git Branch", key="btn_push_git", type="primary"):
                        with st.spinner("Pushing to GitHub..."):
                            try:
                                from pipeline.automation_writer import push_to_branch
                                import os
                                _pom_abs = os.path.join(_repo_path, _auto_result.pom_path) if _auto_result.pom_path else ""
                                _spec_abs = os.path.join(_repo_path, _auto_result.spec_path) if _auto_result.spec_path else ""
                                # Write files first
                                if _pom_abs and _auto_result.pom_code:
                                    os.makedirs(os.path.dirname(_pom_abs), exist_ok=True)
                                    open(_pom_abs, "w").write(_auto_result.pom_code)
                                if _spec_abs and _auto_result.spec_code:
                                    os.makedirs(os.path.dirname(_spec_abs), exist_ok=True)
                                    open(_spec_abs, "w").write(_auto_result.spec_code)
                                _files = [f for f in [_auto_result.pom_path, _auto_result.spec_path] if f]
                                _pushed, _msg = push_to_branch(_repo_path, _auto_feature.strip(), _files)
                                if _pushed:
                                    st.success(f"✅ Pushed to branch `{_msg}`")
                                    st.session_state["auto_result"] = __import__("dataclasses").replace(_auto_result, git_branch=_msg, git_pushed=True)
                                else:
                                    st.error(f"❌ Push failed: {_msg}")
                            except Exception as _push_err:
                                st.error(f"Push error: {_push_err}")

    with tab_run:
        st.subheader("▶️ Run Automation")
        st.caption("Select Playwright spec files and run them directly from the dashboard.")

        # Lazy import to avoid cold-start cost on every Streamlit reload
        from pipeline.test_runner import enumerate_specs, run_release_tests, TestRunResult

        repo_path = getattr(config, "MCSL_AUTOMATION_REPO_PATH", "")
        if not repo_path or not Path(repo_path).exists():
            st.warning(
                "⚠️ MCSL_AUTOMATION_REPO_PATH is not set or does not exist. "
                "Add it to .env:  MCSL_AUTOMATION_REPO_PATH=/path/to/mcsl-test-automation"
            )
        else:
            # Auth state warning
            auth_file = Path(repo_path) / "auth-chrome.json"
            if not auth_file.exists():
                st.warning(
                    "⚠️ `auth-chrome.json` not found. "
                    "Run `npx playwright test tests/setup/login.setup.ts` first to create it."
                )

            # Spec file tree with checkboxes
            spec_groups = enumerate_specs(repo_path)
            if not spec_groups:
                st.info("No .spec.ts files found in the automation repo.")
            else:
                st.markdown("**Select specs to run:**")
                selected: list[str] = []
                for folder, paths in spec_groups.items():
                    with st.expander(f"📁 {folder} ({len(paths)} specs)", expanded=False):
                        for rel_path in paths:
                            key = f"run_chk_{rel_path}"
                            if st.checkbox(Path(rel_path).name, key=key):
                                selected.append(rel_path)

                # Project selector
                project = st.selectbox(
                    "Browser project",
                    ["Google Chrome", "Safari", "Firefox"],
                    key="run_project",
                )

                col_run, col_info = st.columns([1, 3])
                with col_run:
                    run_disabled = st.session_state["run_running"] or len(selected) == 0
                    if st.button("▶ Run Selected", disabled=run_disabled, key="run_btn"):
                        st.session_state["run_running"] = True
                        st.session_state["run_result"] = None
                        st.session_state["run_selected_specs"] = selected

                        def _run_tests_thread(rp=repo_path, specs=selected, proj=project):
                            try:
                                res = run_release_tests(rp, specs, proj)
                                st.session_state["run_result"] = res
                            finally:
                                st.session_state["run_running"] = False

                        threading.Thread(target=_run_tests_thread, daemon=True).start()
                        st.rerun()
                with col_info:
                    if st.session_state["run_running"]:
                        st.info(f"⏳ Running {len(st.session_state['run_selected_specs'])} spec(s)…")
                        st.rerun()
                    elif len(selected) == 0:
                        st.caption("Select at least one spec to enable Run.")

            # Results display
            run_result: TestRunResult | None = st.session_state.get("run_result")
            if run_result is not None:
                if run_result.error:
                    st.error(f"❌ Run error: {run_result.error}")
                else:
                    st.divider()
                    st.markdown("### Results")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("Total", run_result.total)
                    m2.metric("Passed", run_result.passed, delta=None)
                    m3.metric("Failed", run_result.failed, delta=None)
                    m4.metric("Duration", f"{run_result.duration_ms / 1000:.1f}s")

                    for spec in run_result.specs:
                        icon = "✅" if spec.status == "passed" else (
                            "❌" if spec.status == "failed" else (
                            "⏭️" if spec.status == "skipped" else "⏱️"))
                        st.markdown(
                            f"{icon} `{spec.file}` — **{spec.title}** "
                            f"({spec.duration_ms}ms)"
                        )

                    # Post to Slack
                    st.divider()
                    run_name = ", ".join(
                        Path(p).stem for p in st.session_state.get("run_selected_specs", [])
                    )[:80]
                    if st.button("📨 Post Results to Slack", key="run_slack_btn"):
                        from pipeline.slack_client import post_content_to_slack_channel
                        lines = [f"*Automation Run: {run_name}*", ""]
                        lines.append(
                            f"Total: {run_result.total} | "
                            f"Passed: {run_result.passed} | "
                            f"Failed: {run_result.failed} | "
                            f"Skipped: {run_result.skipped}"
                        )
                        lines.append(f"Duration: {run_result.duration_ms / 1000:.1f}s")
                        lines.append("")
                        for s in run_result.specs:
                            ico = "✅" if s.status == "passed" else (
                                "❌" if s.status == "failed" else "⏭️")
                            lines.append(f"{ico} `{s.file}` — {s.title} ({s.duration_ms}ms)")
                        msg = "\n".join(lines)
                        try:
                            resp = post_content_to_slack_channel(
                                getattr(config, "SLACK_CHANNEL", "#qa-pipeline"),
                                msg,
                            )
                            if resp.get("ok"):
                                st.success("✅ Results posted to Slack.")
                            else:
                                st.error(f"Slack error: {resp.get('error', 'unknown')}")
                        except Exception as _slack_err:
                            st.error(f"Slack post failed: {_slack_err}")


if __name__ == "__main__" or True:
    # Allow module import without running main(); Streamlit runs the module directly.
    _init_state()
    main()
