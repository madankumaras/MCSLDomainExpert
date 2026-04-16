# Phase 4: Pipeline Dashboard - Research

**Researched:** 2026-04-16
**Domain:** Streamlit UI, Python threading, background task orchestration
**Confidence:** HIGH

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| DASH-01 | Streamlit dashboard orchestrates Trello card → AC writing → AI QA Agent → test generation → sign-off | card_processor.py (does not yet exist — must be created in 04-05); verify_ac() is the agent entry point |
| DASH-02 | AI QA Agent runs in background threading.Thread so UI stays responsive during verification | threading.Thread stored in session_state; avoid st.* calls from worker thread; use shared flag + st.rerun() polling loop |
| DASH-03 | Progress bar and live status updates shown during AI QA Agent execution | progress_cb kwarg on verify_ac(); st.progress() + st.empty() updated via sav_prog key in session_state |
| DASH-04 | Stop button functional during AI QA Agent run (stop flag checked per loop iteration) | stop_flag=lambda: st.session_state.sav_stop already wired in _verify_scenario() and verify_ac(); dashboard sets sav_stop=True |
| DASH-05 | Report displayed in dashboard with per-scenario pass/fail/partial/qa_needed | VerificationReport.to_dict() returns structured dict; dashboard renders per-scenario cards with badges |
</phase_requirements>

---

## Summary

Phase 4 wires the completed AI QA Agent (Phase 2/3) into a Streamlit UI. The agent's entry point `verify_ac()` is fully implemented — it accepts `stop_flag`, `progress_cb`, and returns `VerificationReport`. The dashboard's sole job is to launch that function in a background thread, keep the UI reactive, and render the returned report.

The core Streamlit threading pattern is: store `threading.Thread` and a `threading.Event` (or a `bool` flag) in `st.session_state`, launch the thread from the main script execution, poll progress with a tight `time.sleep + st.rerun()` loop in the main thread while the background thread updates shared session_state keys. The background thread MUST NOT call any `st.*` commands — all Streamlit rendering happens in the main thread after the thread writes to session_state keys.

`card_processor.py` does not yet exist. Plan 04-05 must create it. The simplest contract: `get_ac_text(trello_card_url: str) -> tuple[str, str]` returns `(card_name, ac_text)`. For Phase 4 this can be a stub that parses the URL and either uses a Trello API call or prompts the user to paste AC text directly, depending on available Trello credentials.

**Primary recommendation:** Use the shared-flag polling pattern (NOT ScriptRunContext injection) for background threading. Store the stop flag as `threading.Event` in `st.session_state.sav_stop`; set it via `st.session_state.sav_stop.set()` from the stop button callback; pass `stop_flag=lambda: st.session_state.sav_stop.is_set()` to `verify_ac()`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| streamlit | >=1.39.0 (installed: 1.56.0) | Dashboard UI, session state, layout | Already in requirements.txt; installed |
| threading (stdlib) | stdlib | Background thread for verify_ac() | Lighter than multiprocessing; stop_flag pattern works cleanly |
| time (stdlib) | stdlib | Polling sleep in rerun loop | Required by polling pattern |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pipeline.smart_ac_verifier | local | verify_ac() entry point, VerificationReport.to_dict() | Main agent call in background thread |
| base64 (stdlib) | stdlib | Decode evidence_screenshot from VerificationReport for st.image() | Rendering screenshot thumbnails in report |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| threading.Thread + polling | streamlit-server-state | Server-state adds a PyPI dependency and complexity; stdlib threading is sufficient for single-user local tool |
| threading.Event for stop | boolean flag in session_state | threading.Event is thread-safe by design; bool in session_state can have TOCTOU issues under rapid clicking |
| polling loop + st.rerun() | st.fragment with rerun_on | Fragments are newer API (1.37+, confirmed present in 1.56); polling loop is simpler and more predictable for this use case |

**Installation:** No new packages needed — streamlit>=1.39.0 is already in requirements.txt and installed at 1.56.0.

---

## Architecture Patterns

### Recommended Project Structure

