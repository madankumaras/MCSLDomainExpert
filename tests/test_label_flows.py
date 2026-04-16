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


def test_bulk_label_flow():
    """LABEL-03: _MCSL_WORKFLOW_GUIDE contains Bulk Label flow with correct casing and steps."""
    from pipeline.smart_ac_verifier import _MCSL_WORKFLOW_GUIDE

    # Critical: "Generate labels" must use lowercase "l" (exact button name in orderGridPage.ts)
    assert "Generate labels" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must contain 'Generate labels' (lowercase l) — "
        "using 'Generate Labels' (capital L) will fail all 7 click attempts"
    )

    # Guide must explicitly warn about the lowercase "l" casing requirement
    assert "lowercase" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must explicitly warn that 'Generate labels' uses lowercase 'l' "
        "— the agent needs the warning to avoid using 'Generate Labels' (capital L)"
    )

    # Guide must describe the header checkbox selection step
    assert "header" in _MCSL_WORKFLOW_GUIDE and "checkbox" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must describe the header row checkbox step for bulk label flow"
    )

    # Guide must include a filter step for unfulfilled orders
    assert "Unfulfilled" in _MCSL_WORKFLOW_GUIDE or "unfulfilled" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE Bulk Label section must include filter for unfulfilled orders "
        "so only the test orders are visible in the grid"
    )

    # Guide must reference the Label Batch page result
    assert "Label Batch" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must reference 'Label Batch' page that opens after Generate labels"
    )

    # Guide must include Mark as Fulfilled as the final bulk step
    assert "Mark as Fulfilled" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must include 'Mark as Fulfilled' as the final bulk label step"
    )


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


def test_doc01_badge_check():
    """DOC-01: _MCSL_WORKFLOW_GUIDE documents badge check strategy with LABEL CREATED locators."""
    from pipeline.smart_ac_verifier import _MCSL_WORKFLOW_GUIDE

    # Guide must contain LABEL CREATED badge check
    assert "LABEL CREATED" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must contain 'LABEL CREATED' badge check"
    )

    # Guide must reference the order-summary-greyBlock status locator or status reference
    assert "order-summary-greyBlock" in _MCSL_WORKFLOW_GUIDE or "status" in _MCSL_WORKFLOW_GUIDE.lower(), (
        "_MCSL_WORKFLOW_GUIDE DOC-01 must reference the status span locator or status description"
    )

    # Guide must mention Label Summary verification step
    assert "Label Summary" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-01 must include Label Summary check"
    )


def test_doc02_download_zip():
    """DOC-02: _MCSL_WORKFLOW_GUIDE documents Download Documents ZIP strategy."""
    from pipeline.smart_ac_verifier import _MCSL_WORKFLOW_GUIDE

    # Guide must mention Download Documents button
    assert "Download Documents" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must mention 'Download Documents' button"
    )

    # Guide must reference download_zip action
    assert "download_zip" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-02 must reference 'download_zip' action"
    )

    # Guide must mention _zip_content result
    assert "_zip_content" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-02 must mention '_zip_content' to indicate where results are stored"
    )


