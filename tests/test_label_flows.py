"""
Wave 0 stubs — Label Flows + Docs + Pre-Requirements (Phase 03)
================================================================
test_manual_label_flow_plan is active (LABEL-01).
All other 16 functions are Wave 0 stubs activated in later plans.
Skip reason format: "Wave 0 stub — activated in later plans"
"""
import pytest


def test_manual_label_flow_plan():
    """LABEL-01: _plan_scenario output for a label scenario includes Manual Label nav steps."""
    from unittest.mock import MagicMock
    from pipeline.smart_ac_verifier import _plan_scenario, _MCSL_WORKFLOW_GUIDE

    # Verify the guide contains the explicit filter step
    assert "Add filter" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must contain explicit 'Add filter' step for Order Id"
    )
    assert "Order Id" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must name 'Order Id' as the filter field"
    )
    assert "LABEL CREATED" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must mention 'LABEL CREATED' status"
    )

    # Mock _plan_scenario to return a plan with the expected structure
    mock_claude = MagicMock()
    mock_claude.invoke.return_value.content = """{
        "nav_clicks": [
            "Click ORDERS tab",
            "Add filter: Order Id",
            "Click order link",
            "Click Generate Label"
        ],
        "look_for": ["LABEL CREATED", "Label Summary"],
        "api_to_watch": [],
        "order_action": "create_new",
        "carrier": "FedEx",
        "plan": "Navigate to Orders, filter by Order Id, generate label, wait for LABEL CREATED"
    }"""

    result = _plan_scenario(
        scenario="FedEx dry ice label scenario — generate label for dry ice shipment",
        app_url="https://admin.shopify.com/store/test-store/apps/mcsl-qa",
        code_ctx="",
        expert_insight="Generate label via Order Summary page",
        claude=mock_claude,
    )

    assert isinstance(result, dict), "plan_scenario must return a dict"
    assert "nav_clicks" in result, "plan must have nav_clicks"
    assert "look_for" in result, "plan must have look_for"

    nav_clicks = result.get("nav_clicks", [])
    assert isinstance(nav_clicks, list), "nav_clicks must be a list"
    assert len(nav_clicks) > 0, "nav_clicks must not be empty"

    # At least one nav step must reference Order Id (the filter step)
    has_order_id_step = any("Order Id" in step or "Order ID" in step for step in nav_clicks)
    assert has_order_id_step, (
        f"nav_clicks must include at least one step referencing 'Order Id' (the filter step). "
        f"Got: {nav_clicks}"
    )

    look_for = result.get("look_for", [])
    assert isinstance(look_for, list), "look_for must be a list"
    has_label_created = any("LABEL CREATED" in item for item in look_for)
    assert has_label_created, (
        f"look_for must include 'LABEL CREATED'. Got: {look_for}"
    )


def test_auto_generate_flow():
    """LABEL-02: _MCSL_WORKFLOW_GUIDE contains Actions menu pattern for Auto-Generate Label flow."""
    from pipeline.smart_ac_verifier import _MCSL_WORKFLOW_GUIDE

    # Guide must reference the Actions button locator or description
    assert "Actions button" in _MCSL_WORKFLOW_GUIDE or "buttons-row > button:nth-child(4)" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must describe the Actions button (buttons-row > button:nth-child(4))"
    )

    # Guide must reference Generate Label as an Actions menu item
    assert "Generate Label" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must mention 'Generate Label' as an Actions menu item"
    )

    # Guide must reference Label Batch page (same as bulk flow)
    assert "Label Batch" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must reference 'Label Batch' page in Actions Menu Label flow"
    )


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_bulk_label_flow():
    """LABEL-03: Agent handles Bulk Label generation (header checkbox → Generate labels → SUCCESS)."""
    pass