```
pipeline_dashboard.py        # Root-level Streamlit app entry point
pipeline/
├── smart_ac_verifier.py     # verify_ac() — already complete
├── card_processor.py        # NEW in 04-05: get_ac_text(url) -> (name, ac_text)
└── order_creator.py         # Already complete
tests/
└── test_dashboard.py        # NEW Wave 0 stubs — one per plan
```

### Pattern 1: Session State Key Initialisation (04-01)

**What:** All `sav_*` keys initialised once at script top before any widget renders.
**When to use:** Every Streamlit app run; Streamlit reruns the entire script on each interaction.

```python
# Source: Streamlit session_state docs — https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state
import streamlit as st
import threading

def _init_state():
    if "sav_running" not in st.session_state:
        st.session_state.sav_running = False
    if "sav_stop" not in st.session_state:
        st.session_state.sav_stop = threading.Event()
    if "sav_result" not in st.session_state:
        st.session_state.sav_result = None   # VerificationReport dict or None
    if "sav_prog" not in st.session_state:
        # {"current": 0, "total": 0, "label": ""}
        st.session_state.sav_prog = {"current": 0, "total": 0, "label": ""}

_init_state()
```

### Pattern 2: Background Thread Launch (04-02)

**What:** Launch `verify_ac()` in a `threading.Thread`, store thread in session_state for daemon management.
**When to use:** User clicks "Run" button while `sav_running` is False.

```python
# Source: Official Streamlit multithreading docs — do NOT call st.* from worker thread
import threading
from pipeline.smart_ac_verifier import verify_ac

def _run_pipeline(ac_text: str, card_name: str):
    """Worker: runs entirely outside Streamlit's script thread. No st.* calls."""
    def _progress(idx: int, scenario: str, step: int, desc: str):
        st.session_state.sav_prog = {
            "current": idx,
            "total": st.session_state.sav_prog.get("total", 0),
            "label": f"[{idx}] {scenario[:50]} — {desc}",
        }

    report = verify_ac(
        ac_text=ac_text,
        card_name=card_name,
        stop_flag=lambda: st.session_state.sav_stop.is_set(),
        progress_cb=_progress,
    )
    st.session_state.sav_result = report.to_dict()
    st.session_state.sav_running = False

def start_pipeline(ac_text: str, card_name: str, total_estimate: int = 1):
    st.session_state.sav_running = True
    st.session_state.sav_stop.clear()
    st.session_state.sav_result = None
    st.session_state.sav_prog = {"current": 0, "total": total_estimate, "label": "Starting…"}
    t = threading.Thread(target=_run_pipeline, args=(ac_text, card_name), daemon=True)
    st.session_state["_sav_thread"] = t
    t.start()
```

**Critical:** `_progress` callback writes to `st.session_state` directly — this works because session_state is a plain dict-like object; the worker thread is writing to a shared Python dict. The main thread reads these values on the next rerun triggered by the polling loop.

### Pattern 3: Polling Loop + Stop Button (04-03)

**What:** Main thread polls `sav_running` and reruns every 500ms while agent is active.
**When to use:** After thread is launched; keeps progress bar and stop button live.

```python
import time

if st.session_state.sav_running:
    prog = st.session_state.sav_prog
    current = prog.get("current", 0)
    total = max(prog.get("total", 1), 1)
    st.progress(current / total, text=prog.get("label", "Running…"))

    if st.button("Stop", key="stop_btn"):
        st.session_state.sav_stop.set()   # signal the worker thread

    time.sleep(0.5)
    st.rerun()   # trigger next poll cycle
```

### Pattern 4: Report Rendering (04-04)

**What:** Render `VerificationReport.to_dict()` result with per-scenario badges.
**When to use:** After `sav_running` is False and `sav_result` is not None.