def test_doc02_download_zip_handler():
    """DOC-02 handler: _do_action download_zip extracts ZIP content into action['_zip_content']."""
    import io
    import zipfile
    from unittest.mock import MagicMock, patch

    # Build an in-memory ZIP with a JSON file
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Download Documents.json", '{"shipment_id": "123"}')
    buf.seek(0)
    zip_bytes = buf.read()

    # Mock a temporary file path that download.save_as writes the ZIP into
    import tempfile, os, shutil

    tmp_dir = tempfile.mkdtemp(prefix="test_sav_zip_")
    zip_path = os.path.join(tmp_dir, "mcsl_download.zip")
    with open(zip_path, "wb") as f:
        f.write(zip_bytes)

    mock_download = MagicMock()

    def fake_save_as(path):
        shutil.copy(zip_path, path)

    mock_download.save_as.side_effect = fake_save_as

    mock_dl_info = MagicMock()
    mock_dl_info.__enter__ = MagicMock(return_value=mock_dl_info)
    mock_dl_info.__exit__ = MagicMock(return_value=False)
    mock_dl_info.value = mock_download

    mock_frame = MagicMock()
    mock_el = MagicMock()
    mock_el.count.return_value = 1
    mock_el.first = mock_el
    mock_frame.get_by_role.return_value = mock_el

    mock_page = MagicMock()
    mock_page.frames = []
    mock_page.expect_download.return_value = mock_dl_info
    mock_page.get_by_role.return_value = mock_el

    action = {"action": "download_zip", "target": "Download Documents"}

    with patch("pipeline.smart_ac_verifier._get_app_frame", return_value=mock_frame):
        from pipeline.smart_ac_verifier import _do_action
        result = _do_action(mock_page, action)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    assert result is True, f"download_zip _do_action should return True, got {result}"
    assert "_zip_content" in action, "action should have '_zip_content' after download_zip"
    assert "Download Documents.json" in action["_zip_content"], (
        f"_zip_content should contain 'Download Documents.json', keys: {list(action['_zip_content'].keys())}"
    )
    assert action["_zip_content"]["Download Documents.json"]["shipment_id"] == "123", (
        f"Parsed JSON should have shipment_id='123', got: {action['_zip_content']['Download Documents.json']}"
    )


def test_doc03_how_to_zip():
    """DOC-02 handler: download_zip works with mixed content (JSON + CSV)."""
    import io
    import zipfile
    from unittest.mock import MagicMock, patch
    import tempfile, os, shutil

    # Build an in-memory ZIP with JSON + CSV files
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("data.json", '{"key": "value"}')
        zf.writestr("report.csv", "col1,col2\nval1,val2\n")
    buf.seek(0)
    zip_bytes = buf.read()

    tmp_dir = tempfile.mkdtemp(prefix="test_how_to_zip_")
    zip_path = os.path.join(tmp_dir, "mcsl_download.zip")
    with open(zip_path, "wb") as f:
        f.write(zip_bytes)

    mock_download = MagicMock()

    def fake_save_as(path):
        shutil.copy(zip_path, path)

    mock_download.save_as.side_effect = fake_save_as

    mock_dl_info = MagicMock()
    mock_dl_info.__enter__ = MagicMock(return_value=mock_dl_info)
    mock_dl_info.__exit__ = MagicMock(return_value=False)
    mock_dl_info.value = mock_download

    mock_frame = MagicMock()
    mock_el = MagicMock()
    mock_el.count.return_value = 1
    mock_el.first = mock_el
    mock_frame.get_by_role.return_value = mock_el

    mock_page = MagicMock()
    mock_page.frames = []
    mock_page.expect_download.return_value = mock_dl_info
    mock_page.get_by_role.return_value = mock_el

    action = {"action": "download_zip", "target": "Download"}

    with patch("pipeline.smart_ac_verifier._get_app_frame", return_value=mock_frame):
        from pipeline.smart_ac_verifier import _do_action
        result = _do_action(mock_page, action)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    assert result is True, f"download_zip should return True for mixed ZIP, got {result}"
    assert "_zip_content" in action
    content = action["_zip_content"]
    assert "data.json" in content, f"JSON file should be in _zip_content, keys={list(content.keys())}"
    assert "report.csv" in content, f"CSV file should be in _zip_content, keys={list(content.keys())}"
    assert isinstance(content["data.json"], dict), "JSON content should be parsed as dict"
    assert isinstance(content["report.csv"], str), "CSV content should be a string"


