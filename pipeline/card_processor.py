"""card_processor.py — Trello card AC text extractor + QA test case generation.

Original contract: get_ac_text(trello_card_url: str) -> tuple[str, str]
Returns (card_name, ac_text). Returns ("", "") on any failure or missing credentials.

Extended (07-01): generate_acceptance_criteria, generate_test_cases,
write_test_cases_to_card, format_qa_comment, parse_test_cases_to_rows, TestCaseRow
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field as dc_field
from pathlib import Path

import config
from dotenv import load_dotenv
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import HumanMessage

# Explicit dotenv path — established pattern from Phase 1 config.py
load_dotenv(Path(__file__).parent.parent / ".env")

_TRELLO_API_BASE = "https://api.trello.com/1"


def _extract_card_id(trello_url: str) -> str:
    """Extract the short card ID from a Trello card URL.

    Handles: https://trello.com/c/{card_id}/...  and  https://trello.com/c/{card_id}
    Returns empty string if URL does not match expected pattern.
    """
    match = re.search(r"/c/([^/?#]+)", trello_url)
    return match.group(1) if match else ""


def get_ac_text(trello_card_url: str) -> tuple[str, str]:
    """Fetch card name and AC text from a Trello card URL.

    Returns (card_name, ac_text).
    Returns ("", "") if:
      - TRELLO_API_KEY or TRELLO_TOKEN environment variables are missing
      - The URL does not contain a recognisable card ID
      - The Trello API request fails for any reason
    """
    api_key = os.environ.get("TRELLO_API_KEY", "")
    token   = os.environ.get("TRELLO_TOKEN",   "")

    if not api_key or not token:
        return ("", "")

    card_id = _extract_card_id(trello_card_url)
    if not card_id:
        return ("", "")

    url = f"{_TRELLO_API_BASE}/cards/{card_id}?fields=name,desc&key={api_key}&token={token}"

    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            data: dict = json.loads(resp.read())
        return (data.get("name", ""), data.get("desc", ""))
    except Exception:  # noqa: BLE001
        return ("", "")


# ---------------------------------------------------------------------------
# TestCaseRow dataclass
# ---------------------------------------------------------------------------

@dataclass
class TestCaseRow:
    si_no: int = 0
    epic: str = ""
    scenario: str = ""
    description: str = ""   # Given/When/Then
    comments: str = ""
    priority: str = "Medium"
    details: str = ""
    pass_fail: str = ""
    release: str = ""


# ---------------------------------------------------------------------------
# Prompt constants
# ---------------------------------------------------------------------------

AC_WRITER_PROMPT = """\
You are a senior QA lead for the MCSL (Multi-Carrier Shipping Labels) Shopify App by PluginHive.
The app supports FedEx, UPS, DHL, USPS, and other carriers.
Navigation: ORDERS tab flow, App Settings → Carriers → Add/Edit.
Never write ACs for mobile viewports.

Feature request:
{raw_request}

Attachments context:
{attachments_context}

Checklist context:
{checklists_context}

Additional research context:
{research_context}

Write Acceptance Criteria in this format:
### Acceptance Criteria
- AC1: [specific testable criterion]
- AC2: ...

Each AC must be testable via the MCSL app UI.
"""

TEST_CASE_PROMPT = """\
You are a senior QA engineer for the MCSL (Multi-Carrier Shipping Labels) Shopify App by PluginHive.
The app supports FedEx, UPS, DHL, USPS, and other carriers.
Navigation: ORDERS tab flow, App Settings → Carriers → Add/Edit.

Card Name: {card_name}
Card Description:
{card_desc}

Developer Notes / Comments:
{comments}

Acceptance Criteria:
{ac_text}