```python
STATUS_BADGE = {
    "pass":      ":green[PASS]",
    "fail":      ":red[FAIL]",
    "partial":   ":orange[PARTIAL]",
    "qa_needed": ":blue[QA NEEDED]",
}

def render_report(result: dict):
    st.subheader(f"Report: {result['card_name']}")
    summary = result.get("summary", {})
    cols = st.columns(4)
    cols[0].metric("Pass",      summary.get("pass", 0))
    cols[1].metric("Fail",      summary.get("fail", 0))
    cols[2].metric("Partial",   summary.get("partial", 0))
    cols[3].metric("QA Needed", summary.get("qa_needed", 0))

    for sc in result.get("scenarios", []):
        badge = STATUS_BADGE.get(sc["status"], sc["status"].upper())
        with st.expander(f"{badge}  {sc['scenario'][:80]}"):
            st.write(f"**Carrier:** {sc.get('carrier', '—')}")
            st.write(f"**Finding:** {sc.get('finding', '')}")
            st.write(f"**Steps taken:** {sc.get('steps_taken', 0)}")
            scr = sc.get("evidence_screenshot", "")
            if scr:
                import base64, io
                from PIL import Image
                img_bytes = base64.b64decode(scr)
                st.image(Image.open(io.BytesIO(img_bytes)), use_container_width=True)
```

### Pattern 5: card_processor.py Interface (04-05)

**What:** Extracts `(card_name, ac_text)` from a Trello card URL.
**When to use:** When user enters a Trello URL in the dashboard input field.

```python
# pipeline/card_processor.py
def get_ac_text(trello_card_url: str) -> tuple[str, str]:
    """Fetch card name and AC text from a Trello card URL.
    Returns (card_name, ac_text). ac_text may be empty if fetch fails.
    """
    ...
```

The simplest Phase 4 implementation: parse the card short ID from the URL, call Trello REST API (`/1/cards/{id}?fields=name,desc`). Credentials from `.env`: `TRELLO_API_KEY`, `TRELLO_TOKEN`. If credentials absent, fall back to returning `("", "")` so the dashboard can prompt the user to paste AC text manually.

### Anti-Patterns to Avoid

- **Calling st.* from the worker thread:** Raises `NoSessionContext` — all st.write(), st.progress(), st.image() calls must stay in the main script thread.
- **Using `add_script_run_ctx` in production:** Officially unsupported; may break on Streamlit upgrades.
- **Setting `sav_running = False` from the worker thread via st.session_state:** Writing plain booleans to session_state from threads is technically a dict write (works) but can race with the main thread reading it; use a threading.Event for the stop signal specifically.
- **Blocking the main thread with `thread.join()`:** The main thread must remain non-blocking so Streamlit can render the stop button.
- **Using `st.stop()` to halt the pipeline:** `st.stop()` stops Streamlit script execution, not the background thread.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Progress communication | Custom socket/queue to pass progress data | Write to `st.session_state.sav_prog` dict directly from worker | Session_state dict writes are safe from worker threads; no extra primitives needed |
| Stop signal | Custom shared global variable | `threading.Event` stored in `st.session_state.sav_stop` | Event is thread-safe; persists across Streamlit reruns in session |
| Report serialisation | Custom serialiser for VerificationReport | `VerificationReport.to_dict()` already implemented | Phase 2 decision: `to_dict()` was specifically designed for Phase 4 dashboard consumption |
| Screenshot display | Base64 decode + file write | `st.image()` accepts base64 bytes directly via PIL/BytesIO | No disk I/O needed for thumbnail display |
| Status badge styling | Custom CSS | Streamlit coloured text `:green[...]` / `:red[...]` markdown | Built-in, zero dependency |

**Key insight:** The entire agent pipeline (`verify_ac`, `VerificationReport`, `to_dict`) was designed in Phase 2 specifically to be consumable by this dashboard. The Phase 4 work is thin orchestration, not agent logic.

---

## Common Pitfalls

### Pitfall 1: Thread writes sav_running=False before sav_result is populated

**What goes wrong:** Main thread polls `sav_running == False` and tries to render `sav_result` — but `sav_result` is still `None` because the thread set the flag before assigning the dict.

**Why it happens:** Race between the thread's last two assignments.

**How to avoid:** In the worker function, always assign `sav_result` FIRST, then set `sav_running = False`. The main thread checks `sav_running` as the gate; by the time it's False, `sav_result` is already set.

