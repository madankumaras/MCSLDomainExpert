"""
Wave 0 stubs — AI QA Agent Core (Phase 02)
==========================================
All tests start skipped. Each stub is activated in the plan that implements the
corresponding feature. Skip reason format: "Wave 0 stub — <REQ-ID>".
"""
import pytest


def test_extract_scenarios():
    """AGENT-01: Agent extracts testable scenarios from AC text as JSON array."""
    from pipeline.smart_ac_verifier import _extract_scenarios
    from unittest.mock import MagicMock

    mock_claude = MagicMock()
    mock_claude.invoke.return_value.content = '["Scenario A", "Scenario B"]'
    result = _extract_scenarios(
        "Given a UPS account is configured, when a label is generated, then the label status shows label generated.",
        claude=mock_claude,
    )
    assert isinstance(result, list)
    assert len(result) > 0


def test_domain_expert_query():
    """AGENT-02: Agent queries Domain Expert RAG for expected behaviour per scenario."""
    from pipeline.smart_ac_verifier import _ask_domain_expert
    from unittest.mock import MagicMock

    mock_claude = MagicMock()
    mock_claude.invoke.return_value.content = "The UPS label flow navigates to Order Summary."
    result = _ask_domain_expert(
        scenario="UPS label is generated successfully",
        card_name="UPS Label Generation",
        claude=mock_claude,
    )
    assert isinstance(result, str)
    assert len(result) > 0


def test_build_execution_plan():
    """AGENT-03: Agent generates JSON execution plan with nav_clicks, look_for, api_to_watch, order_action, carrier."""
    from pipeline.smart_ac_verifier import _plan_scenario
    from unittest.mock import MagicMock

    mock_claude = MagicMock()
    mock_claude.invoke.return_value.content = """{
        "nav_clicks": ["Shipping"],
        "look_for": ["label generated"],
        "api_to_watch": ["/api/orders"],
        "order_action": "existing_fulfilled",
        "carrier": "FedEx",
        "plan": "Navigate to Shipping and verify label status"
    }"""
    result = _plan_scenario(
        scenario="FedEx label is generated successfully",
        app_url="https://admin.shopify.com/store/test-store/apps/mcsl-qa",
        code_ctx="",
        expert_insight="Label status badge should show 'label generated'",
        claude=mock_claude,
    )
    assert isinstance(result, dict)
    assert "nav_clicks" in result
    assert "look_for" in result
    assert "api_to_watch" in result
    assert "order_action" in result
    assert "carrier" in result


def test_browser_loop_scaffold():
    """AGENT-04: _verify_scenario runs agentic loop, respects stop_flag, returns ScenarioResult."""
    from pipeline.smart_ac_verifier import _verify_scenario, ScenarioResult, MAX_STEPS
    from unittest.mock import MagicMock, patch

    # Build a minimal mock page
    mock_page = MagicMock()
    mock_page.url = "https://example.com"
    mock_page.frames = []
    mock_page.main_frame = MagicMock()
    mock_page.accessibility.snapshot.return_value = None
    mock_page.screenshot.return_value = b"fake_png"
    mock_page.evaluate.return_value = []

    plan_data = {"carrier": "FedEx", "api_to_watch": [], "nav_clicks": []}

    # Case 1: _decide_next immediately returns verify → status="pass"
    verify_action = {"action": "verify", "verdict": "pass", "finding": "label found"}
    with patch("pipeline.smart_ac_verifier._decide_next", return_value=verify_action):
        result = _verify_scenario(
            page=mock_page,
            scenario="FedEx label is generated",
            card_name="Label Generation",
            app_base="https://example.com",
            plan_data=plan_data,
        )
    assert isinstance(result, ScenarioResult)
    assert result.status == "pass"
    assert result.finding == "label found"

    # Case 2: stop_flag=True → status="partial", early exit
    with patch("pipeline.smart_ac_verifier._decide_next", return_value=verify_action):
        result_stopped = _verify_scenario(
            page=mock_page,
            scenario="FedEx label is generated",
            card_name="Label Generation",
            app_base="https://example.com",
            plan_data=plan_data,
            stop_flag=lambda: True,
        )
    assert result_stopped.status == "partial"
    assert "Stopped" in result_stopped.finding