def test_doc02_download_file_csv():
    """DOC-02 (file): download_file handler reads CSV content into _file_content."""
    import io
    import tempfile, os, shutil
    from unittest.mock import MagicMock, patch

    # Build a CSV file in a temp location
    csv_content = "col1,col2,col3\nrow1a,row1b,row1c\nrow2a,row2b,row2c\n"
    tmp_dir = tempfile.mkdtemp(prefix="test_sav_file_")
    csv_path = os.path.join(tmp_dir, "report.csv")
    with open(csv_path, "w", encoding="utf-8") as f:
        f.write(csv_content)

    mock_download = MagicMock()
    mock_download.suggested_filename = "report.csv"

    def fake_save_as(path):
        shutil.copy(csv_path, path)

    mock_download.save_as.side_effect = fake_save_as

    mock_dl_info = MagicMock()
    mock_dl_info.__enter__ = MagicMock(return_value=mock_dl_info)
    mock_dl_info.__exit__ = MagicMock(return_value=False)
    mock_dl_info.value = mock_download

    mock_frame = MagicMock()
    mock_el = MagicMock()
    mock_el.count.return_value = 1
    mock_el.first = mock_el
    mock_frame.get_by_role.return_value = mock_el

    mock_page = MagicMock()
    mock_page.frames = []
    mock_page.expect_download.return_value = mock_dl_info
    mock_page.get_by_role.return_value = mock_el

    action = {"action": "download_file", "target": "Export CSV"}

    with patch("pipeline.smart_ac_verifier._get_app_frame", return_value=mock_frame):
        from pipeline.smart_ac_verifier import _do_action
        result = _do_action(mock_page, action)

    shutil.rmtree(tmp_dir, ignore_errors=True)

    assert result is True, f"download_file _do_action should return True, got {result}"
    assert "_file_content" in action, "action should have '_file_content' after download_file"
    fc = action["_file_content"]
    assert isinstance(fc, dict), f"_file_content should be a dict, got {type(fc)}"
    assert "headers" in fc, f"_file_content must have 'headers' key, keys={list(fc.keys())}"
    assert "row_count" in fc, f"_file_content must have 'row_count' key, keys={list(fc.keys())}"
    assert "sample_rows" in fc, f"_file_content must have 'sample_rows' key, keys={list(fc.keys())}"
    assert fc["headers"] == ["col1", "col2", "col3"], f"Unexpected headers: {fc['headers']}"
    assert fc["row_count"] == 2, f"Expected 2 data rows, got {fc['row_count']}"


def test_doc03_label_request_xml():
    """DOC-03: _MCSL_WORKFLOW_GUIDE documents Label Request XML/JSON via 3-dots on Label Summary row."""
    from pipeline.smart_ac_verifier import _MCSL_WORKFLOW_GUIDE

    # Guide must reference Label Summary table (where the 3-dots are)
    assert "Label Summary" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-03 must reference 'Label Summary' table"
    )

    # Guide must reference td:nth-child(8) 3-dots locator or a named reference to it
    assert "td:nth-child(8)" in _MCSL_WORKFLOW_GUIDE or "3-dots" in _MCSL_WORKFLOW_GUIDE or "click3Dots" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-03 must reference the 3-dots locator on Label Summary row"
    )

    # Guide must mention View Log menuitem
    assert "View Log" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-03 must mention 'View Log' menuitem"
    )

    # Guide must mention dialogHalfDivParent dialog
    assert "dialogHalfDivParent" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-03 must mention '.dialogHalfDivParent' dialog locator"
    )


def test_doc04_print_documents():
    """DOC-04: _MCSL_WORKFLOW_GUIDE documents Print Documents as new-tab strategy (switch_tab, NOT download_zip)."""
    from pipeline.smart_ac_verifier import _MCSL_WORKFLOW_GUIDE

    # Guide must mention Print Documents
    assert "Print Documents" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE must mention 'Print Documents' button"
    )

    # Guide must specify switch_tab action (NOT download_zip)
    assert "switch_tab" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-04 must specify 'switch_tab' action for Print Documents"
    )

    # Guide must explicitly warn NOT to use download_zip for Print Documents
    assert "NOT" in _MCSL_WORKFLOW_GUIDE and "download_zip" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-04 must explicitly warn against using download_zip for Print Documents"
    )


