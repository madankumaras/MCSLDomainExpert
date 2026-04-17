"""MCSL Domain Expert — Pipeline Dashboard.

Entry point: streamlit run pipeline_dashboard.py
"""
from __future__ import annotations

import threading
import time
from typing import Any

import json
from pathlib import Path

# Load .env before any st.* calls so env vars are available on first render
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=True)

import streamlit as st

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
    if "code_paths_initialized" not in st.session_state:
        if config.MCSL_AUTOMATION_REPO_PATH:
            st.session_state["automation_code_path"] = config.MCSL_AUTOMATION_REPO_PATH
        if config.STOREPEPSAAS_SERVER_PATH:
            st.session_state["be_repo_path"] = config.STOREPEPSAAS_SERVER_PATH
        if config.STOREPEPSAAS_CLIENT_PATH:
            st.session_state["fe_repo_path"] = config.STOREPEPSAAS_CLIENT_PATH
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
        st.subheader("Code Knowledge Base")

        # Automation Code
        with st.expander("🧪 Automation Code"):
            auto_path = st.text_input(
                "Repo path", key="automation_code_path",
                value=st.session_state.get("automation_code_path", ""),
                placeholder="/path/to/mcsl-test-automation",
            )
            auto_branch_options = []
            if auto_path:
                try:
                    from rag.code_indexer import get_repo_info
                    info = get_repo_info(auto_path)
                    auto_branch_options = info.get("branches", [])
                except Exception:  # noqa: BLE001
                    pass
            if auto_branch_options:
                st.selectbox("Branch", auto_branch_options, key="auto_branch_select")
            col_sync, col_idx = st.columns(2)
            with col_sync:
                if st.button("Pull & Sync", key="auto_sync_btn"):
                    from rag.code_indexer import sync_from_git
                    branch = st.session_state.get("auto_branch_select", "main")
                    with st.spinner("Syncing…"):
                        sync_from_git(auto_path, "automation", branch)
                    st.success("Synced.")
            with col_idx:
                if st.button("Full Re-index", key="auto_reindex_btn"):
                    from rag.code_indexer import index_codebase
                    with st.spinner("Re-indexing…"):
                        index_codebase(auto_path, "automation", clear_existing=True)
                    st.success("Re-indexed.")

        # Backend / Server Code
        with st.expander("🖥️ Backend/Server Code"):
            be_path = st.text_input(
                "Repo path", key="be_repo_path",
                value=st.session_state.get("be_repo_path", ""),
                placeholder="/path/to/storepepsaas/server",
            )
            be_branch_options = []
            if be_path:
                try:
                    from rag.code_indexer import get_repo_info
                    info = get_repo_info(be_path)
                    be_branch_options = info.get("branches", [])
                except Exception:  # noqa: BLE001
                    pass
            if be_branch_options:
                st.selectbox("Branch", be_branch_options, key="be_branch_select")
            col_sync, col_idx = st.columns(2)
            with col_sync:
                if st.button("Pull & Sync", key="be_sync_btn"):
                    from rag.code_indexer import sync_from_git
                    branch = st.session_state.get("be_branch_select", "main")
                    with st.spinner("Syncing…"):
                        sync_from_git(be_path, "storepepsaas_server", branch)
                    st.success("Synced.")
            with col_idx:
                if st.button("Full Re-index", key="be_reindex_btn"):
                    from rag.code_indexer import index_codebase
                    with st.spinner("Re-indexing…"):
                        index_codebase(be_path, "storepepsaas_server", clear_existing=True)
                    st.success("Re-indexed.")

        # Frontend / Client Code
        with st.expander("🌐 Frontend/Client Code"):
            fe_path = st.text_input(
                "Repo path", key="fe_repo_path",
                value=st.session_state.get("fe_repo_path", ""),
                placeholder="/path/to/storepepsaas/client",
            )
            fe_branch_options = []
            if fe_path:
                try:
                    from rag.code_indexer import get_repo_info
                    info = get_repo_info(fe_path)
                    fe_branch_options = info.get("branches", [])
                except Exception:  # noqa: BLE001
                    pass
            if fe_branch_options:
                st.selectbox("Branch", fe_branch_options, key="fe_branch_select")
            col_sync, col_idx = st.columns(2)
            with col_sync:
                if st.button("Pull & Sync", key="fe_sync_btn"):
                    from rag.code_indexer import sync_from_git
                    branch = st.session_state.get("fe_branch_select", "main")
                    with st.spinner("Syncing…"):
                        sync_from_git(fe_path, "storepepsaas_client", branch)
                    st.success("Synced.")
            with col_idx:
                if st.button("Full Re-index", key="fe_reindex_btn"):
                    from rag.code_indexer import index_codebase
                    with st.spinner("Re-indexing…"):
                        index_codebase(fe_path, "storepepsaas_client", clear_existing=True)
                    st.success("Re-indexed.")

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
        st.info("Release QA pipeline coming in Phase 7.")

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
        st.info("Sign Off tab coming in Phase 8.")

    with tab_manual:
        st.info("Write Automation coming in Phase 9.")

    with tab_run:
        st.info("Run Automation coming in Phase 10.")


if __name__ == "__main__" or True:
    # Allow module import without running main(); Streamlit runs the module directly.
    _init_state()
    main()