def test_ax_tree_capture():
    """AGENT-05: Agent captures AX tree (depth 6, 250 lines) + screenshot + network calls per step."""
    from pipeline.smart_ac_verifier import _ax_tree, _screenshot, _network
    from unittest.mock import MagicMock, PropertyMock

    # -- _ax_tree: mock page with one app iframe --
    mock_frame = MagicMock()
    mock_frame.url = "https://admin.shopify.com/store/test/apps/mcsl-qa/shopify"
    mock_frame.accessibility.snapshot.return_value = {
        "role": "button",
        "name": "Generate Label",
        "children": [],
    }

    mock_page = MagicMock()
    mock_page.accessibility.snapshot.return_value = {
        "role": "button",
        "name": "Main Nav Button",
        "children": [],
    }
    # main_frame is a different object so the identity check works
    mock_page.main_frame = MagicMock()
    mock_page.frames = [mock_page.main_frame, mock_frame]

    result = _ax_tree(mock_page)
    assert isinstance(result, str)
    assert len(result) > 0
    assert "--- [APP IFRAME:" in result, f"Expected APP IFRAME header in ax_tree output, got: {result!r}"

    # -- _screenshot: returns non-empty base64 string --
    mock_page2 = MagicMock()
    mock_page2.screenshot.return_value = b"\x89PNG\r\n\x1a\nfake_png_bytes"
    scr = _screenshot(mock_page2)
    assert isinstance(scr, str)
    assert len(scr) > 0
    import base64
    base64.b64decode(scr)  # must not raise

    # -- _network: returns a string (may be empty when no matches) --
    mock_page3 = MagicMock()
    mock_page3.evaluate.return_value = []
    mock_page3.main_frame = MagicMock()
    mock_page3.frames = [mock_page3.main_frame]
    net = _network(mock_page3, ["/api/orders"])
    assert isinstance(net, str)


def test_action_handlers():
    """AGENT-06: _do_action handles all 11 action types without raising unhandled exceptions."""
    from pipeline.smart_ac_verifier import _do_action, _navigate_in_app
    from unittest.mock import MagicMock, patch

    app_base = "https://admin.shopify.com/store/mcsl-qa-store/apps/mcsl-qa"

    # Build a minimal mock page
    mock_page = MagicMock()
    mock_page.frames = []
    mock_page.context.pages = [mock_page]

    # observe → True (no-op)
    assert _do_action(mock_page, {"action": "observe"}, app_base) is True

    # verify → True
    assert _do_action(mock_page, {"action": "verify", "verdict": "pass", "finding": "ok"}, app_base) is True

    # qa_needed → True
    assert _do_action(mock_page, {"action": "qa_needed", "question": "?"}, app_base) is True

    # navigate with named destination → delegates to _navigate_in_app (click-based, returns bool)
    # "shopifyorders" is the only destination that calls page.goto (leaves the app)
    result_nav = _do_action(mock_page, {"action": "navigate", "url": "shopifyorders"}, app_base)
    assert isinstance(result_nav, bool)
    assert mock_page.goto.called
    call_url = mock_page.goto.call_args[0][0]
    assert "admin.shopify.com" in call_url

    # download_zip → False (Phase 2 stub)
    result_zip = _do_action(mock_page, {"action": "download_zip", "url": "http://example.com/file.zip"}, app_base)
    assert result_zip is False

    # download_file → False (Phase 2 stub)
    result_file = _do_action(mock_page, {"action": "download_file", "url": "http://example.com/label.pdf"}, app_base)
    assert result_file is False

    # scroll → True
    assert _do_action(mock_page, {"action": "scroll", "delta_y": 300}, app_base) is True

    # switch_tab with single page → False (no second tab)
    mock_page.context.pages = [mock_page]
    result_switch = _do_action(mock_page, {"action": "switch_tab"}, app_base)
    assert isinstance(result_switch, bool)

    # close_tab → True (context has pages to fall back to)
    mock_page2 = MagicMock()
    mock_page2.frames = []
    mock_page2.context.pages = [mock_page, mock_page2]
    result_close = _do_action(mock_page2, {"action": "close_tab"}, app_base)
    assert isinstance(result_close, bool)


def test_decide_next_valid_response():
    """_decide_next returns parsed action dict when claude returns valid JSON."""
    from pipeline.smart_ac_verifier import _decide_next
    from unittest.mock import MagicMock

    claude = MagicMock()
    claude.invoke.return_value.content = '{"action": "click", "selector": "Generate Label"}'

    result = _decide_next(
        claude, "scenario text", "https://example.com",
        "ax tree", [], [], "ctx", 1, scr=None, expert_insight=""
    )
    assert result.get("action") == "click"


def test_decide_next_garbage_fallback():
    """_decide_next returns qa_needed fallback when claude returns unparseable garbage."""
    from pipeline.smart_ac_verifier import _decide_next
    from unittest.mock import MagicMock

    claude = MagicMock()
    claude.invoke.return_value.content = "I cannot determine what to do next."

    result = _decide_next(
        claude, "scenario text", "https://example.com",
        "ax tree", [], [], "ctx", 1, scr=None, expert_insight=""
    )
    assert result.get("action") == "qa_needed"


