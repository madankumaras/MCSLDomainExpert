"""MCSL Domain Expert — Pipeline Dashboard.

Entry point: streamlit run pipeline_dashboard.py
"""
from __future__ import annotations

import threading
import time
from typing import Any

import streamlit as st

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
    }
    for key, val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = val


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


if __name__ == "__main__" or True:
    # Allow module import without running main(); Streamlit runs the module directly.
    _init_state()