def test_return_label_flow():
    """LABEL-04: _MCSL_WORKFLOW_GUIDE contains Return Label flow with existing_fulfilled note."""
    from pipeline.smart_ac_verifier import _MCSL_WORKFLOW_GUIDE

    # Guide must mention Create Return Label as Actions menu item
    assert "Create Return Label" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must mention 'Create Return Label' in Return Label flow"
    )

    # Guide must reference the Submit button
    assert "Submit" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must reference 'Submit' button for Return Label modal"
    )

    # Guide must mention Return Created status
    assert "Return Created" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must mention 'Return Created' status"
    )

    # Guide must note that Return Label requires an already-fulfilled order
    assert "existing_fulfilled" in _MCSL_WORKFLOW_GUIDE or "already-fulfilled" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must warn that Return Label requires an already-fulfilled order "
        "(use order_action: existing_fulfilled)"
    )


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_doc01_badge_check():
    """DOC-01: Agent verifies label existence via LABEL CREATED status badge."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_doc02_download_zip():
    """DOC-02: download_zip handler intercepts download, extracts ZIP, sets _zip_content."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_doc02_download_file_csv():
    """DOC-02 (file): download_file handler reads CSV content into _file_content."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_doc03_label_request_xml():
    """DOC-03: How To ZIP download — download_zip target='Click Here' → JSON in _zip_content."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_doc04_print_documents():
    """DOC-04: Print Documents — switch_tab + screenshot, NOT download_zip."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_doc05_rate_log():
    """DOC-05: Rate log — ViewallRateSummary → 3-dots → View Log → dialogHalfDivParent."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_pre01_dry_ice_preconditions():
    """PRE-01: dry ice preconditions include appproducts nav + enable toggle + cleanup note."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_pre02_alcohol_preconditions():
    """PRE-02: alcohol preconditions include appproducts nav + Is Alcohol + cleanup."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_pre03_battery_preconditions():
    """PRE-03: battery preconditions include appproducts nav + Is Battery + material/packing."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_pre04_signature_preconditions():
    """PRE-04: signature preconditions include appproducts nav + Signature field."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_pre05_hal_preconditions():
    """PRE-05: HAL preconditions include label_flow[:5] + SideDock steps."""
    pass


@pytest.mark.skip(reason="Wave 0 stub — activated in later plans")
def test_pre06_insurance_preconditions():
    """PRE-06: insurance preconditions include label_flow[:5] + SideDock insurance steps."""
    pass


def test_label05_dangerous_products(tmp_path):
    """LABEL-05: create_order with use_dangerous_products=True uses DANGEROUS_PRODUCTS_JSON."""
    import json
    from unittest.mock import MagicMock, patch, call

    # Create a carrier-env file with both SIMPLE and DANGEROUS product JSON
    env_file = tmp_path / "test-carrier.env"
    env_file.write_text(
        'SHOPIFY_STORE_NAME=mcsl-automation\n'
        'SHOPIFY_ACCESS_TOKEN=fake_token\n'
        'SHOPIFY_API_VERSION=2023-01\n'
        'SIMPLE_PRODUCTS_JSON=[{"product_id": 100, "variant_id": 1001}]\n'
        'DANGEROUS_PRODUCTS_JSON=[{"product_id": 200, "variant_id": 2002}]\n',
        encoding="utf-8",
    )

    mock_response = MagicMock()
    mock_response.json.return_value = {"order": {"id": "8888"}}
    mock_response.raise_for_status.return_value = None

    with patch("pipeline.order_creator.requests.post", return_value=mock_response) as mock_post:
        from pipeline.order_creator import create_order, create_bulk_orders

        # Test create_order with use_dangerous_products=True
        order_id = create_order(env_file, use_dangerous_products=True)
        assert order_id == "8888"

        # Verify the body sent to Shopify uses variant_id from DANGEROUS_PRODUCTS_JSON
        call_kwargs = mock_post.call_args
        payload = call_kwargs[1]["json"]  # keyword arg
        line_items = payload["order"]["line_items"]
        assert len(line_items) == 1
        assert line_items[0]["variant_id"] == 2002, (
            f"Expected variant_id 2002 (from DANGEROUS_PRODUCTS_JSON) "
            f"but got {line_items[0]['variant_id']}"
        )

        # Test create_order with use_dangerous_products=False uses SIMPLE_PRODUCTS_JSON
        mock_post.reset_mock()
        mock_response.json.return_value = {"order": {"id": "7777"}}
        order_id_simple = create_order(env_file, use_dangerous_products=False)
        assert order_id_simple == "7777"
        call_kwargs2 = mock_post.call_args
        payload2 = call_kwargs2[1]["json"]
        line_items2 = payload2["order"]["line_items"]
        assert line_items2[0]["variant_id"] == 1001, (
            f"Expected variant_id 1001 (from SIMPLE_PRODUCTS_JSON) "
            f"but got {line_items2[0]['variant_id']}"
        )

        # Test create_bulk_orders also accepts use_dangerous_products
        mock_post.reset_mock()
        mock_response.json.return_value = {"order": {"id": "9999"}}
        order_ids = create_bulk_orders(env_file, count=2, use_dangerous_products=True)
        assert len(order_ids) == 2
        # Both calls should use dangerous products
        for c in mock_post.call_args_list:
            items = c[1]["json"]["order"]["line_items"]
            assert items[0]["variant_id"] == 2002, (
                f"bulk order should use variant_id 2002 but got {items[0]['variant_id']}"
            )
