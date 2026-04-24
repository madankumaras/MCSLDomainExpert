"""
pipeline/sheets_writer.py — Google Sheets writer for MCSL test case data.
Phase 07 Plan 02 — RQA-04

Exports: append_to_sheet, detect_tab, check_duplicates, create_new_tab, create_release_sheet, list_sheet_tabs, TestCaseRow, DuplicateMatch, SHEET_TABS, TAB_KEYWORDS

NOTE: gspread is imported INSIDE append_to_sheet() and check_duplicates() — NOT at module top —
so this module can be imported without gspread installed.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import config


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SHEET_TABS = [
    "Shipping Labels",
    "Rate Calculation",
    "Tracking",
    "Returns",
    "Additional Services",
    "Settings & Config",
    "Order Management",
    "Draft Plan",
]

TAB_KEYWORDS = {
    "Shipping Labels": ["label", "generate label", "print label", "bulk label"],
    "Rate Calculation": ["rate", "quote", "pricing", "shipping cost"],
    "Tracking": ["track", "tracking", "shipment status"],
    "Returns": ["return", "return label", "rma"],
    "Additional Services": ["signature", "dry ice", "alcohol", "battery", "hal", "insurance"],
    "Settings & Config": ["setting", "config", "carrier account", "api key", "credential"],
    "Order Management": ["order", "fulfillment", "sync"],
}


def list_sheet_tabs() -> list[str]:
    """Return live worksheet titles from the configured Google Sheet."""
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(config.GOOGLE_SHEETS_ID)
    return [ws.title for ws in sh.worksheets()]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TestCaseRow:
    si_no: int = 0
    epic: str = ""
    scenario: str = ""
    description: str = ""
    comments: str = ""
    priority: str = "Medium"
    details: str = ""
    pass_fail: str = ""
    release: str = ""


@dataclass
class DuplicateMatch:
    existing_scenario: str
    new_scenario: str
    similarity: float


# ---------------------------------------------------------------------------
# detect_tab
# ---------------------------------------------------------------------------

def detect_tab(card_name: str, test_cases_markdown: str) -> str:
    """Match card/TC text to SHEET_TABS using keyword lookup. Falls back to 'Draft Plan'."""
    combined = f"{card_name} {test_cases_markdown}".lower()
    for tab, keywords in TAB_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return tab
    return "Draft Plan"


# ---------------------------------------------------------------------------
# parse_test_cases_to_rows (local implementation — parallel with card_processor.py)
# ---------------------------------------------------------------------------

def parse_test_cases_to_rows(
    card_name: str,
    test_cases_markdown: str,
    epic: str = "",
    positive_only: bool = False,
) -> list[TestCaseRow]:
    rows = []
    tc_blocks = re.split(r"(?=^#{2,3}\s+TC-\d+)", test_cases_markdown, flags=re.MULTILINE)
    si = 1
    for block in tc_blocks:
        block = block.strip()
        if not block or not re.match(r"^#{2,3}\s+TC-\d+", block):
            continue
        title_match = re.match(r"^#{2,3}\s+TC-\d+[:\s]+(.+)", block)
        scenario = title_match.group(1).strip() if title_match else card_name
        tc_type = "Positive"
        priority = "Medium"
        type_match = re.search(r"\*\*Type:\*\*\s*(.+)", block)
        if type_match:
            tc_type = type_match.group(1).strip()
        priority_match = re.search(r"\*\*Priority:\*\*\s*(.+)", block)
        if priority_match:
            priority = priority_match.group(1).strip()
        if positive_only and "positive" not in tc_type.lower():
            continue
        preconditions_match = re.search(r"\*\*Preconditions?:\*\*\s*(.+?)(?:\n|$)", block, re.IGNORECASE)
        comments = preconditions_match.group(1).strip() if preconditions_match else ""
        gwt_parts = []
        in_steps = False
        for line in block.splitlines():
            stripped = line.strip()
            if re.match(r"\*\*Steps:\*\*", stripped, re.IGNORECASE):
                in_steps = True
                continue
            if in_steps and re.match(r"\*\*.+\*\*", stripped) and not re.match(
                r"^(Given|When|And|Then|But)\b", stripped, re.IGNORECASE
            ):
                break
            if re.match(r"^(Given|When|And|Then|But)\b", stripped, re.IGNORECASE):
                gwt_parts.append(stripped)
                in_steps = True
        description = "\n".join(gwt_parts) if gwt_parts else block[:200]
        rows.append(
            TestCaseRow(
                si_no=si,
                epic=epic or card_name,
                scenario=scenario,
                description=description,
                comments=comments,
                priority=priority,
            )
        )
        si += 1
    return rows


# ---------------------------------------------------------------------------
# check_duplicates
# ---------------------------------------------------------------------------

def check_duplicates(
    new_rows: list[TestCaseRow],
    tab_name: str,
    similarity_threshold: float = 0.75,
) -> list[DuplicateMatch]:
    """Check new rows against existing sheet rows for near-duplicates using SequenceMatcher."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_PATH, scopes=scopes)
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(config.GOOGLE_SHEETS_ID)
        # Find matching tab (partial match)
        ws = None
        for worksheet in sh.worksheets():
            if tab_name.lower() in worksheet.title.lower():
                ws = worksheet
                break
        if ws is None:
            return []
        existing_values = ws.get_all_values()
        existing_scenarios = [row[2] for row in existing_values[1:] if len(row) > 2 and row[2]]
    except Exception as exc:
        logging.warning("check_duplicates failed to fetch sheet: %s", exc)
        return []

    duplicates = []
    for new_row in new_rows:
        for existing_scenario in existing_scenarios:
            ratio = SequenceMatcher(None, new_row.scenario.lower(), existing_scenario.lower()).ratio()
            if ratio >= similarity_threshold:
                duplicates.append(
                    DuplicateMatch(
                        existing_scenario=existing_scenario,
                        new_scenario=new_row.scenario,
                        similarity=ratio,
                    )
                )
    return duplicates