**Warning signs:** `NoneType has no attribute 'get'` error in the report rendering block.

### Pitfall 2: Stop button click lost due to rerun timing

**What goes wrong:** User clicks Stop; Streamlit reruns immediately; `sav_stop` is not yet set before the next rerun clears the button state.

**Why it happens:** `st.button()` returns True only for one script execution. If the rerun loop fires before the button press is processed, the stop signal is missed.

**How to avoid:** Use `on_click` callback to set the event: `st.button("Stop", on_click=lambda: st.session_state.sav_stop.set())`. Callbacks execute before the rerun, guaranteeing the event is set.

### Pitfall 3: Progress bar division by zero

**What goes wrong:** `st.progress(current / total)` raises `ZeroDivisionError` when `total == 0` (before scenario count is known).

**How to avoid:** Always `total = max(prog.get("total", 1), 1)` before dividing.

### Pitfall 4: Thread outlives the Streamlit session

**What goes wrong:** User navigates away or closes tab; the verify_ac() browser loop continues running in the background, consuming Playwright/Chromium resources.

**Why it happens:** `threading.Thread` with `daemon=True` should die when the main process exits, but for long-running sessions it keeps running.

**How to avoid:** Set `daemon=True` on the thread. Additionally, always pass `stop_flag` — so the user can always signal termination before navigating away.

### Pitfall 5: Streamlit re-initialises session state after server restart

**What goes wrong:** Mid-run server restart (e.g., code save triggers hot-reload) clears `st.session_state`, orphaning the background thread.

**How to avoid:** This is a known Streamlit dev limitation. Not solvable without external state. For Phase 4, accept this and document that the user must re-run if the dashboard hot-reloads during a run.

### Pitfall 6: `st.image()` with raw base64 string (not bytes)

**What goes wrong:** `st.image()` requires bytes or a PIL Image, not a base64 string. Passing `evidence_screenshot` directly raises an error.

**How to avoid:** Always decode: `st.image(base64.b64decode(scr))` or wrap via `io.BytesIO`.

---

## Code Examples

### Verified Pattern: Full session_state init + thread launch + polling

```python
# Source: Streamlit docs + project pattern — verified against 1.56.0 installed
import streamlit as st
import threading
import time

# ── 1. Init ────────────────────────────────────────────────────────────────────
def _init_state():
    defaults = {
        "sav_running": False,
        "sav_stop":    threading.Event(),
        "sav_result":  None,
        "sav_prog":    {"current": 0, "total": 0, "label": ""},
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_state()

# ── 2. Worker (no st.* calls) ──────────────────────────────────────────────────
def _worker(ac_text, card_name):
    from pipeline.smart_ac_verifier import verify_ac
    def _prog(idx, scenario, step, desc):
        st.session_state.sav_prog = {"current": idx, "total": st.session_state.sav_prog["total"], "label": f"{scenario[:40]} — {desc}"}
    report = verify_ac(
        ac_text=ac_text,
        card_name=card_name,
        stop_flag=lambda: st.session_state.sav_stop.is_set(),
        progress_cb=_prog,
    )
    st.session_state.sav_result = report.to_dict()   # set result FIRST
    st.session_state.sav_running = False              # then clear flag

# ── 3. Launch ──────────────────────────────────────────────────────────────────
def start_run(ac_text, card_name, n_scenarios):
    st.session_state.sav_running = True
    st.session_state.sav_stop.clear()
    st.session_state.sav_result = None
    st.session_state.sav_prog = {"current": 0, "total": n_scenarios, "label": "Starting…"}
    t = threading.Thread(target=_worker, args=(ac_text, card_name), daemon=True)
    t.start()

# ── 4. Polling UI ──────────────────────────────────────────────────────────────
if st.session_state.sav_running:
    prog = st.session_state.sav_prog
    st.progress(prog["current"] / max(prog["total"], 1), text=prog["label"])
    st.button("Stop", on_click=lambda: st.session_state.sav_stop.set())
    time.sleep(0.5)
    st.rerun()
```