def test_doc05_rate_log():
    """DOC-05: _MCSL_WORKFLOW_GUIDE documents rate log strategy with ViewallRateSummary expand step."""
    from pipeline.smart_ac_verifier import _MCSL_WORKFLOW_GUIDE

    # Guide must reference ViewallRateSummary expand step
    assert "ViewallRateSummary" in _MCSL_WORKFLOW_GUIDE or "View all Rate Summary" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-05 must reference 'ViewallRateSummary' or 'View all Rate Summary' expand step"
    )

    # Guide must mention dialogHalfDivParent dialog
    assert "dialogHalfDivParent" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-05 must reference '.dialogHalfDivParent' dialog locator"
    )

    # Guide must note that table must be expanded BEFORE clicking 3-dots
    assert "FIRST" in _MCSL_WORKFLOW_GUIDE or "expand" in _MCSL_WORKFLOW_GUIDE.lower() or "COLLAPSED" in _MCSL_WORKFLOW_GUIDE or "collapsed" in _MCSL_WORKFLOW_GUIDE, (
        "_MCSL_WORKFLOW_GUIDE DOC-05 must note that the rate table must be expanded before clicking 3-dots"
    )


def test_pre01_dry_ice_preconditions():
    """PRE-01: dry ice preconditions include MCSL AppProducts nav + enable toggle + CLEANUP as list item."""
    from pipeline.smart_ac_verifier import _get_preconditions

    steps = _get_preconditions(scenario_text="dry ice shipment", carrier="fedex")
    assert isinstance(steps, list), f"_get_preconditions must return a list, got {type(steps)}"

    # Must include the Is Dry Ice Needed toggle step
    has_dry_ice_toggle = any("Is Dry Ice Needed" in s for s in steps)
    assert has_dry_ice_toggle, (
        f"PRE-01 steps must contain 'Is Dry Ice Needed' toggle step. Steps: {steps}"
    )

    # Must include a CLEANUP step as a list item (not just a comment string)
    cleanup_steps = [s for s in steps if s.startswith("(CLEANUP")]
    assert len(cleanup_steps) > 0, (
        f"PRE-01 steps must include at least one (CLEANUP ...) list item. Steps: {steps}"
    )
    has_cleanup_dry_ice = any(
        "Is Dry Ice Needed" in s or "uncheck" in s.lower() or "dry ice" in s.lower()
        for s in cleanup_steps
    )
    assert has_cleanup_dry_ice, (
        f"PRE-01 CLEANUP step must mention 'Is Dry Ice Needed' or 'uncheck'. Cleanup steps: {cleanup_steps}"
    )


def test_pre02_alcohol_preconditions():
    """PRE-02: alcohol preconditions include MCSL AppProducts nav + Is Alcohol + CLEANUP as list item."""
    from pipeline.smart_ac_verifier import _get_preconditions

    steps = _get_preconditions(scenario_text="alcohol shipment", carrier="fedex")
    assert isinstance(steps, list)

    # Must include the Is Alcohol toggle step
    has_alcohol_toggle = any("Is Alcohol" in s for s in steps)
    assert has_alcohol_toggle, (
        f"PRE-02 steps must contain 'Is Alcohol' toggle step. Steps: {steps}"
    )

    # Must include a CLEANUP step referencing Is Alcohol
    cleanup_steps = [s for s in steps if s.startswith("(CLEANUP")]
    assert len(cleanup_steps) > 0, (
        f"PRE-02 steps must include at least one (CLEANUP ...) list item. Steps: {steps}"
    )
    has_cleanup_alcohol = any(
        "Is Alcohol" in s or "alcohol" in s.lower()
        for s in cleanup_steps
    )
    assert has_cleanup_alcohol, (
        f"PRE-02 CLEANUP step must mention 'Is Alcohol'. Cleanup steps: {cleanup_steps}"
    )


def test_pre03_battery_preconditions():
    """PRE-03: battery preconditions include MCSL AppProducts nav + Is Battery/Dangerous Good + CLEANUP."""
    from pipeline.smart_ac_verifier import _get_preconditions

    steps = _get_preconditions(scenario_text="battery shipment", carrier="fedex")
    assert isinstance(steps, list)

    # Must include Is Battery or Dangerous Good toggle step
    has_battery_toggle = any(
        "Is Battery" in s or "Dangerous Good" in s for s in steps
    )
    assert has_battery_toggle, (
        f"PRE-03 steps must contain 'Is Battery' or 'Dangerous Good' toggle step. Steps: {steps}"
    )

    # Must include a CLEANUP step
    cleanup_steps = [s for s in steps if s.startswith("(CLEANUP")]
    assert len(cleanup_steps) > 0, (
        f"PRE-03 steps must include at least one (CLEANUP ...) list item. Steps: {steps}"
    )