# ---------------------------------------------------------------------------
# create_new_tab
# ---------------------------------------------------------------------------

def create_new_tab(tab_name: str) -> dict:
    """Create a new worksheet tab if it does not already exist."""
    import gspread
    from google.oauth2.service_account import Credentials

    clean_name = (tab_name or "").strip()
    if not clean_name:
        raise ValueError("Tab name cannot be empty.")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(config.GOOGLE_SHEETS_ID)

    existing_titles = [ws.title for ws in sh.worksheets()]
    for title in existing_titles:
        if title.lower() == clean_name.lower():
            return {
                "ok": True,
                "created": False,
                "tab": title,
                "sheet_url": f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEETS_ID}",
                "reason": "already_exists",
                "error": "",
            }

    ws = sh.add_worksheet(title=clean_name[:100], rows=200, cols=9)
    ws.append_row([
        "SI No",
        "Epic",
        "Scenario",
        "Description",
        "Comments",
        "Priority",
        "Details",
        "Pass/Fail",
        "Release",
    ])
    return {
        "ok": True,
        "created": True,
        "tab": ws.title,
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEETS_ID}",
        "reason": "",
        "error": "",
    }


RELEASE_SHEET_HEADERS = [
    "Card Name",
    "Ticket",
    "Toggle /other info",
    "Card URL",
    "Card Description",
    "API",
    "List Name",
]

_JIRA_RE = re.compile(r"\b([A-Z]{2,10}-\d+)\b")
_REST_RE = re.compile(r"\b(rest api|restful|rest)\b", re.IGNORECASE)
_SOAP_RE = re.compile(r"\bsoap\b", re.IGNORECASE)


def _extract_ticket(desc: str, labels: list[str]) -> str:
    combined = " ".join(labels or []) + " " + (desc or "")
    m = _JIRA_RE.search(combined)
    return m.group(1) if m else "NO ticket attached"


def _extract_toggle_info(desc: str, labels: list[str]) -> str:
    combined = (" ".join(labels or []) + " " + (desc or "")).lower()
    return "Toggle available" if "toggle" in combined else ""


def _extract_api_type(desc: str, labels: list[str]) -> str:
    combined = " ".join(labels or []) + " " + (desc or "")
    if _REST_RE.search(combined):
        return "REST"
    if _SOAP_RE.search(combined):
        return "SOAP"
    return "N/A"


def create_release_sheet(
    release_name: str,
    cards: list,
    list_name: str = "",
    bugs_by_card: dict | None = None,
) -> dict:
    import gspread
    from google.oauth2.service_account import Credentials

    bugs_by_card = bugs_by_card or {}
    tab_name = re.sub(r"[\\/*?\[\]:]", "-", (release_name or "").strip())[:100]
    if not tab_name:
        raise ValueError("Release name cannot be empty.")

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(config.GOOGLE_SHEETS_ID)

    existing_titles = [ws.title for ws in sh.worksheets()]
    created = tab_name not in existing_titles
    if created:
        ws = sh.add_worksheet(title=tab_name, rows=max(len(cards) + 10, 50), cols=len(RELEASE_SHEET_HEADERS))
    else:
        ws = sh.worksheet(tab_name)
        ws.clear()

    ws.append_row(RELEASE_SHEET_HEADERS, value_input_option="USER_ENTERED")
    try:
        sh.batch_update({"requests": [{"repeatCell": {
            "range": {"sheetId": ws.id, "startRowIndex": 0, "endRowIndex": 1, "startColumnIndex": 0, "endColumnIndex": len(RELEASE_SHEET_HEADERS)},
            "cell": {"userEnteredFormat": {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.27, "green": 0.51, "blue": 0.71}}},
            "fields": "userEnteredFormat(textFormat,backgroundColor)"
        }}]})
    except Exception:
        pass

    rows_to_write = []
    for card in cards:
        desc = getattr(card, "desc", "") or ""
        labels = getattr(card, "labels", []) or []
        bugs = bugs_by_card.get(getattr(card, "id", ""), [])
        if bugs:
            ticket_cell = "\n".join(f"{b.get('severity', 'Bug')} - {b.get('name', '')}" for b in bugs if b.get("name"))
        else:
            ticket_cell = _extract_ticket(desc, labels)
        rows_to_write.append([
            getattr(card, "name", ""),
            ticket_cell or "NO ticket attached",
            _extract_toggle_info(desc, labels),
            getattr(card, "url", "") or "",
            desc,
            _extract_api_type(desc, labels),
            list_name or getattr(card, "list_name", ""),
        ])
    if rows_to_write:
        ws.append_rows(rows_to_write, value_input_option="USER_ENTERED")

    return {
        "tab": tab_name,
        "rows_added": len(rows_to_write),
        "sheet_url": f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEETS_ID}/edit#gid={ws.id}",
        "created": created,
    }