def test_carrier_detection():
    """CARRIER-01: Carrier name detected from AC text is injected into planning prompt."""
    from pipeline.smart_ac_verifier import _detect_carrier

    # Core carriers
    assert _detect_carrier("FedEx account configured") == ("FedEx", "C2")
    assert _detect_carrier("UPS shipment with signature") == ("UPS", "C3")
    assert _detect_carrier("DHL international") == ("DHL", "C1")
    assert _detect_carrier("USPS registered mail") == ("USPS", "C22")
    assert _detect_carrier("stamps.com delivery") == ("USPS Stamps", "C22")
    assert _detect_carrier("easypost api") == ("EasyPost", "C22")
    assert _detect_carrier("canada post package") == ("Canada Post", "C4")
    # Unknown fallback
    assert _detect_carrier("unknown carrier scenario") == ("", "")


def test_plan_scenario_injects_carrier():
    """CARRIER-01: _plan_scenario returns plan dict with carrier field set from AC text."""
    from pipeline.smart_ac_verifier import _plan_scenario
    from unittest.mock import MagicMock

    mock_claude = MagicMock()
    mock_claude.invoke.return_value.content = """{
        "nav_clicks": ["Shipping"],
        "look_for": ["label generated"],
        "api_to_watch": ["/api/orders"],
        "order_action": "create_new",
        "carrier": "FedEx",
        "plan": "Navigate to Shipping and generate dry ice label"
    }"""
    result = _plan_scenario(
        scenario="FedEx dry ice scenario",
        app_url="https://admin.shopify.com/store/test-store/apps/mcsl-qa",
        code_ctx="",
        expert_insight="",
        claude=mock_claude,
    )
    assert isinstance(result, dict)
    assert result.get("carrier") == "FedEx"