### Verified Pattern: verify_ac() signature (from smart_ac_verifier.py)

```python
# Source: pipeline/smart_ac_verifier.py — confirmed by direct code read
def verify_ac(
    ac_text: str,
    card_name: str = "",
    stop_flag: "Callable[[], bool] | None" = None,
    headless: bool = False,
    app_url: str = "",
    progress_cb: "Callable[[int, str, int, str], None] | None" = None,
    qa_answers: "dict[str, str] | None" = None,
    max_scenarios: "int | None" = None,
) -> VerificationReport:
    ...
```

`progress_cb` signature: `(scenario_idx: int, scenario_title: str, step_num: int, step_desc: str) -> None`

### Verified Pattern: VerificationReport.to_dict() output schema

```python
# Source: pipeline/smart_ac_verifier.py VerificationReport.to_dict() — confirmed by direct code read
{
    "card_name": str,
    "total": int,
    "summary": {"pass": int, "fail": int, "partial": int, "qa_needed": int},
    "duration_seconds": float,
    "scenarios": [
        {
            "scenario": str,
            "carrier": str,
            "status": str,        # "pass" | "fail" | "partial" | "qa_needed"
            "finding": str,       # human-readable verdict; defaults to "Scenario passed" for pass
            "evidence_screenshot": str,  # base64 PNG or ""
            "steps_taken": int,
        },
        ...
    ],
}
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `st.experimental_rerun()` | `st.rerun()` | Streamlit 1.27 | Use `st.rerun()` — experimental variant raises deprecation warning |
| `SessionState` hack (custom class) | `st.session_state` (built-in) | Streamlit 0.84 | Use `st.session_state` directly |
| `st.beta_columns()` | `st.columns()` | Streamlit 0.84 | Use `st.columns()` |
| `st.image(base64_str)` | `st.image(bytes_or_PIL)` | Long-standing | Must decode base64 before passing to st.image |

**Deprecated/outdated:**
- `st.experimental_*` family: All replaced by stable equivalents in 1.27+. None needed for Phase 4.
- `streamlit-server-state` PyPI package: Was needed before session_state existed; not needed.

---

## Open Questions

1. **Does card_processor.py need real Trello API credentials?**
   - What we know: No `TRELLO_API_KEY` or `TRELLO_TOKEN` in requirements or .env template
   - What's unclear: Whether Trello credentials are available in the project's `.env`
   - Recommendation: Plan 04-05 should implement `get_ac_text()` with a try/fallback — attempt Trello API fetch, fall back to returning `("", "")` so the UI can offer a manual paste textarea. This avoids blocking the dashboard on credential availability.

2. **How many scenarios does a typical Trello card contain?**
   - What we know: `verify_ac()` has `max_scenarios` cap; default is no cap
   - What's unclear: Expected AC size — affects progress bar denominator accuracy
   - Recommendation: Set `max_scenarios=10` as a safe default in the dashboard run; expose as an advanced setting.

3. **Should `pipeline_dashboard.py` live at repo root or inside `pipeline/`?**
   - What we know: No existing dashboard file anywhere in the repo; other Streamlit apps (chat_app.py) live at repo root per roadmap references
   - Recommendation: Root level (`pipeline_dashboard.py`) — consistent with the project pattern and easier to `streamlit run pipeline_dashboard.py`.

---

## Validation Architecture

`workflow.nyquist_validation` is `true` in `.planning/config.json` — this section is required.

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.3.3 |
| Config file | none — pytest auto-discovers `tests/` |
| Quick run command | `/Users/madan/Documents/MCSLDomainExpert/.venv/bin/pytest tests/test_dashboard.py -x -q` |
| Full suite command | `/Users/madan/Documents/MCSLDomainExpert/.venv/bin/pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DASH-01 | `pipeline_dashboard.py` imports without error and defines `_init_state()`, `start_run()`, `render_report()` | unit (import + attribute check) | `pytest tests/test_dashboard.py::test_dash01_scaffold -x` | Wave 0 |
| DASH-02 | `start_run()` launches a `threading.Thread`, sets `sav_running=True`, stops on stop signal | unit (mock session_state + thread) | `pytest tests/test_dashboard.py::test_dash02_threading -x` | Wave 0 |
| DASH-03 | `_progress_cb` updates `sav_prog` dict correctly; progress fraction in [0,1] | unit | `pytest tests/test_dashboard.py::test_dash03_progress -x` | Wave 0 |
| DASH-04 | Stop button sets `sav_stop` event; worker thread detects `stop_flag()=True` and exits | unit (mock verify_ac) | `pytest tests/test_dashboard.py::test_dash04_stop_button -x` | Wave 0 |
| DASH-05 | `render_report()` builds correct badge text for all 4 statuses; handles empty screenshots | unit | `pytest tests/test_dashboard.py::test_dash05_report_render -x` | Wave 0 |

