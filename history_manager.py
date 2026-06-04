import json
import logging
from datetime import datetime
from config import CONFIG_FILE, HISTORY_DIR, atomic_write_text

log = logging.getLogger(__name__)

class HistoryManager:
    def __init__(self):
        self.save_path = str(HISTORY_DIR)
        self.history = []
        self.chat_history = []
        self.load_settings()

    def load_settings(self):
        if CONFIG_FILE.exists():
            try:
                data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
                self.history = data.get("history", [])
                self.chat_history = data.get("chat_history", [])
                self.save_path = data.get("save_path", str(HISTORY_DIR))
            except Exception:
                log.error("Could not load %s (corrupt JSON?)", CONFIG_FILE.name, exc_info=True)

    def save_to_history(self, mode, url, prompt):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "mode": mode,
            "prompt": prompt[:150] + "..." if len(prompt) > 150 else prompt,
            "url": url
        }
        self.history.append(entry)
        self._persist()

    def _persist(self):
        data = {
            "history": self.history[-500:],
            "chat_history": self.chat_history[-100:],
            "save_path": self.save_path
        }
        atomic_write_text(CONFIG_FILE, json.dumps(data, ensure_ascii=False, indent=2))

    def set_save_path(self, path):
        self.save_path = path
        self._persist()

    def get_save_path(self):
        return self.save_path

    def save_chat_message(self, role, content):
        self.chat_history.append({"role": role, "content": content})
        self._persist()

    def get_chat_history(self):
        return self.chat_history

    def clear_chat_history(self):
        self.chat_history = []
        self._persist()

    def get_entries(self):
        return reversed(self.history)
