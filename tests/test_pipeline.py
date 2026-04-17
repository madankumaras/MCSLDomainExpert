"""
tests/test_pipeline.py — Unit tests for pipeline/user_story_writer.py, pipeline/trello_client.py
Phase 06 Plan 01 — TDD RED phase
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch, call

import pytest


# ---------------------------------------------------------------------------
# US-01: generate_user_story
# ---------------------------------------------------------------------------

def test_us01_generate_returns_markdown():
    """generate_user_story() returns non-empty string with User Story or Acceptance Criteria."""
    fake_response = MagicMock()
    fake_response.content = "### User Story\nAs a merchant...\n### Acceptance Criteria\n- AC1: signature"

    with patch("pipeline.user_story_writer._get_claude") as mock_get_claude, \
         patch("rag.vectorstore.search", return_value=[]), \
         patch("rag.code_indexer.search_code", return_value=[]):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_get_claude.return_value = mock_llm

        from pipeline.user_story_writer import generate_user_story
        result = generate_user_story("Add FedEx signature option")

    assert isinstance(result, str)
    assert len(result) > 0
    assert "User Story" in result or "Acceptance Criteria" in result


def test_us01_generate_no_rag():
    """generate_user_story() handles RAG exceptions gracefully — no crash."""
    fake_response = MagicMock()
    fake_response.content = "### User Story\nAs a merchant, I want FedEx signature so that deliveries are confirmed."

    with patch("pipeline.user_story_writer._get_claude") as mock_get_claude, \
         patch("rag.vectorstore.search", side_effect=Exception("Collection empty")), \
         patch("rag.code_indexer.search_code", side_effect=Exception("Collection empty")):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_get_claude.return_value = mock_llm

        from pipeline.user_story_writer import generate_user_story
        result = generate_user_story("some feature")

    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# US-02: refine_user_story
# ---------------------------------------------------------------------------

def test_us02_refine_returns_updated():
    """refine_user_story() returns non-empty updated markdown."""
    fake_response = MagicMock()
    fake_response.content = "### User Story\nUpdated story with concise ACs."

    with patch("pipeline.user_story_writer._get_claude") as mock_get_claude:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_get_claude.return_value = mock_llm

        from pipeline.user_story_writer import refine_user_story
        result = refine_user_story("### User Story\nOriginal", "Make it more concise")

    assert isinstance(result, str)
    assert len(result) > 0


def test_us02_refine_prompt_contains_both():
    """refine_user_story() passes both previous_us and change_request into the LLM prompt."""
    captured_messages = []

    fake_response = MagicMock()
    fake_response.content = "### User Story\nRefined output."

    def fake_invoke(messages):
        captured_messages.extend(messages)
        return fake_response

    with patch("pipeline.user_story_writer._get_claude") as mock_get_claude:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = fake_invoke
        mock_get_claude.return_value = mock_llm

        from pipeline.user_story_writer import refine_user_story
        refine_user_story("PREVIOUS_CONTENT", "CHANGE_REQUEST_TEXT")

    # The prompt content should include both strings
    all_content = " ".join(str(m) for m in captured_messages)
    assert "PREVIOUS_CONTENT" in all_content
    assert "CHANGE_REQUEST_TEXT" in all_content


# ---------------------------------------------------------------------------
# US-03: TrelloClient — create card and missing credentials
# ---------------------------------------------------------------------------

def test_us03_trello_card_created():
    """create_card_in_list() returns TrelloCard with id from API response."""
    fake_json = {"id": "card123", "name": "My Feature", "desc": "AC here",
                 "url": "https://trello.com/c/card123", "idList": "list1", "idMembers": []}
    mock_response = MagicMock()
    mock_response.json.return_value = fake_json
    mock_response.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_response):
        from pipeline.trello_client import TrelloClient
        client = TrelloClient(api_key="k", token="t", board_id="b")
        card = client.create_card_in_list(list_id="list1", name="My Feature", desc="AC here")

    assert card.id == "card123"


def test_us03_trello_missing_creds():
    """TrelloClient() raises ValueError when Trello env vars are missing."""
    env_backup = {}
    for key in ("TRELLO_API_KEY", "TRELLO_TOKEN", "TRELLO_BOARD_ID"):
        env_backup[key] = os.environ.pop(key, None)

    try:
        from pipeline.trello_client import TrelloClient
        with pytest.raises(ValueError):
            TrelloClient()
    finally:
        for key, val in env_backup.items():
            if val is not None:
                os.environ[key] = val


# ---------------------------------------------------------------------------
# MC-01: move_card_to_list_by_id and add_comment
# ---------------------------------------------------------------------------

def test_mc01_move_card_by_id():
    """move_card_to_list_by_id() calls PUT /cards/{card_id} with idList=list_id."""
    fake_json = {"id": "card123"}
    mock_response = MagicMock()
    mock_response.json.return_value = fake_json
    mock_response.raise_for_status = MagicMock()
    mock_response.status_code = 200

    with patch("requests.put", return_value=mock_response) as mock_put:
        from pipeline.trello_client import TrelloClient
        client = TrelloClient(api_key="k", token="t", board_id="b")
        client.move_card_to_list_by_id("card123", "list456")

    mock_put.assert_called_once()
    call_args = mock_put.call_args
    url = call_args[0][0]
    assert "card123" in url

    # idList must be in the json body
    json_body = call_args.kwargs.get("json") or (call_args[1].get("json") if len(call_args) > 1 else None)
    assert json_body is not None, "Expected json keyword arg in requests.put call"
    assert json_body.get("idList") == "list456"


def test_mc01_audit_comment():
    """add_comment() calls POST to cards/{card_id}/actions/comments."""
    mock_response = MagicMock()
    mock_response.json.return_value = {}
    mock_response.raise_for_status = MagicMock()

    with patch("requests.post", return_value=mock_response) as mock_post:
        from pipeline.trello_client import TrelloClient
        client = TrelloClient(api_key="k", token="t", board_id="b")
        client.add_comment("card123", "Moved by MCSL QA Pipeline")

    mock_post.assert_called_once()
    call_url = mock_post.call_args[0][0]
    assert "card123" in call_url
    assert "actions/comments" in call_url


# ---------------------------------------------------------------------------
# HIST-01: history persistence (skips gracefully if 06-03 not yet done)
# ---------------------------------------------------------------------------

def test_hist01_save_history(tmp_path):
    """_save_history() writes valid JSON; _load_history() reads it back."""
    pd = pytest.importorskip("pipeline_dashboard")
    if not hasattr(pd, "_save_history"):
        pytest.skip("_save_history not yet implemented (06-03)")

    hist_file = tmp_path / "pipeline_history.json"
    data = {"card1": {"card_name": "X", "approved_at": "2026-01-01"}}

    with patch.object(pd, "_HISTORY_FILE", hist_file):
        pd._save_history(data)
        assert hist_file.exists()
        assert json.loads(hist_file.read_text()) == data


def test_hist01_load_empty(tmp_path):
    """_load_history() returns {} when file does not exist."""
    pd = pytest.importorskip("pipeline_dashboard")
    if not hasattr(pd, "_load_history"):
        pytest.skip("_load_history not yet implemented (06-03)")

    nonexistent = tmp_path / "no_file.json"
    with patch.object(pd, "_HISTORY_FILE", nonexistent):
        result = pd._load_history()
    assert result == {}


def test_hist01_entry_schema(tmp_path):
    """History entries must contain card_name, approved_at, card_url keys."""
    pd = pytest.importorskip("pipeline_dashboard")
    if not hasattr(pd, "_save_history") or not hasattr(pd, "_load_history"):
        pytest.skip("_save_history/_load_history not yet implemented (06-03)")

    entry = {"card_name": "X", "approved_at": "2026-01-01", "card_url": "https://trello.com/c/xyz"}
    hist_file = tmp_path / "pipeline_history.json"

    with patch.object(pd, "_HISTORY_FILE", hist_file):
        pd._save_history({"card1": entry})
        loaded = pd._load_history()

    assert "card_name" in loaded["card1"]
    assert "approved_at" in loaded["card1"]
    assert "card_url" in loaded["card1"]


# ---------------------------------------------------------------------------
# RQA-05: analyse_release — release intelligence + risk analysis
# ---------------------------------------------------------------------------

def test_rqa05_analyse_release_returns_report():
    """analyse_release() returns ReleaseAnalysis with valid risk_level and empty error."""
    fake_content = '{"risk_level":"LOW","risk_summary":"No conflicts","conflicts":[],"ordering":[],"coverage_gaps":[],"kb_context_summary":"","sources":[]}'
    fake_response = MagicMock()
    fake_response.content = fake_content

    import config as _config
    with patch("pipeline.release_analyser.ChatAnthropic") as mock_claude, \
         patch("rag.vectorstore.search", return_value=[]), \
         patch.object(_config, "ANTHROPIC_API_KEY", "fake-key"):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_claude.return_value = mock_llm

        from pipeline.release_analyser import analyse_release, CardSummary, ReleaseAnalysis
        result = analyse_release(
            "v1.2",
            [CardSummary(card_id="c1", card_name="FedEx Label", card_desc="Add FedEx label")],
        )

    assert isinstance(result, ReleaseAnalysis)
    assert result.risk_level in {"LOW", "MEDIUM", "HIGH"}
    assert result.error == ""


def test_rqa05_analyse_release_empty_cards():
    """analyse_release() with empty cards list returns ReleaseAnalysis(risk_level='LOW') with non-empty error."""
    from pipeline.release_analyser import analyse_release, ReleaseAnalysis

    result = analyse_release("v1.2", [])

    assert isinstance(result, ReleaseAnalysis)
    assert result.risk_level == "LOW"
    assert result.error != ""


def test_rqa05_analyse_release_no_api_key():
    """analyse_release() returns ReleaseAnalysis with non-empty error when ANTHROPIC_API_KEY is empty."""
    import pipeline.release_analyser as ra_mod
    import config

    with patch.object(config, "ANTHROPIC_API_KEY", ""):
        from pipeline.release_analyser import analyse_release, CardSummary, ReleaseAnalysis
        result = analyse_release(
            "v1.2",
            [CardSummary(card_id="c1", card_name="X", card_desc="Y")],
        )

    assert isinstance(result, ReleaseAnalysis)
    assert result.error != ""


# ---------------------------------------------------------------------------
# RQA-04: append_to_sheet + detect_tab — Google Sheets writer
# ---------------------------------------------------------------------------

def test_rqa04_append_to_sheet_returns_meta():
    """append_to_sheet() returns dict with 'tab' (str) and 'rows_added' (int) keys."""
    header_row = [["SI No", "Epic", "Scenarios", "Description", "Comments", "Priority", "Details", "Pass/Fail", "Release"]]

    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = header_row
    mock_ws.append_row = MagicMock()
    mock_ws.title = "Shipping Labels"

    mock_sh = MagicMock()
    mock_sh.worksheets.return_value = [mock_ws]
    mock_sh.worksheet.return_value = mock_ws

    mock_gc = MagicMock()
    mock_gc.open_by_key.return_value = mock_sh

    mock_gspread = MagicMock()
    mock_gspread.authorize.return_value = mock_gc

    mock_creds_cls = MagicMock()
    mock_creds_cls.from_service_account_file.return_value = MagicMock()

    import sys
    with patch.dict(sys.modules, {"gspread": mock_gspread, "google.oauth2.service_account": MagicMock()}), \
         patch("pipeline.sheets_writer.check_duplicates", return_value=[]):
        # Ensure google.oauth2.service_account.Credentials is patchable
        sys.modules["google.oauth2.service_account"].Credentials = mock_creds_cls

        from pipeline.sheets_writer import append_to_sheet
        result = append_to_sheet(
            "FedEx Signature Card",
            "## TC-1: Signature Label\nGiven order placed\nWhen label generated\nThen signature required",
            release="v1",
        )

    assert isinstance(result, dict)
    assert "tab" in result and isinstance(result["tab"], str)
    assert "rows_added" in result and isinstance(result["rows_added"], int)


def test_rqa04_detect_tab_keyword_match():
    """detect_tab() returns 'Shipping Labels' for a card name containing 'label'."""
    from pipeline.sheets_writer import detect_tab

    result = detect_tab("Generate FedEx Label", "TC-1: generate label with signature")

    assert result == "Shipping Labels"


# ---------------------------------------------------------------------------
# RQA-01: validate_card — domain_validator (07-01)
# ---------------------------------------------------------------------------

def test_rqa01_validate_card_returns_report():
    """validate_card() returns a ValidationReport with overall_status in {PASS, NEEDS_REVIEW, FAIL}."""
    import config
    fake_json_str = (
        '{"overall_status":"PASS","summary":"OK","requirement_gaps":[],'
        '"ac_gaps":[],"accuracy_issues":[],"suggestions":[],'
        '"kb_insights":"FedEx label flow uses ORDERS tab","sources":[]}'
    )
    fake_response = MagicMock()
    fake_response.content = fake_json_str

    with patch("pipeline.domain_validator.ChatAnthropic") as mock_cls, \
         patch("rag.vectorstore.search", return_value=[]), \
         patch.object(config, "ANTHROPIC_API_KEY", "test-key"):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_cls.return_value = mock_llm

        from pipeline.domain_validator import validate_card, ValidationReport
        result = validate_card("Add FedEx signature", "User wants signature on delivery")

    assert isinstance(result, ValidationReport)
    assert result.overall_status in {"PASS", "NEEDS_REVIEW", "FAIL"}
    assert result.error == ""


def test_rqa01_validate_card_no_api_key():
    """validate_card() returns ValidationReport with non-empty error when ANTHROPIC_API_KEY is empty."""
    import config

    with patch.object(config, "ANTHROPIC_API_KEY", ""):
        from pipeline.domain_validator import validate_card, ValidationReport
        result = validate_card("Some card", "Some desc")

    assert isinstance(result, ValidationReport)
    assert result.error != ""


def test_rqa01_validate_card_rag_failure():
    """validate_card() handles rag.vectorstore.search() exception gracefully — no crash."""
    import config
    fake_json_str = (
        '{"overall_status":"PASS","summary":"OK","requirement_gaps":[],'
        '"ac_gaps":[],"accuracy_issues":[],"suggestions":[],'
        '"kb_insights":"fallback","sources":[]}'
    )
    fake_response = MagicMock()
    fake_response.content = fake_json_str

    with patch("pipeline.domain_validator.ChatAnthropic") as mock_cls, \
         patch("rag.vectorstore.search", side_effect=Exception("Chroma not available")), \
         patch.object(config, "ANTHROPIC_API_KEY", "test-key"):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_cls.return_value = mock_llm

        from pipeline.domain_validator import validate_card, ValidationReport
        result = validate_card("Some card", "Some desc")

    assert isinstance(result, ValidationReport)


# ---------------------------------------------------------------------------
# RQA-02: generate_acceptance_criteria / generate_test_cases (07-01)
# ---------------------------------------------------------------------------

def test_rqa02_generate_ac_returns_markdown():
    """generate_acceptance_criteria() returns non-empty string."""
    fake_response = MagicMock()
    fake_response.content = "### Acceptance Criteria\n- AC1: FedEx signature required"

    with patch("pipeline.card_processor.ChatAnthropic") as mock_cls:
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_cls.return_value = mock_llm

        from pipeline.card_processor import generate_acceptance_criteria
        result = generate_acceptance_criteria("Add FedEx signature option")

    assert isinstance(result, str) and len(result) > 0


def test_rqa02_generate_tc_prompt_contains_card():
    """generate_test_cases() includes card.name in the prompt passed to Claude."""
    captured_messages = []
    fake_response = MagicMock()
    fake_response.content = "## TC-1: Signature\nGiven order placed\nWhen label generated\nThen signature appears"

    def fake_invoke(messages):
        captured_messages.extend(messages)
        return fake_response

    with patch("pipeline.card_processor.ChatAnthropic") as mock_cls:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = fake_invoke
        mock_cls.return_value = mock_llm

        from pipeline.trello_client import TrelloCard
        from pipeline.card_processor import generate_test_cases
        card = TrelloCard(id="c1", name="FedEx Signature Feature", desc="Add signature option")
        generate_test_cases(card)

    all_content = " ".join(str(m) for m in captured_messages)
    assert "FedEx Signature Feature" in all_content


# ---------------------------------------------------------------------------
# RQA-04: write_test_cases_to_card / parse_test_cases_to_rows (07-01)
# ---------------------------------------------------------------------------

def test_rqa04_write_tc_calls_add_comment():
    """write_test_cases_to_card() calls trello.add_comment exactly once."""
    mock_trello = MagicMock()
    mock_trello.add_comment = MagicMock()

    from pipeline.card_processor import write_test_cases_to_card
    write_test_cases_to_card("card1", "## TC-1\nGiven...", trello=mock_trello)

    assert mock_trello.add_comment.call_count == 1


def test_rqa04_parse_tc_rows_gwt():
    """parse_test_cases_to_rows() returns list of TestCaseRow with Given/When/Then in description."""
    from pipeline.card_processor import parse_test_cases_to_rows
    md = (
        "## TC-1: Label with Signature\n"
        "Given the order is placed\n"
        "When the label is generated\n"
        "Then signature confirmation appears"
    )
    result = parse_test_cases_to_rows(card_name="FedEx Test", test_cases_markdown=md)

    assert isinstance(result, list)
    assert len(result) >= 1
    assert hasattr(result[0], "description")
    desc = result[0].description
    assert "Given" in desc or "When" in desc or "Then" in desc
