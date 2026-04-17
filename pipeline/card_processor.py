"""card_processor.py — Trello card AC text extractor.

Contract: get_ac_text(trello_card_url: str) -> tuple[str, str]
Returns (card_name, ac_text). Returns ("", "") on any failure or missing credentials.
"""
from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

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
