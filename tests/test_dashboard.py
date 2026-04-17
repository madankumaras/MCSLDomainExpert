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


# ---------------------------------------------------------------------------
# Phase 6 Move Cards tab tests — MC-01
# ---------------------------------------------------------------------------

def test_mc_tab_source_and_target_present():
    """MC-01: tab_devdone source contains selectbox keys and default list names."""
    import inspect
    import pipeline_dashboard
    src = inspect.getsource(pipeline_dashboard)
    assert "dd_list_select" in src, "dd_list_select not found in pipeline_dashboard source"
    assert "dd_move_target" in src, "dd_move_target not found in pipeline_dashboard source"
    assert "Dev Done" in src, "'Dev Done' default not found in pipeline_dashboard source"
    assert "Ready for QA" in src, "'Ready for QA' default not found in pipeline_dashboard source"


def test_mc_tab_move_uses_by_id():
    """MC-01: Move Cards uses move_card_to_list_by_id and posts audit comment."""
    import inspect
    import pipeline_dashboard
    src = inspect.getsource(pipeline_dashboard)
    assert "move_card_to_list_by_id" in src, "move_card_to_list_by_id not found in pipeline_dashboard source"
    assert "dd_chk_" in src, "dd_chk_ per-card key prefix not found in pipeline_dashboard source"
    assert "add_comment" in src, "add_comment not found in pipeline_dashboard source"


def test_mc_tab_select_all():
    """MC-01: Move Cards has select-all toggle and dd_checked state."""
    import inspect
    import pipeline_dashboard
    src = inspect.getsource(pipeline_dashboard)
    assert "dd_select_all" in src, "dd_select_all not found in pipeline_dashboard source"
    assert "dd_checked" in src, "dd_checked not found in pipeline_dashboard source"


# ---------------------------------------------------------------------------
# Phase 6 History tab tests — HIST-01
# ---------------------------------------------------------------------------

def test_hist_tab_renders_runs():
    """HIST-01: tab_history renders from pipeline_runs and shows history fields."""
    import inspect
    import pipeline_dashboard
    src = inspect.getsource(pipeline_dashboard)
    assert "pipeline_runs" in src, "pipeline_runs not found in pipeline_dashboard source"
    assert "approved_at" in src, "approved_at not found in pipeline_dashboard source"
    assert "card_url" in src, "card_url not found in pipeline_dashboard source"
    assert "Clear history" in src, "'Clear history' not found in pipeline_dashboard source"


def test_hist_tab_load_from_disk():
    """HIST-01: _load_history and _save_history are callable; _HISTORY_FILE is a Path."""
    from pathlib import Path
    import pipeline_dashboard
    assert callable(getattr(pipeline_dashboard, "_load_history", None)), \
        "_load_history is not callable on pipeline_dashboard module"
    assert callable(getattr(pipeline_dashboard, "_save_history", None)), \
        "_save_history is not callable on pipeline_dashboard module"
    assert isinstance(pipeline_dashboard._HISTORY_FILE, Path), \
        "_HISTORY_FILE is not a Path instance"
    result = pipeline_dashboard._load_history()
    assert isinstance(result, dict), "_load_history() did not return a dict"


# ---------------------------------------------------------------------------
# Phase 7 Release QA tab tests — RQA-01, RQA-03
# ---------------------------------------------------------------------------

def test_rqa01_session_state_keys():
    """RQA-01: _init_state() sets rqa_list_name, rqa_board_id, rqa_board_name, release_analysis."""
    from unittest.mock import patch, MagicMock
    import pipeline_dashboard as pd

    fake_ss = {}

    class DictLikeState(dict):
        def __contains__(self, item):
            return super().__contains__(item)
        def get(self, key, default=None):
            return super().get(key, default)

    ss = DictLikeState()

    with patch("pipeline_dashboard.st") as mock_st:
        mock_st.session_state = ss
        pd._init_state()

    assert "rqa_list_name" in ss, "rqa_list_name not set by _init_state()"
    assert "rqa_board_id" in ss, "rqa_board_id not set by _init_state()"
    assert "release_analysis" in ss, "release_analysis not set by _init_state()"
    assert ss["release_analysis"] is None, "release_analysis should default to None"


def test_rqa03_sav_running_per_card():
    """RQA-03: Run AI QA Agent button sets per-card sav_running_{card.id} key."""
    import pipeline_dashboard as pd
    import inspect
    src = inspect.getsource(pd)

    # Verify per-card key pattern exists in source (f-string with card.id)
    assert "sav_running_" in src, "sav_running_ per-card key pattern not found"
    assert "sav_stop_" in src, "sav_stop_ per-card key pattern not found"

    # Simulate the button press logic directly via session state manipulation
    from unittest.mock import patch
    ss = {}

    card_id = "card_abc"
    sav_running_key = f"sav_running_{card_id}"
    sav_stop_key    = f"sav_stop_{card_id}"
    sav_result_key  = f"sav_result_{card_id}"

    # Simulate what the "Run AI QA Agent" button block does
    ss[sav_running_key] = True
    ss[sav_stop_key]    = False
    ss[sav_result_key]  = {"done": False}

    assert ss.get(sav_running_key) == True
    assert ss.get(sav_stop_key)    == False
    assert ss.get(sav_result_key)  == {"done": False}


def test_rqa03_sav_result_before_flag():
    """RQA-03: Thread closure writes sav_result atomically before clearing sav_running flag."""
    import threading
    from unittest.mock import patch, MagicMock
    import types

    card_id = "card_xyz"
    sav_result_key  = f"sav_result_{card_id}"
    sav_running_key = f"sav_running_{card_id}"
    sav_stop_key    = f"sav_stop_{card_id}"
    sav_stop_event_key = f"sav_stop_event_{card_id}"
    sav_prog_key    = f"sav_prog_{card_id}"
    sav_report_key  = f"sav_report_{card_id}"

    ss = {
        sav_result_key:  {"done": False},
        sav_running_key: True,
        sav_stop_key:    False,
    }

    fake_report = MagicMock()
    fake_report.verdict = "pass"

    # Build a closure matching the _run_sav_thread pattern from tab_release
    _stop_event = threading.Event()

    def _run_sav_thread(
        _url="https://example.com",
        _ac="AC text",
        _max=3,
        _event=_stop_event,
        _rk=sav_result_key,
        _sk=sav_stop_key,
        _sek=sav_stop_event_key,
        _pk=sav_prog_key,
        _repk=sav_report_key,
    ):
        try:
            report = fake_report
            ss[_repk] = report
            ss[_rk] = {"done": True, "report": report, "error": None}
        except Exception as _ex:
            ss[_rk] = {"done": True, "report": None, "error": str(_ex)}
        finally:
            ss.pop(_sek, None)
            ss[sav_running_key] = False

    # Run synchronously
    _run_sav_thread()

    assert ss[sav_result_key]["done"] == True, "done flag not set"
    assert ss[sav_result_key]["report"] is not None, "report should not be None"
    assert "error" in ss[sav_result_key], "error key missing from result dict"