### Mocking Strategy for Streamlit Tests

Streamlit widgets (`st.write`, `st.progress`, `st.button`, `st.image`) cannot run outside a browser context. Tests mock the `st` module using `unittest.mock.patch` or `MagicMock`. The established project pattern (see `tests/test_agent.py`) uses:

```python
from unittest.mock import MagicMock, patch

# Pattern used across all Phase 2/3 tests:
with patch("pipeline_dashboard.verify_ac", return_value=mock_report):
    ...
```

For session_state: create a plain `dict`-like object as a stand-in:

```python
import types

def make_session_state():
    ss = types.SimpleNamespace()
    ss.sav_running = False
    ss.sav_stop = threading.Event()
    ss.sav_result = None
    ss.sav_prog = {"current": 0, "total": 0, "label": ""}
    return ss
```

Then `patch("pipeline_dashboard.st.session_state", new=make_session_state())`.

### Sampling Rate

- **Per task commit:** `/Users/madan/Documents/MCSLDomainExpert/.venv/bin/pytest tests/test_dashboard.py -x -q`
- **Per wave merge:** `/Users/madan/Documents/MCSLDomainExpert/.venv/bin/pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_dashboard.py` — new file; covers DASH-01 through DASH-05 (Wave 0 stubs, activated per plan)
- [ ] `pipeline/card_processor.py` — new module; created in plan 04-05
- [ ] `pipeline_dashboard.py` — new file; created in plan 04-01

*(conftest.py and pytest infrastructure already exist — no new framework install needed)*

---

## Sources

### Primary (HIGH confidence)

- `pipeline/smart_ac_verifier.py` (direct code read) — `verify_ac()` signature, `progress_cb` contract, `stop_flag` wiring, `VerificationReport.to_dict()` schema
- `requirements.txt` (direct read) — streamlit>=1.39.0 confirmed; installed version 1.56.0 verified via venv python
- [Streamlit Multithreading Docs](https://docs.streamlit.io/develop/concepts/design/multithreading) — official pattern for background threads, ScriptRunContext, safe/unsafe patterns
- [Streamlit Session State Docs](https://docs.streamlit.io/develop/api-reference/caching-and-state/st.session_state) — session_state init patterns, callbacks

### Secondary (MEDIUM confidence)

- [Streamlit Community — Stop/Cancel Button](https://discuss.streamlit.io/t/stop-or-cancel-button/1543) — threading.Event pattern for stop button, validated against official docs
- [Streamlit Community — Changing session state from thread](https://discuss.streamlit.io/t/changing-session-state-not-reflecting-in-active-python-thread/37683) — confirms direct dict writes to session_state from worker threads are safe at Python level

### Tertiary (LOW confidence)

- WebSearch community patterns for `st.rerun()` polling loop — consistent with official architecture model but not directly verified in official changelog

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — streamlit installed and confirmed, stdlib threading
- Architecture: HIGH — verify_ac() and VerificationReport interfaces confirmed by direct code read; threading pattern from official docs
- Pitfalls: MEDIUM — stop button race condition and result-before-flag ordering are common patterns documented in community discussions; confirmed plausible from architecture understanding

**Research date:** 2026-04-16
**Valid until:** 2026-05-16 (Streamlit APIs are stable; threading stdlib is immutable)