def test_pre04_signature_preconditions():
    """PRE-04: signature preconditions include MCSL AppProducts nav + Signature field + CLEANUP."""
    from pipeline.smart_ac_verifier import _get_preconditions

    steps = _get_preconditions(scenario_text="signature required shipment", carrier="fedex")
    assert isinstance(steps, list)

    # Must include a Signature field step
    has_signature_step = any("Signature" in s for s in steps)
    assert has_signature_step, (
        f"PRE-04 steps must contain a 'Signature' step. Steps: {steps}"
    )

    # Must include a CLEANUP step
    cleanup_steps = [s for s in steps if s.startswith("(CLEANUP")]
    assert len(cleanup_steps) > 0, (
        f"PRE-04 steps must include at least one (CLEANUP ...) list item. Steps: {steps}"
    )


def test_pre05_hal_preconditions():
    """PRE-05: HAL preconditions include AppProducts nav + Hold at Location + CLEANUP. No SideDock."""
    from pipeline.smart_ac_verifier import _get_preconditions

    steps = _get_preconditions(scenario_text="hold at location shipment", carrier="fedex")
    assert isinstance(steps, list), f"_get_preconditions must return a list, got {type(steps)}"

    # Must include Hold at Location step
    has_hal_step = any("Hold at Location" in s for s in steps)
    assert has_hal_step, (
        f"PRE-05 steps must contain 'Hold at Location' step. Steps: {steps}"
    )

    # Must reference AppProducts hamburger nav (no SideDock in MCSL)
    has_nav = any(
        "hamburger" in s.lower() or "Products" in s
        for s in steps
    )
    assert has_nav, (
        f"PRE-05 steps must reference AppProducts navigation (hamburger or Products). Steps: {steps}"
    )

    # Must include a CLEANUP step
    cleanup_steps = [s for s in steps if s.startswith("(CLEANUP")]
    assert len(cleanup_steps) > 0, (
        f"PRE-05 steps must include at least one (CLEANUP ...) list item. Steps: {steps}"
    )

    # Must NOT reference SideDock (SideDock is FedEx-only, does not exist in MCSL)
    has_sidedock = any("SideDock" in s for s in steps)
    assert not has_sidedock, (
        f"PRE-05 (HAL) must NOT reference 'SideDock' — SideDock does not exist in MCSL. Steps: {steps}"
    )


def test_pre06_insurance_preconditions():
    """PRE-06: insurance preconditions include AppProducts nav + Insurance/Declared Value + CLEANUP. No SideDock."""
    from pipeline.smart_ac_verifier import _get_preconditions

    steps = _get_preconditions(scenario_text="insurance coverage shipment", carrier="fedex")
    assert isinstance(steps, list), f"_get_preconditions must return a list, got {type(steps)}"

    # Must include Insurance or Declared Value step
    has_insurance_step = any("Insurance" in s or "Declared Value" in s for s in steps)
    assert has_insurance_step, (
        f"PRE-06 steps must contain 'Insurance' or 'Declared Value' step. Steps: {steps}"
    )

    # Must reference AppProducts hamburger nav (no SideDock in MCSL)
    has_nav = any(
        "hamburger" in s.lower() or "Products" in s
        for s in steps
    )
    assert has_nav, (
        f"PRE-06 steps must reference AppProducts navigation (hamburger or Products). Steps: {steps}"
    )

    # Must include a CLEANUP step
    cleanup_steps = [s for s in steps if s.startswith("(CLEANUP")]
    assert len(cleanup_steps) > 0, (
        f"PRE-06 steps must include at least one (CLEANUP ...) list item. Steps: {steps}"
    )

    # Must NOT reference SideDock (SideDock is FedEx-only, does not exist in MCSL)
    has_sidedock = any("SideDock" in s for s in steps)
    assert not has_sidedock, (
        f"PRE-06 (Insurance) must NOT reference 'SideDock' — SideDock does not exist in MCSL. Steps: {steps}"
    )


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
