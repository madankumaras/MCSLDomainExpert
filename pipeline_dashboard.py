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
    """Initialise all sav_* session state keys. Idempotent."""
    defaults: dict[str, Any] = {
        "sav_running": False,
        "sav_stop":    threading.Event(),
        "sav_result":  None,
        "sav_prog":    {"current": 0, "total": 0, "label": ""},
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


# ── Thread launch stub (implemented in 04-02) ──────────────────────────────────

def start_run(
    ac_text: str,
    card_name: str,
    n_scenarios: int = 1,
    headless: bool = True,
    max_scenarios: int = 10,
) -> None:
    """Launch verify_ac() in a background thread. Implemented in plan 04-02."""
    pass  # 04-02 replaces this body


# ── Report render stub (implemented in 04-04) ─────────────────────────────────

def render_report(result: dict) -> None:
    """Render VerificationReport.to_dict() as styled scenario cards. Implemented in 04-04."""
    pass  # 04-04 replaces this body


# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="MCSL Domain Expert",
    page_icon="🚀",
    layout="wide",
    initial_sidebar_state="expanded",
)
st.markdown(_CSS, unsafe_allow_html=True)

_init_state()

# ── Sidebar ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown('<div class="app-header">MCSL</div>', unsafe_allow_html=True)
    st.markdown('<div class="app-subtitle">Domain Expert</div>', unsafe_allow_html=True)
    st.divider()
    st.subheader("Configuration")
    carrier_filter = st.selectbox(
        "Carrier",
        options=["All", "FedEx", "UPS", "USPS", "DHL"],
        index=0,
    )
    headless_mode = st.checkbox("Headless browser", value=True)
    max_scenarios = st.number_input(
        "Max scenarios", min_value=1, max_value=50, value=10, step=1
    )
    st.divider()
    st.caption("Streamlit 1.56 · MCSL QA Agent v1.0")

# ── Header ─────────────────────────────────────────────────────────────────────

st.markdown(
    '<h1 class="app-header">MCSL Domain Expert</h1>'
    '<p class="app-subtitle">AI-powered AC verification pipeline</p>',
    unsafe_allow_html=True,
)
st.divider()

# ── Input area ────────────────────────────────────────────────────────────────

col_input, col_run = st.columns([5, 1])
with col_input:
    trello_url = st.text_input(
        "Trello Card URL",
        placeholder="https://trello.com/c/xxxxxxxx/...",
        help="Paste the Trello card URL — the dashboard will fetch the AC text automatically.",
    )
with col_run:
    st.write("")   # vertical alignment spacer
    run_clicked = st.button("Run", type="primary", use_container_width=True)

manual_ac = st.text_area(
    "Or paste AC text directly",
    height=120,
    placeholder="Acceptance criteria text…",
    help="If Trello credentials are not configured, paste the AC text here.",
)
