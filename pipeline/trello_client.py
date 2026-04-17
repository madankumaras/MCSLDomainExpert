"""
pipeline/trello_client.py — Trello REST API wrapper for MCSL QA Pipeline.

Exports: TrelloClient, TrelloCard, TrelloList
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any

import requests

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class TrelloList:
    id: str
    name: str
    pos: float = 0.0


@dataclass
class TrelloCard:
    id: str
    name: str
    desc: str = ""
    url: str = ""
    list_id: str = ""
    member_ids: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    attachments: list[dict] = field(default_factory=list)
    checklists: list[dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# TrelloClient
# ---------------------------------------------------------------------------

class TrelloClient:
    """Minimal Trello REST client using the requests library."""

    BASE = "https://api.trello.com/1"

    def __init__(
        self,
        api_key: str | None = None,
        token: str | None = None,
        board_id: str | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("TRELLO_API_KEY", "")
        self.token = token or os.getenv("TRELLO_TOKEN", "")
        self.board_id = board_id or os.getenv("TRELLO_BOARD_ID", "")
        if not all([self.api_key, self.token, self.board_id]):
            raise ValueError(
                "Trello credentials missing. Set TRELLO_API_KEY, TRELLO_TOKEN, "
                "TRELLO_BOARD_ID in .env"
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @property
    def _auth(self) -> dict:
        return {"key": self.api_key, "token": self.token}

    def _get(self, path: str, **params: Any) -> Any:
        r = requests.get(f"{self.BASE}/{path}", params={**self._auth, **params})
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, **data: Any) -> Any:
        r = requests.post(f"{self.BASE}/{path}", params=self._auth, json=data)
        r.raise_for_status()
        return r.json()

    def _put(self, path: str, **data: Any) -> Any:
        r = requests.put(f"{self.BASE}/{path}", params=self._auth, json=data)
        r.raise_for_status()
        return r.json()

    # ------------------------------------------------------------------
    # Board / list operations
    # ------------------------------------------------------------------

    def get_lists(self) -> list[TrelloList]:
        """Return all lists on the configured board."""
        data = self._get(f"boards/{self.board_id}/lists")
        return [TrelloList(id=l["id"], name=l["name"], pos=l.get("pos", 0.0)) for l in data]

    def get_list_by_name(self, name: str) -> TrelloList | None:
        """Return the first list whose name matches, or None."""
        for lst in self.get_lists():
            if lst.name == name:
                return lst
        return None

    def create_list(self, name: str, pos: str = "bottom") -> TrelloList:
        """Create a new list on the configured board."""
        data = self._post("lists", name=name, idBoard=self.board_id, pos=pos)
        return TrelloList(id=data["id"], name=data["name"], pos=data.get("pos", 0.0))

    # ------------------------------------------------------------------
    # Member operations
    # ------------------------------------------------------------------

    def get_board_members(self) -> list[dict]:
        """Return list of {id, fullName, username} dicts for board members."""
        data = self._get(f"boards/{self.board_id}/members")
        return [{"id": m["id"], "fullName": m.get("fullName", ""), "username": m.get("username", "")} for m in data]

    # ------------------------------------------------------------------
    # Card operations
    # ------------------------------------------------------------------

    def get_cards_in_list(self, list_id: str) -> list[TrelloCard]:
        """Return all cards in the given list."""
        data = self._get(f"lists/{list_id}/cards")
        return [
            TrelloCard(
                id=c["id"],
                name=c.get("name", ""),
                desc=c.get("desc", ""),
                url=c.get("url", ""),
                list_id=c.get("idList", list_id),
                member_ids=c.get("idMembers", []),
            )
            for c in data
        ]

    def create_card_in_list(
        self,
        list_id: str,
        name: str,
        desc: str = "",
        member_ids: list[str] | None = None,
        list_name: str = "",
    ) -> TrelloCard:
        """Create a card in the specified list and return a TrelloCard."""
        data = self._post(
            "cards",
            idList=list_id,
            name=name,
            desc=desc,
            idMembers=member_ids or [],
        )
        return TrelloCard(
            id=data["id"],
            name=data.get("name", name),
            desc=data.get("desc", desc),
            url=data.get("url", ""),
            list_id=data.get("idList", list_id),
            member_ids=data.get("idMembers", []),
        )

    def move_card_to_list(self, card_id: str, list_name: str) -> None:
        """Move a card to a list identified by name (performs name lookup)."""
        lst = self.get_list_by_name(list_name)
        if lst is None:
            raise ValueError(f"List named {list_name!r} not found on board {self.board_id!r}")
        self._put(f"cards/{card_id}", idList=lst.id)
        logger.info("Moved card %s to list %s (%s)", card_id, list_name, lst.id)

    def move_card_to_list_by_id(self, card_id: str, list_id: str) -> dict:
        """Move a card directly to a list by list ID — no name lookup performed.

        Calls PUT /1/cards/{card_id} with idList=list_id.
        This is the MCSL-safe variant that avoids stale-name resolution errors.
        """
        result = self._put(f"cards/{card_id}", idList=list_id)
        logger.info("Moved card %s to list %s (by id)", card_id, list_id)
        return result

    def add_comment(self, card_id: str, text: str) -> dict:
        """Post an audit comment to a card."""
        return self._post(f"cards/{card_id}/actions/comments", text=text)

    def update_card_description(self, card_id: str, new_desc: str) -> dict:
        """Update the description of a card."""
        return self._put(f"cards/{card_id}", desc=new_desc)

    def get_card_comments(self, card_id: str) -> list[str]:
        """Fetch comment text from a card. Returns list of comment strings (newest first)."""
        actions = self._get(f"cards/{card_id}/actions", filter="commentCard")
        return [
            a["data"]["text"]
            for a in actions
            if a.get("type") == "commentCard" and "data" in a and "text" in a["data"]
        ]
