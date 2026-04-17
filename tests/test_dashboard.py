import pytest
import threading
import types


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_ss():
    """Minimal session_state stand-in."""
    ss = types.SimpleNamespace()
    ss.sav_running = False
    ss.sav_stop = threading.Event()
    ss.sav_result = None
    ss.sav_prog = {"current": 0, "total": 0, "label": ""}
    return ss


def _minimal_result():
    return {
        "card_name": "Test Card",
        "total": 4,
        "summary": {"pass": 1, "fail": 1, "partial": 1, "qa_needed": 1},
        "duration_seconds": 12.3,
        "scenarios": [
            {"scenario": "S1", "carrier": "FedEx", "status": "pass",
             "finding": "Scenario passed", "evidence_screenshot": "", "steps_taken": 3},
            {"scenario": "S2", "carrier": "UPS", "status": "fail",
             "finding": "Badge not found", "evidence_screenshot": "", "steps_taken": 5},
            {"scenario": "S3", "carrier": "USPS", "status": "partial",
             "finding": "Label created but doc missing", "evidence_screenshot": "", "steps_taken": 4},
            {"scenario": "S4", "carrier": "DHL", "status": "qa_needed",
             "finding": "Unclear state", "evidence_screenshot": "", "steps_taken": 2},
        ],
    }


# ---------------------------------------------------------------------------
# DASH-01: Scaffold
# ---------------------------------------------------------------------------

def test_dash01_scaffold():
    import pipeline_dashboard as pd
    assert callable(pd._init_state)
    assert callable(pd.start_run)
    assert callable(pd.render_report)


# ---------------------------------------------------------------------------
# DASH-02: Threading
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="wave:04-02")
def test_dash02_threading():
    from unittest.mock import patch, MagicMock
    import pipeline_dashboard as pd

    ss = make_ss()
    mock_thread = MagicMock()
    mock_thread_class = MagicMock(return_value=mock_thread)

    with patch("pipeline_dashboard.st") as mock_st, \
         patch("pipeline_dashboard.threading.Thread", mock_thread_class):
        mock_st.session_state = ss
        pd.start_run("ac text", "Card Name", n_scenarios=2)

    assert ss.sav_running is True
    assert ss.sav_prog["total"] == 2
    mock_thread.start.assert_called_once()


# ---------------------------------------------------------------------------
# DASH-03: Progress callback
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="wave:04-03")
def test_dash03_progress():
    from unittest.mock import patch
    import pipeline_dashboard as pd

    ss = make_ss()
    ss.sav_prog = {"current": 0, "total": 3, "label": ""}

    with patch("pipeline_dashboard.st") as mock_st:
        mock_st.session_state = ss
        pd._progress_cb(1, "scenario title", 2, "clicking button")

    assert ss.sav_prog["current"] == 1
    assert "scenario" in ss.sav_prog["label"]


# ---------------------------------------------------------------------------
# DASH-04: Stop button
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="wave:04-04")
def test_dash04_stop_button():
    import pipeline_dashboard as pd

    ss = make_ss()
    assert not ss.sav_stop.is_set()

    # Simulate stop button on_click callback
    stop_cb = pd._make_stop_callback(ss)
    stop_cb()

    assert ss.sav_stop.is_set()


# ---------------------------------------------------------------------------
# DASH-05: Report render
# ---------------------------------------------------------------------------

@pytest.mark.skip(reason="wave:04-05")
def test_dash05_report_render():
    from unittest.mock import patch, MagicMock
    import pipeline_dashboard as pd

    result = _minimal_result()

    with patch("pipeline_dashboard.st") as mock_st:
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
        mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
        pd.render_report(result)

    # Verify STATUS_BADGE covers all four statuses
    assert "pass" in pd.STATUS_BADGE
    assert "fail" in pd.STATUS_BADGE
    assert "partial" in pd.STATUS_BADGE
    assert "qa_needed" in pd.STATUS_BADGE