def test_order_creator(tmp_path):
    """AGENT-04 (order): create_order creates a Shopify REST order and returns order id."""
    import json
    from unittest.mock import MagicMock, patch

    # Create a temporary carrier-env file
    env_file = tmp_path / "test-carrier.env"
    env_file.write_text(
        'SHOPIFY_STORE_NAME=mcsl-automation\n'
        'SHOPIFY_ACCESS_TOKEN=fake_token\n'
        'SHOPIFY_API_VERSION=2023-01\n'
        'SIMPLE_PRODUCTS_JSON=[{"product_id": 123, "variant_id": 456}]\n',
        encoding="utf-8",
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {"order": {"id": "9999"}}
    mock_response.raise_for_status.return_value = None

    with patch("pipeline.order_creator.requests.post", return_value=mock_response) as mock_post:
        from pipeline.order_creator import create_order, create_bulk_orders, _read_carrier_env

        # Test _read_carrier_env
        env_data = _read_carrier_env(env_file)
        assert env_data.get("SHOPIFY_ACCESS_TOKEN") == "fake_token"
        assert env_data.get("SHOPIFY_STORE_NAME") == "mcsl-automation"
        assert "SIMPLE_PRODUCTS_JSON" in env_data

        # Test create_order returns order ID string
        order_id = create_order(env_file)
        assert order_id == "9999"
        assert mock_post.called
        call_kwargs = mock_post.call_args
        assert "X-Shopify-Access-Token" in call_kwargs[1]["headers"]

        # Test create_bulk_orders returns list of 2 IDs
        mock_post.reset_mock()
        order_ids = create_bulk_orders(env_file, count=2)
        assert isinstance(order_ids, list)
        assert len(order_ids) == 2
        assert all(oid == "9999" for oid in order_ids)


def test_verify_scenario_order_wiring():
    """AGENT-04: _verify_scenario calls create_order when plan_data has order_action='create_new'."""
    from pathlib import Path
    from unittest.mock import MagicMock, patch

    from pipeline.smart_ac_verifier import _verify_scenario, ScenarioResult

    mock_page = MagicMock()
    mock_page.url = "https://example.com"
    mock_page.frames = []
    mock_page.main_frame = MagicMock()
    mock_page.accessibility.snapshot.return_value = None
    mock_page.screenshot.return_value = b"fake_png"
    mock_page.evaluate.return_value = []

    verify_action = {"action": "verify", "verdict": "pass", "finding": "ok"}

    # Patch order_creator imports inside the module
    with patch("pipeline.smart_ac_verifier._decide_next", return_value=verify_action), \
         patch("pipeline.order_creator.requests.post") as mock_post:

        mock_response = MagicMock()
        mock_response.json.return_value = {"order": {"id": "ORD-123"}}
        mock_response.raise_for_status.return_value = None
        mock_post.return_value = mock_response

        # Patch get_carrier_env_for_code to avoid filesystem lookup
        with patch("pipeline.order_creator._get_carrier_env_path") as mock_env_path, \
             patch("pipeline.order_creator._read_carrier_env") as mock_read_env:

            mock_env_path.return_value = Path("/fake/path/ups.env")
            mock_read_env.return_value = {
                "SHOPIFY_STORE_NAME": "mcsl-automation",
                "SHOPIFY_ACCESS_TOKEN": "fake_token",
                "SHOPIFY_API_VERSION": "2023-01",
                "SIMPLE_PRODUCTS_JSON": '[{"product_id": 123, "variant_id": 456}]',
            }

            result = _verify_scenario(
                page=mock_page,
                scenario="FedEx label generation",
                card_name="Label Generation",
                app_base="https://example.com",
                plan_data={
                    "order_action": "create_new",
                    "carrier": "FedEx",
                    "carrier_code": "C2",
                    "api_to_watch": [],
                },
                ctx="",
                claude=MagicMock(),
                stop_flag=None,
            )

    assert isinstance(result, ScenarioResult)
    assert result.status == "pass"


def test_verdict_reporting():
    """AGENT-06: VerificationReport.to_dict() returns correct summary counts and stop_flag halts verify_ac."""
    from pipeline.smart_ac_verifier import VerificationReport, ScenarioResult
    from unittest.mock import patch

    # --- Part 1: to_dict() summary counts ---
    report = VerificationReport(
        card_name="Test Card",
        scenarios=[
            ScenarioResult(scenario="s1", status="pass", finding="ok", carrier="FedEx"),
            ScenarioResult(scenario="s2", status="fail", finding="label not found", carrier="UPS"),
        ],
    )
    d = report.to_dict()
    assert d["summary"] == {"pass": 1, "fail": 1, "partial": 0, "qa_needed": 0}
    assert d["total"] == 2
    assert d["card_name"] == "Test Card"
    assert "scenarios" in d
    assert "duration_seconds" in d

    # --- Part 2: stop_flag=lambda: True halts before first scenario ---
    with patch("pipeline.smart_ac_verifier._extract_scenarios", return_value=["scenario 1"]), \
         patch("pipeline.smart_ac_verifier._launch_browser") as mock_browser, \
         patch("pipeline.smart_ac_verifier._ask_domain_expert", return_value="insight"), \
         patch("pipeline.smart_ac_verifier._code_context", return_value="ctx"), \
         patch("pipeline.smart_ac_verifier._plan_scenario", return_value={}), \
         patch("pipeline.smart_ac_verifier.ChatAnthropic"):
        # mock_browser returns (pw, browser, ctx, page) tuple
        mock_pw = __import__("unittest.mock", fromlist=["MagicMock"]).MagicMock()
        mock_browser.return_value = (mock_pw, mock_pw, mock_pw, mock_pw)

        from pipeline.smart_ac_verifier import verify_ac
        result = verify_ac(
            ac_text="Given a scenario",
            card_name="Test Card",
            stop_flag=lambda: True,
        )
    assert isinstance(result, VerificationReport)
    assert len(result.scenarios) == 0  # stopped before first scenario

    # --- Part 3: ScenarioResult defaults ---
    s = ScenarioResult(scenario="Test scenario")
    assert s.status == "pending"
    assert hasattr(s, "carrier")


def test_full_report_integration():
    """Constructs a VerificationReport with 2 scenarios and asserts to_dict() structure."""
    from pipeline.smart_ac_verifier import VerificationReport, ScenarioResult

    report = VerificationReport(
        card_name="Test Card",
        scenarios=[
            ScenarioResult(
                scenario="When FedEx account is configured, label is generated successfully",
                carrier="FedEx",
                status="pass",
                finding="",
                evidence_screenshot="",
            ),
            ScenarioResult(
                scenario="When UPS account has invalid credentials, error message is shown",
                carrier="UPS",
                status="fail",
                finding="Error modal not found after 15 steps",
                evidence_screenshot="",
            ),
        ],
        duration_seconds=12.5,
    )

    result = report.to_dict()

    # Top-level keys
    assert "card_name" in result
    assert "total" in result
    assert "summary" in result
    assert "duration_seconds" in result
    assert "scenarios" in result

    # Counts
    assert result["total"] == 2
    assert result["summary"]["pass"] == 1
    assert result["summary"]["fail"] == 1
    assert result["summary"]["partial"] == 0
    assert result["summary"]["qa_needed"] == 0
    assert result["duration_seconds"] == 12.5

    # Per-scenario keys
    for s in result["scenarios"]:
        assert "scenario" in s
        assert "status" in s
        assert "finding" in s
        assert "steps_taken" in s
        assert "carrier" in s

    # Pass finding defaults to "Scenario passed" when empty
    pass_scenario = next(s for s in result["scenarios"] if s["status"] == "pass")
    assert pass_scenario["finding"] == "Scenario passed"
