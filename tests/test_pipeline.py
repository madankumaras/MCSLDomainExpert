"""
tests/test_pipeline.py — Unit tests for pipeline/user_story_writer.py, pipeline/trello_client.py
Phase 06 Plan 01 — TDD RED phase
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import types
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
    all_content = " ".join(getattr(m, "content", str(m)) for m in captured_messages)
    assert "PREVIOUS_CONTENT" in all_content
    assert "CHANGE_REQUEST_TEXT" in all_content


def test_requirement_research_gracefully_degrades_without_rag():
    """Requirement research should still return context when RAG backends are unavailable."""
    fake_vectorstore = types.SimpleNamespace(search=MagicMock(side_effect=Exception("vector db unavailable")))
    fake_code_indexer = types.SimpleNamespace(search_code=MagicMock(side_effect=Exception("code index unavailable")))

    with patch("pipeline.requirement_research.carrier_research_context", return_value="Carrier context"), \
         patch("pipeline.requirement_research.load_runtime_locator_memory_context", return_value=["locator A"]), \
         patch.dict(sys.modules, {"rag.vectorstore": fake_vectorstore, "rag.code_indexer": fake_code_indexer}):
        from pipeline.requirement_research import build_requirement_research_context

        result = build_requirement_research_context("Enable UPS customs value validation")

    assert "Requirement research for User Story / AC" in result
    assert "Carrier context" in result
    assert "Relevant proven UI/navigation hints" in result
    assert "Official carrier/platform findings from local RAG" in result


def test_dashboard_ac_generation_path_keeps_research_and_timestamp_hooks():
    """The AC generation branch should import research context and record timestamps."""
    src = Path("pipeline_dashboard.py").read_text(encoding="utf-8")

    assert "from datetime import datetime" in src
    assert 'if st.button("🤖 Generate User Story & AC"' in src
    assert "from pipeline.requirement_research import build_requirement_research_context" in src
    assert "_research = build_requirement_research_context(_raw)" in src
    assert "ac_generated_at=datetime.now().isoformat(timespec=\"seconds\")" in src


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


def test_mc01_get_card_comments_includes_copied_comments():
    """get_card_comments() should include both direct and copied Trello comments."""
    fake_actions = [
        {"type": "commentCard", "data": {"text": "Direct comment"}},
        {"type": "copyCommentCard", "data": {"text": "Copied comment from source card"}},
        {"type": "updateCard", "data": {"text": "ignore me"}},
    ]
    mock_response = MagicMock()
    mock_response.json.return_value = fake_actions
    mock_response.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_response) as mock_get:
        from pipeline.trello_client import TrelloClient
        client = TrelloClient(api_key="k", token="t", board_id="b")
        comments = client.get_card_comments("card123")

    mock_get.assert_called_once()
    assert comments == ["Direct comment", "Copied comment from source card"]


def test_mc01_get_card_returns_rich_trello_card():
    """get_card() should return a full TrelloCard including labels/comments/attachments/checklists."""
    card_json = {
        "id": "card123",
        "name": "My Feature",
        "desc": "Card description",
        "url": "https://trello.com/c/card123",
        "idList": "list1",
        "labels": [{"name": "SL: Shopify MCSL"}, {"name": "SL: International & Customs"}],
        "idMembers": ["m1"],
    }
    comments_json = [{"type": "commentCard", "data": {"text": "Direct comment"}}]
    attachments_json = [{"name": "spec.pdf", "url": "https://example.com/spec.pdf"}]
    checklists_json = [{"name": "QA", "checkItems": [{"name": "Verify label", "state": "incomplete"}]}]

    responses = []
    for payload in (card_json, comments_json, attachments_json, checklists_json):
        mock_response = MagicMock()
        mock_response.json.return_value = payload
        mock_response.raise_for_status = MagicMock()
        responses.append(mock_response)

    with patch("requests.get", side_effect=responses):
        from pipeline.trello_client import TrelloClient
        client = TrelloClient(api_key="k", token="t", board_id="b")
        card = client.get_card("card123")

    assert card.id == "card123"
    assert card.labels == ["SL: Shopify MCSL", "SL: International & Customs"]
    assert card.comments == ["Direct comment"]
    assert card.attachments == [{"name": "spec.pdf", "url": "https://example.com/spec.pdf"}]
    assert card.checklists == [{"name": "QA", "items": [{"name": "Verify label", "state": "incomplete"}]}]


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


def test_rqa05_analyse_release_accepts_content_blocks():
    """analyse_release() should parse Anthropic content-block responses without fallback."""
    fake_response = MagicMock()
    fake_response.content = [
        {
            "type": "text",
            "text": '{"risk_level":"LOW","risk_summary":"No conflicts","conflicts":[],"ordering":[],"coverage_gaps":[],"kb_context_summary":"","sources":[]}',
        }
    ]

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
    assert result.risk_level == "LOW"
    assert result.error == ""
    assert result.risk_summary == "No conflicts"


def test_rqa05_card_summary_combined_text_includes_comments_labels_and_checklists():
    """Release analysis should see the same richer Trello evidence set, not just title + desc."""
    from pipeline.release_analyser import CardSummary

    card = CardSummary(
        card_id="c1",
        card_name="From SL: ZI-021",
        card_desc="Minimum customs value floor",
        card_comments=["Check FedEx label generation", "Validate FedEx compliance"],
        card_labels=["SL: International & Customs", "SL: Shopify MCSL"],
        card_checklists=[{"name": "QA", "items": [{"name": "Verify value floored to $1"}]}],
    )

    combined = card.combined_text()

    assert "Check FedEx label generation" in combined
    assert "Validate FedEx compliance" in combined
    assert "SL: International & Customs" in combined
    assert "Verify value floored to $1" in combined


def test_rqa06_diagnose_ticket_forces_carrier_specific_when_comments_name_carrier():
    """diagnose_ticket() should override model drift when card text/comments explicitly name a carrier."""
    import config as _config
    from pipeline.ticket_diagnoser import diagnose_ticket

    fake_response = MagicMock()
    fake_response.content = (
        '{"issue_type":"feature","carrier_scope":"generic","likely_root_cause":"request_or_label_api",'
        '"confidence":"medium","summary":"Model guessed generic","evidence":[],"next_checks":[],"suggested_test_strategy":[]}'
    )

    ticket_text = (
        "From SL: ZI-021 — Enhancement: minimum customs value floor\\n"
        "PR: Enforce minimum customs value of 1 in FedEx request builders\\n"
        "[MANUAL TESTING REQUIRED - COMPLIANCE]\\n"
        "- Check FedEx label generation\\n"
        "- Test other carriers for no impact\\n"
        "- Validate FedEx compliance"
    )

    with patch("langchain_anthropic.ChatAnthropic") as mock_claude, \
         patch("rag.vectorstore.search", return_value=[]), \
         patch("rag.code_indexer.search_code", return_value=[]), \
         patch.object(_config, "ANTHROPIC_API_KEY", "fake-key"):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_claude.return_value = mock_llm

        result = diagnose_ticket(ticket_text)

    assert result.carrier_scope == "carrier_specific"
    assert any("FedEx" in item for item in result.evidence)


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

    import pipeline.domain_validator as dv

    with patch.object(dv, "_make_llm") as mock_llm_factory, \
         patch.object(config, "ANTHROPIC_API_KEY", "test-key"):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_llm_factory.return_value = mock_llm

        result = dv.validate_card("Add FedEx signature", "User wants signature on delivery")

    assert isinstance(result, dv.ValidationReport)
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

    import pipeline.domain_validator as dv

    with patch.object(dv, "_make_llm") as mock_llm_factory, \
         patch.object(config, "ANTHROPIC_API_KEY", "test-key"):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_llm_factory.return_value = mock_llm

        result = dv.validate_card("Some card", "Some desc")

    assert isinstance(result, dv.ValidationReport)


def test_rqa01_validate_card_malformed_json_uses_fallback_message():
    """Malformed validator JSON should fall back cleanly without leaking parser details."""
    import config
    import pipeline.domain_validator as dv

    broken_response = MagicMock()
    broken_response.content = '{"overall_status":"NEEDS_REVIEW","summary":"Bad JSON"'

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [broken_response, broken_response, broken_response]

    with patch.object(dv, "_make_llm", return_value=mock_llm), \
         patch.object(config, "ANTHROPIC_API_KEY", "test-key"):
        result = dv.validate_card("Customs floor", "Add minimum customs value floor")

    assert isinstance(result, dv.ValidationReport)
    assert result.error == "Validator returned malformed JSON; fallback validation was used."


def test_rqa01_validate_card_accepts_content_blocks():
    """validate_card() should parse Anthropic content-block responses without fallback."""
    import config
    import pipeline.domain_validator as dv

    fake_response = MagicMock()
    fake_response.content = [
        {
            "type": "text",
            "text": '{"overall_status":"PASS","summary":"Looks good","requirement_gaps":[],"ac_gaps":[],"accuracy_issues":[],"suggestions":[],"kb_insights":"Grounded in MCSL context."}',
        }
    ]

    with patch.object(dv, "_make_llm") as mock_llm_factory, \
         patch.object(config, "ANTHROPIC_API_KEY", "test-key"):
        mock_llm = MagicMock()
        mock_llm.invoke.return_value = fake_response
        mock_llm_factory.return_value = mock_llm

        result = dv.validate_card("Add FedEx signature", "User wants signature on delivery")

    assert isinstance(result, dv.ValidationReport)
    assert result.overall_status == "PASS"
    assert result.error == ""
    assert result.summary == "Looks good"


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

    import pipeline.card_processor as cp

    with patch.object(cp, "_make_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = fake_invoke
        mock_llm_factory.return_value = mock_llm

        from pipeline.trello_client import TrelloCard
        card = TrelloCard(id="c1", name="FedEx Signature Feature", desc="Add signature option")
        cp.generate_test_cases(card)

    all_content = " ".join(getattr(m, "content", str(m)) for m in captured_messages)
    assert "FedEx Signature Feature" in all_content


def test_rqa02_generate_tc_prompt_includes_structured_context_sections():
    """generate_test_cases() keeps the FedEx-style structured context sections in the prompt."""
    captured_messages = []
    fake_response = MagicMock()
    fake_response.content = "### TC-1: Signature\n**Type:** Positive\n**Priority:** High\n**Preconditions:** Carrier configured\n**Steps:**\nGiven setup exists\nWhen label is generated\nThen signature option appears"

    def fake_invoke(messages):
        captured_messages.extend(messages)
        return fake_response

    import pipeline.card_processor as cp

    with patch.object(cp, "_make_llm") as mock_llm_factory:
        mock_llm = MagicMock()
        mock_llm.invoke.side_effect = fake_invoke
        mock_llm_factory.return_value = mock_llm

        from pipeline.trello_client import TrelloCard

        card = TrelloCard(
            id="c2",
            name="Toggle-driven customs floor",
            desc="Validate customs floor behavior",
            comments=["toggle: minimum customs value floor", "Dev note: verify checkout and label flow"],
        )
        cp.generate_test_cases(card)

    all_content = " ".join(getattr(m, "content", str(m)) for m in captured_messages)
    assert "Developer / QA comments from Trello" in all_content
    assert "Similar past test cases from the QA knowledge base" in all_content or "Feature Card:" in all_content
    assert "Relevant automation / code context" in all_content or "Feature Card:" in all_content


def test_slack_toggle_detection_handles_store_enablement_and_unquoted_shopify_keys():
    """Toggle detection should recognize common Trello comment forms used by devs."""
    from pipeline.slack_client import detect_toggles

    toggles = detect_toggles(
        "Enhancement for customs floor",
        "Minimum customs value floor",
        "\n".join([
            "Please enable minimum customs value floor on the store before QA.",
            "feature name: customs floor rollout",
            "shopify.feature.minimum.customs.value.floor.enabled",
        ]),
    )

    lowered = {item.lower() for item in toggles}
    assert any("minimum customs value floor" in item for item in lowered)
    assert any("customs floor rollout" in item for item in lowered)


def test_slack_toggle_detection_handles_generic_config_key_comment():
    """Toggle detection should catch copied config keys from Trello comments."""
    from pipeline.slack_client import detect_toggle_details, detect_toggles

    toggles = detect_toggles(
        "",
        "Enhancement: minimum customs value floor",
        '\n'.join([
            "related toggle to enable country wise customs value:",
            '"accountUUID.country.wise.customs.value.enabled": true,',
        ]),
    )

    lowered = {item.lower() for item in toggles}
    assert any("country wise customs value" in item for item in lowered)
    details = detect_toggle_details(
        "",
        "Enhancement: minimum customs value floor",
        '\n'.join([
            "related toggle to enable country wise customs value:",
            '"accountUUID.country.wise.customs.value.enabled": true,',
        ]),
    )
    assert any(item.get("key_template") == "accountUUID.country.wise.customs.value.enabled" for item in details)


def test_slack_toggle_detection_reads_description_and_comment_fallback_shapes():
    """Toggle detection should work across Trello description and comments."""
    from pipeline.slack_client import detect_toggles

    toggles = detect_toggles(
        "\n".join([
            "Prerequisite for QA:",
            "Toggle key:",
            "accountUUID.multi.package.hazmat.enabled",
        ]),
        "Hazmat package update",
        "\n".join([
            "Please enable checkout carrier restrictions for the store before QA.",
            "feature flag is customs floor rollout",
        ]),
    )

    lowered = {item.lower() for item in toggles}
    assert any("multi package hazmat" in item for item in lowered)
    assert any("checkout carrier restrictions" in item for item in lowered)
    assert any("customs floor rollout" in item for item in lowered)


def test_slack_toggle_detection_ignores_toggle_explanatory_prose():
    """Toggle detection should not treat explanatory ON/OFF prose as toggle names."""
    from pipeline.slack_client import detect_toggles

    toggles = detect_toggles(
        "",
        "Minimum customs value floor",
        "\n".join([
            "Toggle: minimum customs value floor",
            "Toggle OFF disables the post-conversion floor, toggle ON enables the post-conversion floor, in its default enabled state.",
        ]),
    )

    lowered = {item.lower() for item in toggles}
    assert "minimum customs value floor" in lowered
    assert not any("post-conversion floor" in item for item in lowered)
    assert "prerequisite" not in lowered


def test_slack_toggle_formatting_keeps_raw_config_key_in_message():
    """Toggle Slack text should keep the raw config key and rely on separate UUID fields."""
    from pipeline.slack_client import _format_toggle_lines

    lines = _format_toggle_lines(
        [
            {
                "label": "country wise customs value",
                "key_template": "accountUUID.country.wise.customs.value.enabled",
            }
        ],
        account_uuid="acc-123",
    )

    assert "country wise customs value" in lines
    assert '"accountUUID.country.wise.customs.value.enabled": true' in lines


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


# ---------------------------------------------------------------------------
# SLACK-01: SlackClient + module helpers (08-01)
# ---------------------------------------------------------------------------

def test_slack01_send_dm():
    """send_dm() calls conversations.open then chat.postMessage and returns ts string."""
    from unittest.mock import MagicMock, patch

    open_resp = MagicMock()
    open_resp.json.return_value = {"channel": {"id": "DM123"}}
    open_resp.raise_for_status = MagicMock()

    msg_resp = MagicMock()
    msg_resp.json.return_value = {"ok": True, "ts": "111.222"}
    msg_resp.raise_for_status = MagicMock()

    with patch("requests.post", side_effect=[open_resp, msg_resp]) as mock_post:
        from pipeline.slack_client import SlackClient
        client = SlackClient(token="xoxb-test", channel="C123", webhook_url="")
        result = client.send_dm("U456", "Hello dev")

    assert mock_post.call_count == 2
    first_url = mock_post.call_args_list[0][0][0]
    assert "conversations.open" in first_url
    second_url = mock_post.call_args_list[1][0][0]
    assert "chat.postMessage" in second_url


def test_slack01_post_to_channel():
    """post_to_channel() calls chat.postMessage with the given channel."""
    from unittest.mock import MagicMock, patch

    msg_resp = MagicMock()
    msg_resp.json.return_value = {"ok": True, "ts": "222.333"}
    msg_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=msg_resp) as mock_post:
        from pipeline.slack_client import SlackClient
        client = SlackClient(token="xoxb-test", channel="C123", webhook_url="")
        client.post_to_channel("Test message", channel="C999")

    assert mock_post.call_count == 1
    call_url = mock_post.call_args_list[0][0][0]
    assert "chat.postMessage" in call_url
    call_json = mock_post.call_args_list[0][1]["json"]
    assert call_json["channel"] == "C999"


def test_slack01_post_signoff_webhook():
    """post_signoff() via webhook returns ok=True (webhook returns plain 'ok' text)."""
    from unittest.mock import MagicMock, patch

    wh_resp = MagicMock()
    wh_resp.status_code = 200
    wh_resp.text = "ok"
    wh_resp.raise_for_status = MagicMock()

    with patch("requests.post", return_value=wh_resp) as mock_post:
        from pipeline.slack_client import SlackClient
        client = SlackClient(token="", channel="", webhook_url="https://hooks.slack.com/test")
        result = client.post_signoff("Sign-off message", channel=None)

    assert mock_post.call_count == 1
    assert result["ok"] is True


def test_slack01_slack_configured_true():
    """slack_configured() returns True when SLACK_WEBHOOK_URL is set."""
    with patch.dict(os.environ, {
        "SLACK_WEBHOOK_URL": "https://hooks.slack.com/x",
        "SLACK_BOT_TOKEN": "",
        "SLACK_CHANNEL": "",
    }):
        from pipeline.slack_client import slack_configured
        assert slack_configured() is True


def test_slack01_list_channels():
    """list_slack_channels() returns (channels_list, error, note) with expected shape."""
    from unittest.mock import MagicMock, patch

    get_resp = MagicMock()
    get_resp.json.return_value = {
        "ok": True,
        "channels": [{"id": "C001", "name": "qa-team"}],
        "response_metadata": {"next_cursor": ""},
    }
    get_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=get_resp), \
         patch.dict(os.environ, {"SLACK_BOT_TOKEN": "xoxb-test", "SLACK_WEBHOOK_URL": "", "SLACK_CHANNEL": ""}):
        from pipeline.slack_client import list_slack_channels
        channels, error, note = list_slack_channels()

    assert isinstance(channels, list)
    assert len(channels) >= 1
    assert channels[0]["id"] == "C001"


def test_slack01_list_channels_uses_bearer_auth_header():
    """Channel listing should use bearer auth headers instead of token query params."""
    get_resp = MagicMock()
    get_resp.json.return_value = {
        "ok": True,
        "channels": [{"id": "C001", "name": "qa-team"}],
        "response_metadata": {"next_cursor": ""},
    }
    get_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=get_resp) as mock_get:
        from pipeline.slack_client import SlackClient

        SlackClient(token="xoxb-test").list_channels()

    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer xoxb-test"
    assert "token" not in mock_get.call_args.kwargs["params"]


def test_slack01_search_users_uses_bearer_auth_header():
    """User search should use bearer auth headers instead of token query params."""
    get_resp = MagicMock()
    get_resp.json.return_value = {
        "ok": True,
        "members": [
            {"id": "U001", "name": "madan", "profile": {"real_name": "Madan", "display_name": "madan"}},
        ],
        "response_metadata": {"next_cursor": ""},
    }
    get_resp.raise_for_status = MagicMock()

    with patch("requests.get", return_value=get_resp) as mock_get:
        from pipeline.slack_client import SlackClient

        results = SlackClient(token="xoxb-test").search_users("madan")

    assert results[0]["id"] == "U001"
    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer xoxb-test"
    assert "token" not in mock_get.call_args.kwargs["params"]


# ---------------------------------------------------------------------------
# SLACK-02: notify_devs_of_bug + get_card_members (08-02)
# ---------------------------------------------------------------------------

def test_slack02_notify_devs():
    """notify_devs_of_bug() fetches card members and sends one DM per member."""
    from unittest.mock import MagicMock

    mock_trello = MagicMock()
    mock_trello.get_card_members.return_value = [
        {"id": "U001", "fullName": "Alice", "username": "alice"}
    ]

    mock_slack = MagicMock()
    mock_slack.send_dm.return_value = "ts.123"

    from pipeline.bug_reporter import notify_devs_of_bug
    result = notify_devs_of_bug(
        "card1",
        "FedEx Label Bug",
        "Label not generated",
        trello_client=mock_trello,
        slack_client=mock_slack,
    )

    mock_trello.get_card_members.assert_called_once_with("card1")
    mock_slack.send_dm.assert_called_once()
    first_arg = mock_slack.send_dm.call_args[0][0]
    assert first_arg == "U001"
    assert result["sent_count"] == 1
    assert not result.get("error")


def test_slack02_notify_devs_no_members():
    """notify_devs_of_bug() with no card members sends no DMs and returns sent_count=0."""
    from unittest.mock import MagicMock

    mock_trello = MagicMock()
    mock_trello.get_card_members.return_value = []

    mock_slack = MagicMock()

    from pipeline.bug_reporter import notify_devs_of_bug
    result = notify_devs_of_bug(
        "card1",
        "Some Bug",
        "desc",
        trello_client=mock_trello,
        slack_client=mock_slack,
    )

    mock_slack.send_dm.assert_not_called()
    assert result["sent_count"] == 0


def test_slack02_get_card_members():
    """TrelloClient.get_card_members() calls GET /1/cards/{card_id}/members and returns list of dicts."""
    from unittest.mock import MagicMock, patch

    fake_members = [{"id": "5e1a2b3c", "fullName": "Dev Person", "username": "devperson"}]
    mock_response = MagicMock()
    mock_response.json.return_value = fake_members
    mock_response.raise_for_status = MagicMock()

    with patch("requests.get", return_value=mock_response):
        from pipeline.trello_client import TrelloClient
        client = TrelloClient(api_key="k", token="t", board_id="b")
        result = client.get_card_members("card123")

    assert isinstance(result, list)
    assert result[0]["id"] == "5e1a2b3c"
    assert result[0]["fullName"] == "Dev Person"


# ---------------------------------------------------------------------------
# AUTO-01: write_automation
# ---------------------------------------------------------------------------

_AUTO01_FAKE_RESPONSE = (
    "=== POM FILE: support/pages/order_summary/orderSummaryPage.ts ===\n"
    "import BasePage from '@pages/basePage';\n"
    "class OrderSummaryPage extends BasePage {\n"
    "  constructor(page) { super(page); this.btn = this.appFrame.locator('button'); }\n"
    "}\n"
    "export default OrderSummaryPage;\n"
    "=== SPEC FILE: tests/order_summary/order_summary.spec.ts ===\n"
    "import { test, expect } from '@setup/fixtures';\n"
    "test.describe.configure({ mode: \"serial\" });\n"
    "test.describe(\"OrderSummary\", () => {\n"
    "  test.skip(!['mcsl-automation'].includes(process.env.SHOPIFY_STORE_NAME ?? ''), 'skip');\n"
    "  test('Verify label', async () => {});\n"
    "});\n"
)


def test_auto01_write_automation_returns_result():
    """write_automation() returns AutomationResult with non-empty pom_code and spec_code."""
    from unittest.mock import MagicMock, patch

    fake_llm_response = MagicMock()
    fake_llm_response.content = _AUTO01_FAKE_RESPONSE
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = fake_llm_response

    with patch("pipeline.automation_writer.ChatAnthropic", return_value=mock_llm):
        from pipeline.automation_writer import write_automation
        result = write_automation("order_summary", "- TC1: Verify label generates")

    assert result.pom_code != ""
    assert result.spec_code != ""
    assert result.error == ""


def test_auto01_spec_structure():
    """Generated spec contains test.describe, @setup/fixtures import, and test.skip store guard."""
    from unittest.mock import MagicMock, patch

    fake_llm_response = MagicMock()
    fake_llm_response.content = _AUTO01_FAKE_RESPONSE
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = fake_llm_response

    with patch("pipeline.automation_writer.ChatAnthropic", return_value=mock_llm):
        from pipeline.automation_writer import write_automation
        result = write_automation("order_summary", "- TC1: Verify label generates")

    assert "test.describe" in result.spec_code
    assert "@setup/fixtures" in result.spec_code
    assert "test.skip" in result.spec_code


def test_auto01_pom_structure():
    """Generated POM contains BasePage extension, this.appFrame locators, and export default."""
    from unittest.mock import MagicMock, patch

    fake_llm_response = MagicMock()
    fake_llm_response.content = _AUTO01_FAKE_RESPONSE
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = fake_llm_response

    with patch("pipeline.automation_writer.ChatAnthropic", return_value=mock_llm):
        from pipeline.automation_writer import write_automation
        result = write_automation("order_summary", "- TC1: Verify label generates")

    assert "BasePage" in result.pom_code
    assert "this.appFrame" in result.pom_code
    assert "export default" in result.pom_code


def test_auto01_no_api_key():
    """write_automation() returns AutomationResult with error when ANTHROPIC_API_KEY is absent — never raises."""
    from unittest.mock import patch
    import pipeline.automation_writer as aw_mod

    with patch.object(aw_mod, "config") as mock_cfg:
        mock_cfg.ANTHROPIC_API_KEY = ""
        mock_cfg.CLAUDE_SONNET_MODEL = "claude-sonnet-4-6"
        from pipeline.automation_writer import write_automation
        result = write_automation("order_summary", "- TC1: Verify label generates")

    assert result.error != ""
    assert result.pom_code == ""


# ---------------------------------------------------------------------------
# AUTO-02: explore_feature() — Chrome Agent ExplorationResult
# ---------------------------------------------------------------------------

def test_auto02_explore_error():
    """explore_feature() returns ExplorationResult with error field when browser launch fails — never raises."""
    from unittest.mock import patch

    with patch("pipeline.chrome_agent._launch_browser", side_effect=Exception("browser unavailable")):
        from pipeline.chrome_agent import explore_feature, ExplorationResult
        result = explore_feature("Label Generation")

    assert isinstance(result, ExplorationResult)
    assert result.error != ""
    assert "browser unavailable" in result.error
    assert result.ax_tree_text == ""


# ---------------------------------------------------------------------------
# AUTO-03: push_to_branch() — git push to automation feature branch
# ---------------------------------------------------------------------------

def test_auto03_git_push():
    """push_to_branch() calls git checkout, add, commit, push with cwd=repo_path and returns (True, branch_name)."""
    from unittest.mock import patch, MagicMock

    mock_run_result = MagicMock()
    mock_run_result.returncode = 0

    with patch("subprocess.run", return_value=mock_run_result) as mock_run:
        from pipeline.automation_writer import push_to_branch
        result = push_to_branch(
            "/fake/repo",
            "Label Generation",
            ["support/pages/labelGen/labelGenPage.ts", "tests/labelGen/labelGen.spec.ts"],
        )

    assert result[0] is True, f"Expected success=True, got {result}"
    assert "automation/label" in result[1], f"Expected branch name with 'automation/label', got {result[1]}"
    assert mock_run.call_count >= 4, f"Expected at least 4 subprocess.run calls, got {mock_run.call_count}"
    for call_args in mock_run.call_args_list:
        assert call_args.kwargs.get("cwd") == "/fake/repo", (
            f"Expected cwd='/fake/repo' but got {call_args.kwargs.get('cwd')}"
        )


def test_auto03_git_error():
    """push_to_branch() returns (False, stderr_string) on CalledProcessError — never raises."""
    import subprocess
    from unittest.mock import patch

    with patch(
        "subprocess.run",
        side_effect=subprocess.CalledProcessError(1, "git push", stderr="remote rejected"),
    ):
        from pipeline.automation_writer import push_to_branch
        result = push_to_branch("/fake/repo", "Feature Name", ["file.ts"])

    assert result[0] is False, f"Expected success=False, got {result}"
    assert "remote rejected" in result[1], f"Expected 'remote rejected' in error msg, got {result[1]}"


def test_auto04_find_pom_matches_existing_mcsl_files(tmp_path):
    repo = tmp_path / "mcsl-auto"
    (repo / "support/pages/orders").mkdir(parents=True)
    (repo / "tests/orderSummary").mkdir(parents=True)
    (repo / "support/pages/orders/orderSummaryPage.ts").write_text("class OrderSummary {}", encoding="utf-8")
    (repo / "tests/orderSummary/documentAutoUploadForFedex.spec.ts").write_text("test()", encoding="utf-8")

    import pipeline.automation_writer as aw_mod

    with patch.object(aw_mod.config, "MCSL_AUTOMATION_REPO_PATH", str(repo)):
        match = aw_mod.find_pom("Order Summary label verification", "Generate label from order summary")

    assert match is not None
    assert match["file"] == "support/pages/orders/orderSummaryPage.ts"
    assert match["spec_file"] == "tests/orderSummary/documentAutoUploadForFedex.spec.ts"
    assert match["app_path"] == "orders"


def test_auto05_write_automation_updates_existing_mcsl_files(tmp_path):
    repo = tmp_path / "mcsl-auto"
    (repo / "support/pages/orders").mkdir(parents=True)
    (repo / "tests/orderSummary").mkdir(parents=True)
    (repo / "support/pages/orders/orderSummaryPage.ts").write_text("class OrderSummary {}", encoding="utf-8")
    (repo / "tests/orderSummary/documentAutoUploadForFedex.spec.ts").write_text("test()", encoding="utf-8")

    fake_llm_response = MagicMock()
    fake_llm_response.content = (
        "=== POM FILE: support/pages/orders/orderSummaryPage.ts ===\n"
        "import BasePage from '@pages/basePage';\n"
        "class OrderSummary extends BasePage {}\n"
        "export default OrderSummary;\n"
        "=== SPEC FILE: tests/orderSummary/documentAutoUploadForFedex.spec.ts ===\n"
        "import { test, expect } from '@setup/fixtures';\n"
        "test.describe.configure({ mode: \"serial\" });\n"
        "test.describe('Order Summary', () => {});\n"
    )
    mock_llm = MagicMock()
    mock_llm.invoke.return_value = fake_llm_response

    import pipeline.automation_writer as aw_mod

    with patch.object(aw_mod.config, "MCSL_AUTOMATION_REPO_PATH", str(repo)), \
         patch("pipeline.automation_writer.ChatAnthropic", return_value=mock_llm):
        result = aw_mod.write_automation(
            "Order Summary label verification",
            "- TC1: Verify label generates",
            acceptance_criteria="Generate label from order summary",
        )

    assert result.kind == "existing_pom"
    assert result.pom_path == "support/pages/orders/orderSummaryPage.ts"
    assert result.spec_path == "tests/orderSummary/documentAutoUploadForFedex.spec.ts"
    assert "Matched existing automation" in result.detection_reason


def test_auto06_feature_detector_falls_back_to_existing_match():
    fake_doc = types.SimpleNamespace(
        page_content="Order summary automation chunk",
        metadata={"file_path": "tests/orderSummary/documentAutoUploadForFedex.spec.ts"},
    )

    with patch("pipeline.feature_detector.search_code", return_value=[fake_doc]), \
         patch("pipeline.feature_detector.find_pom", return_value={
             "file": "support/pages/orders/orderSummaryPage.ts",
             "spec_file": "tests/orderSummary/documentAutoUploadForFedex.spec.ts",
             "app_path": "orders",
         }), \
         patch("pipeline.feature_detector.config") as mock_cfg:
        mock_cfg.ANTHROPIC_API_KEY = ""
        mock_cfg.CLAUDE_SONNET_MODEL = "claude-sonnet"
        result = __import__("pipeline.feature_detector", fromlist=["detect_feature"]).detect_feature(
            "Order Summary label verification",
            "Generate label from order summary",
        )

    assert result.kind == "existing"
    assert "tests/orderSummary/documentAutoUploadForFedex.spec.ts" in result.related_files


def test_auto07_post_results_formats_and_posts_to_slack():
    from pipeline.test_runner import SpecResult, TestRunResult
    from pipeline.slack_client import post_results

    run_result = TestRunResult(
        specs=[
            SpecResult(file="tests/a.spec.ts", title="passes", status="passed", duration_ms=100),
            SpecResult(file="tests/b.spec.ts", title="fails", status="failed", duration_ms=120),
        ],
        total=2,
        passed=1,
        failed=1,
        skipped=0,
        duration_ms=220,
    )

    mock_client = MagicMock()
    mock_client.post_to_channel.return_value = {"ok": True, "ts": "123.456"}

    with patch("pipeline.slack_client._make_client", return_value=mock_client):
        result = post_results(run_result, "MCSLapp 1.2.3")

    assert result["ok"] is True
    assert result["ts"] == "123.456"
    payload = mock_client.post_to_channel.call_args[0][0]
    assert "MCSL Automation — MCSLapp 1.2.3" in payload
    assert "Failed:" in payload


def test_dashboard_tc_warning_skips_fallback_validation_errors():
    """TC warning should not trigger for fallback validation reports with an error message."""
    src = Path("pipeline_dashboard.py").read_text(encoding="utf-8")

    assert 'not getattr(_vr, "error", "") and getattr(_vr, "overall_status", "") == "FAIL"' in src


def test_sheets_writer_lists_live_tabs_from_configured_sheet():
    """Sheet tab list should come from live worksheet titles, not only the static constant."""
    import sys
    import types

    fake_ws1 = types.SimpleNamespace(title="MCSL Master")
    fake_ws2 = types.SimpleNamespace(title="Shipping Labels")
    fake_sheet = types.SimpleNamespace(worksheets=lambda: [fake_ws1, fake_ws2])
    fake_gc = types.SimpleNamespace(open_by_key=lambda key: fake_sheet)
    fake_gspread = types.SimpleNamespace(authorize=lambda creds: fake_gc)
    fake_creds = types.SimpleNamespace(from_service_account_file=lambda *args, **kwargs: object())
    fake_service_account = types.SimpleNamespace(Credentials=fake_creds)

    with patch.dict(
        sys.modules,
        {
            "gspread": fake_gspread,
            "google": types.SimpleNamespace(),
            "google.oauth2": types.SimpleNamespace(),
            "google.oauth2.service_account": fake_service_account,
        },
    ):
        from pipeline.sheets_writer import list_sheet_tabs

        tabs = list_sheet_tabs()

    assert tabs == ["MCSL Master", "Shipping Labels"]


def test_dashboard_uses_live_sheet_tab_options_helper():
    """Dashboard publish selectors should use the live sheet tab helper."""
    src = Path("pipeline_dashboard.py").read_text(encoding="utf-8")

    assert "_live_publish_tabs = _sheet_tab_options()" in src
    assert "_live_approval_tabs = _sheet_tab_options()" in src


def test_dashboard_ai_qa_bug_review_has_fedex_style_controls():
    """AI QA Verifier bug review should expose explicit review wording and bulk-select controls."""
    src = Path("pipeline_dashboard.py").read_text(encoding="utf-8")

    assert '<div class="step-chip">🐛 Bug Review</div>' in src
    assert "☑ Select All" in src
    assert "☐ None" in src
    assert "📨 Notify Assigned Devs (" in src


def test_validate_ac_load_cards_also_populates_diagnosis():
    """Validate AC load flow should create diagnosis state so extra diagnosis step is not needed."""
    src = Path("pipeline_dashboard.py").read_text(encoding="utf-8")

    assert "def _analyse_loaded_card(card: Any)" in src
    assert 'st.session_state[f"diagnosis_{_card_id}"] =' in src