# ---------------------------------------------------------------------------
# append_to_sheet
# ---------------------------------------------------------------------------

def append_to_sheet(
    card_name: str,
    test_cases_markdown: str,
    epic: str = "",
    tab_name: str | None = None,
    release: str = "",
    card_url: str = "",
) -> dict:
    """Parse TCs and append to the correct MCSL master sheet tab. Returns metadata dict.

    Inserts a coloured card-header row before each card's TC rows so the sheet
    groups test cases visually under their source card (with a Trello link).

    gspread is imported INSIDE this function so callers can import sheets_writer
    without gspread installed.
    """
    import gspread
    from google.oauth2.service_account import Credentials

    target_tab = tab_name or detect_tab(card_name, test_cases_markdown)
    rows = parse_test_cases_to_rows(card_name, test_cases_markdown, epic=epic, positive_only=True)
    if not rows:
        return {"tab": target_tab, "rows_added": 0, "sheet_url": "", "release": release, "duplicates": []}

    for row in rows:
        row.release = release

    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    creds = Credentials.from_service_account_file(config.GOOGLE_CREDENTIALS_PATH, scopes=scopes)
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(config.GOOGLE_SHEETS_ID)

    ws = None
    ws_titles = [w.title for w in sh.worksheets()]
    for title in ws_titles:
        if target_tab.lower() in title.lower() or title.lower() in target_tab.lower():
            ws = sh.worksheet(title)
            target_tab = title
            break
    if ws is None:
        for title in ws_titles:
            if "draft" in title.lower():
                ws = sh.worksheet(title)
                target_tab = title
                break
    if ws is None:
        raise ValueError(f"Sheet tab '{target_tab}' not found in {ws_titles}")

    existing = ws.get_all_values()
    next_si = len(existing)

    duplicates = check_duplicates(rows, target_tab)

    # ── Card header row ──────────────────────────────────────────────────────
    # One coloured row per card: card name (hyperlinked when URL available) +
    # release label so the group is easy to spot at a glance.
    if card_url:
        header_cell = f'=HYPERLINK("{card_url}","{card_name.replace(chr(34), chr(39))}")'
    else:
        header_cell = card_name
    release_label = f"Release: {release}" if release else ""
    num_cols = 9
    header_row = [header_cell, release_label] + [""] * (num_cols - 2)
    ws.append_row(header_row, value_input_option="USER_ENTERED")

    # Colour the header row golden-yellow (#FFD966)
    header_row_index = next_si  # 0-based
    try:
        sh.batch_update({"requests": [{"repeatCell": {
            "range": {
                "sheetId": ws.id,
                "startRowIndex": header_row_index,
                "endRowIndex": header_row_index + 1,
                "startColumnIndex": 0,
                "endColumnIndex": num_cols,
            },
            "cell": {"userEnteredFormat": {
                "backgroundColor": {"red": 1.0, "green": 0.851, "blue": 0.4},
                "textFormat": {"bold": True},
            }},
            "fields": "userEnteredFormat(backgroundColor,textFormat)",
        }}]})
    except Exception:
        pass  # colour is cosmetic — don't fail the whole write

    next_si += 1

    # ── TC rows ──────────────────────────────────────────────────────────────
    for row in rows:
        row.si_no = next_si
        ws.append_row([
            row.si_no,
            row.epic,
            row.scenario,
            row.description,
            row.comments,
            row.priority,
            row.details,
            row.pass_fail,
            row.release,
        ])
        next_si += 1

    sheet_url = f"https://docs.google.com/spreadsheets/d/{config.GOOGLE_SHEETS_ID}"
    return {
        "tab": target_tab,
        "rows_added": len(rows),
        "sheet_url": sheet_url,
        "release": release,
        "duplicates": duplicates,
    }
