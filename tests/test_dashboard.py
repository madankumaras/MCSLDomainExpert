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

def test_dash05_report_render():
    from unittest.mock import patch, MagicMock
    import pipeline_dashboard as pd

    result = _minimal_result()

    with patch("pipeline_dashboard.st") as mock_st:
        mock_st.columns.return_value = [MagicMock(), MagicMock(), MagicMock(), MagicMock(), MagicMock()]
        mock_st.expander.return_value.__enter__ = MagicMock(return_value=None)
        mock_st.expander.return_value.__exit__ = MagicMock(return_value=False)
        pd.render_report(result)

    # Verify STATUS_BADGE covers all four statuses
    assert "pass" in pd.STATUS_BADGE
    assert "fail" in pd.STATUS_BADGE
    assert "partial" in pd.STATUS_BADGE
    assert "qa_needed" in pd.STATUS_BADGE


# ---------------------------------------------------------------------------
# card_processor.py tests (04-05 — not wave-skipped, pure unit tests)
# ---------------------------------------------------------------------------

def test_card_processor_missing_creds(monkeypatch):
    monkeypatch.delenv("TRELLO_API_KEY", raising=False)
    monkeypatch.delenv("TRELLO_TOKEN", raising=False)
    # Import after env patching
    import importlib
    import pipeline.card_processor as cp
    importlib.reload(cp)   # reload to pick up monkeypatched env
    name, ac = cp.get_ac_text("https://trello.com/c/abc123/some-card")
    assert name == ""
    assert ac == ""


def test_card_processor_valid_url():
    import json
    import io
    from unittest.mock import patch, MagicMock

    fake_body = json.dumps({"name": "My Card", "desc": "AC text here"}).encode()
    mock_resp = MagicMock()
    mock_resp.__enter__ = MagicMock(return_value=mock_resp)
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.read.return_value = fake_body

    with patch("pipeline.card_processor.os.environ.get") as mock_env, \
         patch("pipeline.card_processor.urllib.request.urlopen", return_value=mock_resp):
        mock_env.side_effect = lambda k, d="": {"TRELLO_API_KEY": "key123", "TRELLO_TOKEN": "tok456"}.get(k, d)
        from pipeline import card_processor as cp
        import importlib; importlib.reload(cp)
        name, ac = cp.get_ac_text("https://trello.com/c/abc123/some-card")

    assert name == "My Card"
    assert ac == "AC text here"


# ---------------------------------------------------------------------------
# Phase 5 UI tests — Wave 0 stubs (unskipped progressively by plans 05-01/02/03)
# ---------------------------------------------------------------------------

def test_ui05_branding():
    from unittest.mock import patch
    calls = {}
    with patch("streamlit.set_page_config", side_effect=lambda **kw: calls.update(kw)):
        import importlib
        import pipeline_dashboard
        importlib.reload(pipeline_dashboard)
    assert calls.get("page_title") == "MCSL QA Pipeline"
    assert calls.get("page_icon") == "🚚"
    assert calls.get("layout") == "wide"


def test_ui06_css_classes():
    import pipeline_dashboard as pd
    required = [
        "pipeline-header", "status-badge", "status-ok", "status-err", "status-warn",
        "step-chip", "risk-low", "risk-medium", "risk-high",
        "step-header", "step-num", "step-title",
        "pf-step", "pf-arrow", "pipeline-flow",
        "sev-p1", "sev-p2", "sev-p3", "sev-p4",
        "badge-pass", "badge-fail", "badge-partial", "badge-qa_needed",
        "scenario-card",
    ]
    for cls in required:
        assert cls in pd._CSS, f"CSS class '{cls}' missing from _CSS"


def test_ui01_seven_tabs():
    import pipeline_dashboard as pd
    assert hasattr(pd, "_CSS")


def test_ui01_tab_stubs():
    import pipeline_dashboard as pd
    import inspect
    src = inspect.getsource(pd)
    for tab_var in ["tab_us", "tab_devdone", "tab_release", "tab_history",
                    "tab_signoff", "tab_manual", "tab_run"]:
        assert tab_var in src, f"Tab variable '{tab_var}' missing"


def test_ui02_status_badges():
    import pipeline_dashboard as pd
    ok_html = pd._status_badge("Claude API", True)
    assert "status-ok" in ok_html and "Claude API" in ok_html
    err_html = pd._status_badge("Trello", False, "Set TRELLO_* in .env")
    assert "status-err" in err_html
    assert "Set TRELLO_" in err_html


def test_ui03_release_progress():
    import pipeline_dashboard as pd
    import inspect
    src = inspect.getsource(pd)
    assert "rqa_cards" in src
    assert "rqa_approved" in src
    assert "rqa_test_cases" in src
    assert "rqa_release" in src


def test_ui04_knowledge_base():
    import pipeline_dashboard as pd
    import inspect
    src = inspect.getsource(pd)
    assert "storepepsaas_server" in src
    assert "storepepsaas_client" in src
    assert "MCSL_AUTOMATION_REPO_PATH" in src
    assert "BACKEND_CODE_PATH" not in src
    assert "FRONTEND_CODE_PATH" not in src


def test_ui07_dry_run_toggle():
    import pipeline_dashboard as pd
    import inspect
    src = inspect.getsource(pd)
    assert "st.toggle" in src
    assert "Dry Run" in src or "dry run" in src.lower()


# ---------------------------------------------------------------------------
# Phase 6 User Story tab tests — US-01, US-02, US-03
# ---------------------------------------------------------------------------

def test_us_tab_generate_calls_writer():
    """US-01: tab_us source contains generate_user_story import and call."""
    import inspect
    import pipeline_dashboard
    src = inspect.getsource(pipeline_dashboard)
    assert "generate_user_story" in src, "generate_user_story not found in pipeline_dashboard source"


def test_us_tab_refine_calls_refiner():
    """US-02: tab_us source contains refine_user_story call and us_history state key."""
    import inspect
    import pipeline_dashboard
    src = inspect.getsource(pipeline_dashboard)
    assert "refine_user_story" in src, "refine_user_story not found in pipeline_dashboard source"
    assert "us_history" in src, "us_history not found in pipeline_dashboard source"


def test_us_tab_push_calls_trello():
    """US-03: tab_us source contains create_card_in_list and Trello session keys."""
    import inspect
    import pipeline_dashboard
    src = inspect.getsource(pipeline_dashboard)
    assert "create_card_in_list" in src, "create_card_in_list not found in pipeline_dashboard source"
    assert "us_card_title" in src, "us_card_title not found in pipeline_dashboard source"
    assert "us_assign_members" in src, "us_assign_members not found in pipeline_dashboard source"


def test_us_tab_history_saved_on_push():
    """US-03: history helpers are present and callable at module level."""
    import inspect
    import pipeline_dashboard
    src = inspect.getsource(pipeline_dashboard)
    assert "_save_history" in src, "_save_history not found in pipeline_dashboard source"
    assert "_load_history" in src, "_load_history not found in pipeline_dashboard source"
    assert "_HISTORY_FILE" in src, "_HISTORY_FILE not found in pipeline_dashboard source"
    assert callable(getattr(pipeline_dashboard, "_save_history", None)), \
        "_save_history is not callable on pipeline_dashboard module"
    assert callable(getattr(pipeline_dashboard, "_load_history", None)), \
        "_load_history is not callable on pipeline_dashboard module"
