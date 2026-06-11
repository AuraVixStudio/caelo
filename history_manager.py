import json
import logging
import threading
from datetime import datetime
from config import CONFIG_FILE, HISTORY_DIR, atomic_write_text, load_json_or_backup

log = logging.getLogger(__name__)

class HistoryManager:
    def __init__(self):
        # S31-m: jeden lock serializuje read-modify-write. Instancja jest WSPÓŁDZIELONA
        # (Backend.history) i wołana z wątków-workerów genjobs (save_media_urls) ORAZ
        # czatu/voice — bez locka równoległe append+_persist gubiły wpisy (atomic_write_text
        # czyni sam zapis atomowym, ale NIE serializuje sekwencji RMW).
        self._lock = threading.RLock()
        self.save_path = str(HISTORY_DIR)
        self.history = []
        self.chat_history = []
        self.load_settings()

    def load_settings(self):
        # P1-11: korupcja → backup .corrupt + wartości domyślne (wspólny loader).
        with self._lock:
            data = load_json_or_backup(CONFIG_FILE, None)
            if isinstance(data, dict):
                self.history = data.get("history", [])
                self.chat_history = data.get("chat_history", [])
                self.save_path = data.get("save_path", str(HISTORY_DIR))

    def save_to_history(self, mode, url, prompt):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "prompt": prompt[:150] + "..." if len(prompt) > 150 else prompt,
            "url": url
        }
        with self._lock:
            self.history.append(entry)
            self._persist()

    def _persist(self):
        # Wywoływane TYLKO trzymając self._lock (przez metody publiczne).
        data = {
            "history": self.history[-500:],
            "chat_history": self.chat_history[-100:],
            "save_path": self.save_path
        }
        atomic_write_text(CONFIG_FILE, json.dumps(data, ensure_ascii=False, indent=2))

    def set_save_path(self, path):
        with self._lock:
            self.save_path = path
            self._persist()

    def get_save_path(self):
        return self.save_path

    def save_chat_message(self, role, content):
        with self._lock:
            self.chat_history.append({"role": role, "content": content})
            self._persist()

    def get_chat_history(self):
        return self.chat_history

    def clear_chat_history(self):
        with self._lock:
            self.chat_history = []
            self._persist()

    def get_entries(self):
        return reversed(self.history)
