"""
Wave 0 stubs — AI QA Agent Core (Phase 02)
==========================================
All tests start skipped. Each stub is activated in the plan that implements the
corresponding feature. Skip reason format: "Wave 0 stub — <REQ-ID>".
"""
import pytest


@pytest.mark.skip(reason="Wave 0 stub — AGENT-01")
def test_extract_scenarios():
    """AGENT-01: Agent extracts testable scenarios from AC text as JSON array."""
    try:
        from pipeline.smart_ac_verifier import _extract_scenarios
    except ImportError:
        pytest.skip("pipeline.smart_ac_verifier not yet implemented")
    from unittest.mock import MagicMock

    mock_claude = MagicMock()
    mock_claude.invoke.return_value.content = '["Scenario A", "Scenario B"]'
    result = _extract_scenarios("Given a UPS account is configured, when a label is generated, then the label status shows label generated.", claude=mock_claude)
    assert isinstance(result, list)
    assert len(result) > 0


@pytest.mark.skip(reason="Wave 0 stub — AGENT-02")
def test_domain_expert_query():
    """AGENT-02: Agent queries Domain Expert RAG for expected behaviour per scenario."""
    try:
        from pipeline.smart_ac_verifier import _ask_domain_expert
    except ImportError:
        pytest.skip("pipeline.smart_ac_verifier not yet implemented")
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


@pytest.mark.skip(reason="Wave 0 stub — AGENT-03")
def test_build_execution_plan():
    """AGENT-03: Agent generates JSON execution plan with nav_clicks, look_for, api_to_watch, order_action, carrier."""
    try:
        from pipeline.smart_ac_verifier import _plan_scenario
    except ImportError:
        pytest.skip("pipeline.smart_ac_verifier not yet implemented")
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


@pytest.mark.skip(reason="Wave 0 stub — AGENT-04")
def test_browser_loop_scaffold():
    """AGENT-04: Agent runs agentic browser loop up to MAX_STEPS."""
    try:
        from pipeline.smart_ac_verifier import _verify_scenario
    except ImportError:
        pytest.skip("pipeline.smart_ac_verifier not yet implemented")
    # stub — no browser launched in unit tests
    assert True


@pytest.mark.skip(reason="Wave 0 stub — AGENT-05")
def test_ax_tree_capture():
    """AGENT-05: Agent captures AX tree (depth 6, 250 lines) + screenshot + network calls per step."""
    try:
        from pipeline.smart_ac_verifier import _ax_tree
    except ImportError:
        pytest.skip("pipeline.smart_ac_verifier not yet implemented")
    # stub — no browser launched in unit tests
    assert True


@pytest.mark.skip(reason="Wave 0 stub — AGENT-06")
def test_action_handlers():
    """AGENT-06: Agent performs browser actions: click, fill, navigate, download_zip, etc."""
    try:
        from pipeline.smart_ac_verifier import _do_action
    except ImportError:
        pytest.skip("pipeline.smart_ac_verifier not yet implemented")
    # stub — no browser launched in unit tests
    assert True


@pytest.mark.skip(reason="Wave 0 stub — CARRIER-01")
def test_carrier_detection():
    """CARRIER-01: Carrier name detected from AC text is injected into planning prompt."""
    try:
        from pipeline.smart_ac_verifier import _detect_carrier
    except ImportError:
        pytest.skip("pipeline.smart_ac_verifier not yet implemented")
    assert _detect_carrier("FedEx account configured") == ("FedEx", "C2")
    assert _detect_carrier("UPS label generated") == ("UPS", "C3")
    assert _detect_carrier("unknown carrier") == ("", "")


@pytest.mark.skip(reason="Wave 0 stub — AGENT-01")
def test_order_creator():
    """AGENT-01 (order): create_order creates a Shopify REST order and returns order id."""
    try:
        from pipeline.order_creator import create_order
    except ImportError:
        pytest.skip("pipeline.order_creator not yet implemented")
    # stub — no live Shopify call in unit tests
    assert True


@pytest.mark.skip(reason="Wave 0 stub — AGENT-06")
def test_verdict_reporting():
    """AGENT-06: VerificationReport and ScenarioResult dataclasses are importable and correct."""
    try:
        from pipeline.smart_ac_verifier import VerificationReport, ScenarioResult
    except ImportError:
        pytest.skip("pipeline.smart_ac_verifier not yet implemented")
    report = VerificationReport(card_name="Test Card", app_url="https://example.com")
    assert report.passed == 0
    assert report.failed == 0
    scenario = ScenarioResult(scenario="Test scenario")
    assert scenario.status == "pending"
    assert hasattr(scenario, "carrier")
