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

# ── Run button handler ─────────────────────────────────────────────────────────

if run_clicked and not st.session_state.sav_running:
    from pipeline.card_processor import get_ac_text  # lazy import

    card_name = ""
    ac_input  = manual_ac.strip()

    if trello_url.strip():
        with st.spinner("Fetching AC from Trello…"):
            fetched_name, fetched_ac = get_ac_text(trello_url.strip())
        if fetched_ac:
            ac_input  = fetched_ac
            card_name = fetched_name
        else:
            st.warning(
                "Could not fetch AC from Trello (check TRELLO_API_KEY / TRELLO_TOKEN). "
                "Paste AC text manually below."
            )

    if not ac_input:
        st.warning("Enter a Trello card URL or paste AC text to run.")
    else:
        if not card_name:
            card_name = trello_url.strip() or "Manual AC"
        start_run(
            ac_text=ac_input,
            card_name=card_name,
            n_scenarios=int(max_scenarios),
            headless=headless_mode,
            max_scenarios=int(max_scenarios),
        )
        st.rerun()

# ── Running state: progress bar + stop button ─────────────────────────────────

if st.session_state.sav_running:
    prog    = st.session_state.sav_prog
    current = prog.get("current", 0)
    total   = max(prog.get("total", 1), 1)   # guard: never divide by zero

    st.progress(
        current / total,
        text=prog.get("label", "Running…"),
    )

    # on_click callback guarantees the event is set BEFORE the next rerun fires
    st.button(
        "Stop",
        key="stop_btn",
        on_click=lambda: st.session_state.sav_stop.set(),
        type="secondary",
    )

    st.info(f"Verifying scenario {current} of {total}…")
    time.sleep(0.5)
    st.rerun()   # poll every 500 ms — triggers next script execution

elif (
    not st.session_state.sav_running
    and st.session_state.sav_stop.is_set()
    and st.session_state.sav_result is not None
):
    st.warning("Run stopped by user. Partial results shown below.")

# ── Completed state: render report ────────────────────────────────────────────

if not st.session_state.sav_running and st.session_state.sav_result is not None:
    render_report(st.session_state.sav_result)
elif not st.session_state.sav_running and st.session_state.sav_result is None:
    st.info("Enter a Trello card URL or paste AC text above and click **Run** to start verification.")
