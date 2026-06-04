"""Magazyn wielu rozmów (konwersacji) czatu.

Każda rozmowa: {id, title, created, messages:[{role, content}]}.
Treść (content) zapisywana jest jako TEKST (bez base64 obrazów), by plik był lekki.
Aktywna rozmowa wskazywana przez 'active'.
"""

import json
import logging
import time
import uuid

from config import CHATS_FILE, atomic_write_text, load_json_or_backup

log = logging.getLogger(__name__)


class ChatStore:
    def __init__(self):
        self.data = {"active": None, "chats": []}
        self._load()
        if not self.data.get("chats"):
            self.new_chat()
        if not self.data.get("active") or not self._find(self.data["active"]):
            self.data["active"] = self.data["chats"][0]["id"]
            self._save()

    # --- trwałość ---
    def _load(self):
        # P1-11: korupcja → backup .corrupt + start od zera (wspólny loader).
        loaded = load_json_or_backup(CHATS_FILE, None)
        if isinstance(loaded, dict) and isinstance(loaded.get("chats"), list):
            self.data = loaded

    def _save(self):
        try:
            atomic_write_text(CHATS_FILE, json.dumps(self.data, ensure_ascii=False, indent=2))
        except Exception:
            log.exception("Failed to save %s", CHATS_FILE.name)

    def _find(self, cid):
        for c in self.data["chats"]:
            if c["id"] == cid:
                return c
        return None

    # --- operacje na rozmowach ---
    def new_chat(self, title="New chat"):
        chat = {"id": uuid.uuid4().hex, "title": title,
                "created": int(time.time()), "messages": []}
        self.data["chats"].insert(0, chat)
        self.data["active"] = chat["id"]
        self._save()
        return chat

    def delete(self, cid):
        self.data["chats"] = [c for c in self.data["chats"] if c["id"] != cid]
        if not self.data["chats"]:
            self.new_chat()
        if self.data["active"] == cid:
            self.data["active"] = self.data["chats"][0]["id"]
        self._save()

    def rename(self, cid, title):
        c = self._find(cid)
        if c:
            c["title"] = title.strip() or c["title"]
            self._save()

    def set_active(self, cid):
        if self._find(cid):
            self.data["active"] = cid
            self._save()

    def active_id(self):
        return self.data.get("active")

    def list(self):
        return self.data["chats"]

    def get_active(self):
        return self._find(self.data.get("active")) or (self.data["chats"][0] if self.data["chats"] else None)

    def messages(self):
        c = self.get_active()
        return c["messages"] if c else []

    # --- wiadomości ---
    def add_message(self, role, text):
        c = self.get_active()
        if not c:
            return
        c["messages"].append({"role": role, "content": text})
        # auto-tytuł z pierwszej wiadomości użytkownika
        if role == "user" and c["title"] == "New chat":
            t = (text or "").strip().replace("\n", " ")
            if t:
                c["title"] = (t[:34] + "…") if len(t) > 34 else t
        self._save()

    def set_messages(self, msgs):
        """Zastępuje wiadomości aktywnej rozmowy (tekstowa kopia stanu live)."""
        c = self.get_active()
        if c is not None:
            c["messages"] = msgs
            self._save()

    def clear_active(self):
        c = self.get_active()
        if c is not None:
            c["messages"] = []
            c["title"] = "New chat"
            self._save()