Write test cases in this format for each scenario:
## TC-{{n}}: {{scenario title}}
**Type:** Positive | Negative | Edge Case
**Priority:** High | Medium | Low
Given {{precondition}}
When {{action}}
Then {{expected result}}
"""


# ---------------------------------------------------------------------------
# New functions
# ---------------------------------------------------------------------------

def generate_acceptance_criteria(
    raw_request: str,
    model: str | None = None,
    attachments: list[dict] | None = None,
    checklists: list[dict] | None = None,
    research_context: str | None = None,
) -> str:
    """Generate acceptance criteria for a feature request using Claude."""
    attachments_context = str(attachments) if attachments else "None"
    checklists_context = str(checklists) if checklists else "None"
    prompt = AC_WRITER_PROMPT.format(
        raw_request=raw_request,
        attachments_context=attachments_context,
        checklists_context=checklists_context,
        research_context=research_context or "None",
    )
    llm = ChatAnthropic(
        model=model or config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=2048,
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()


def generate_test_cases(card, model: str | None = None) -> str:
    """Generate test cases for a TrelloCard using Claude.

    card is a TrelloCard — uses card.name, card.desc, card.comments.
    """
    comments_text = "\n".join(card.comments) if getattr(card, "comments", None) else "None"
    # get_ac_text expects a URL string; TrelloCard objects use card.desc as AC source directly
    ac_text_str = card.desc or "(no AC yet)"
    prompt = TEST_CASE_PROMPT.format(
        card_name=card.name,
        card_desc=card.desc or "(no description)",
        comments=comments_text,
        ac_text=ac_text_str,
    )
    llm = ChatAnthropic(
        model=model or config.CLAUDE_SONNET_MODEL,
        api_key=config.ANTHROPIC_API_KEY,
        temperature=0.3,
        max_tokens=2048,
    )
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()


def format_qa_comment(
    card_name: str,
    test_cases_markdown: str,
    release: str = "",
    qa_name: str = "",
) -> str:
    """Format test cases as a QA comment string."""
    parts = ["## MCSL QA Test Cases"]
    if card_name:
        parts.append(f"**Card:** {card_name}")
    if release:
        parts.append(f"**Release:** {release}")
    if qa_name:
        parts.append(f"**QA:** {qa_name}")
    parts.append("")
    parts.append(test_cases_markdown.strip())
    return "\n".join(parts)


def write_test_cases_to_card(
    card_id: str,
    test_cases: str,
    trello,
    release: str = "",
    card_name: str = "",
) -> None:
    """Post formatted test cases as a comment on the Trello card."""
    comment = format_qa_comment(card_name=card_name, test_cases_markdown=test_cases, release=release)
    trello.add_comment(card_id, comment)


def parse_test_cases_to_rows(
    card_name: str,
    test_cases_markdown: str,
    epic: str = "",
    positive_only: bool = False,
) -> list[TestCaseRow]:
    """Parse test case markdown into a list of TestCaseRow objects."""
    rows = []
    # Split by TC blocks: ## TC-N: title
    tc_blocks = re.split(r"(?=^## TC-\d+)", test_cases_markdown, flags=re.MULTILINE)
    si = 1
    for block in tc_blocks:
        block = block.strip()
        if not block or not block.startswith("## TC-"):
            continue
        # Extract scenario title
        title_match = re.match(r"## TC-\d+[:\s]+(.+)", block)
        scenario = title_match.group(1).strip() if title_match else card_name

        # Extract type/priority
        tc_type = "Positive"
        priority = "Medium"
        type_match = re.search(r"\*\*Type:\*\*\s*(.+)", block)
        if type_match:
            tc_type = type_match.group(1).strip()
        priority_match = re.search(r"\*\*Priority:\*\*\s*(.+)", block)
        if priority_match:
            priority = priority_match.group(1).strip()

        if positive_only and "negative" in tc_type.lower():
            continue

        # Extract Given/When/Then as description
        gwt_parts = []
        for keyword in ("Given", "When", "Then"):
            m = re.search(rf"{keyword}\s+(.+?)(?=\n(?:Given|When|Then|##)|$)", block, re.DOTALL | re.IGNORECASE)
            if m:
                gwt_parts.append(f"{keyword} {m.group(1).strip()}")
        description = "\n".join(gwt_parts) if gwt_parts else block[:200]

        rows.append(TestCaseRow(
            si_no=si,
            epic=epic or card_name,
            scenario=scenario,
            description=description,
            priority=priority,
            release="",
        ))
        si += 1
    return rows
