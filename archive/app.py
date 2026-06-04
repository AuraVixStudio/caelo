# --- Legacy fallback (Faza 8) ---------------------------------------------
# Ta aplikacja customtkinter została przeniesiona do archive/, ale współdzielony
# rdzeń (config, api_manager, oauth_manager, chats_manager, history_manager)
# pozostaje w korzeniu repo — reużywa go też backend grok_core. Dokładamy korzeń
# repo do sys.path, aby importy „po nazwie" działały po przenosinach.
import os as _os
import sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
# --------------------------------------------------------------------------
import tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import threading
import json
import webbrowser
import os
import sys
import time
import base64
import io
import re
import requests
from PIL import Image, ImageTk
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from config import (COLORS, FONTS, ASPECT_RATIOS, RESOLUTIONS, VIDEO_RESOLUTIONS,
                    CONFIG_FILE, HISTORY_DIR, SETTINGS_FILE, ICON_FILE,
                    DEFAULT_CHAT_MODELS, DEFAULT_CHAT_MODEL,
                    VIDEO_MODELS, DEFAULT_VIDEO_MODEL, APP_VERSION)
from history_manager import HistoryManager
from api_manager import APIManager
from oauth_manager import OAuthManager
from chats_manager import ChatStore
from ui_utils import download_image, ResultCard

# Opcjonalne wsparcie przeciągnij-i-upuść plików (drag & drop).
# Jeśli tkinterdnd2 nie jest zainstalowane, aplikacja działa normalnie (bez DnD).
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES
    _DND_AVAILABLE = True
except Exception:
    TkinterDnD = None
    DND_FILES = None
    _DND_AVAILABLE = False

load_dotenv()
ctk.set_appearance_mode("Dark")

# --- Narzędzia (function calling) udostępniane modelowi w czacie ---
TOOL_SYSTEM = (
    "You have tools for generating and editing images and generating video: "
    "generate_image, edit_image, generate_video. When the user asks to create or "
    "edit an image/video (e.g. 'change the background to night'), CALL the appropriate tool instead of "
    "refusing. The images to edit are the ones the user attached in the current message. "
    "After running a tool, briefly summarize the result."
)
CHAT_TOOLS = [
    {"type": "function", "function": {
        "name": "generate_image",
        "description": "Generates a NEW image from a description and shows it to the user in the chat.",
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string", "description": "Detailed image description."},
            "aspect_ratio": {"type": "string", "description": "Aspect ratio, e.g. 16:9, 1:1, 9:16."}
        }, "required": ["prompt"]}}},
    {"type": "function", "function": {
        "name": "edit_image",
        "description": "Edits the image(s) ATTACHED by the user in the current message "
                       "(change background, style, add/remove elements). The result is shown to the user.",
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string", "description": "Description of the changes to apply to the image."}
        }, "required": ["prompt"]}}},
    {"type": "function", "function": {
        "name": "generate_video",
        "description": "Generates a short video from a description and shows it to the user.",
        "parameters": {"type": "object", "properties": {
            "prompt": {"type": "string", "description": "Description of the video scene."}
        }, "required": ["prompt"]}}},
]


# Mixin DnD tylko gdy dostępny; inaczej pusty (klasa działa bez zmian).
if _DND_AVAILABLE:
    _DnDMixin = TkinterDnD.DnDWrapper
else:
    class _DnDMixin:
        pass


class AIStudioPro(ctk.CTk, _DnDMixin):
    def __init__(self):
        super().__init__()

        # Inicjalizacja drag & drop (wczytanie natywnego tkdnd)
        self.dnd_enabled = False
        if _DND_AVAILABLE:
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_enabled = True
            except Exception as e:
                print("Drag & drop unavailable (tkdnd):", e)

        self.title(f"AI Studio Pro - xAI Interface  v{APP_VERSION}")
        self.geometry("1400x900")
        self.minsize(1100, 720)
        self.configure(fg_color=COLORS["background"])

        # Ikona aplikacji (pasek tytułu + pasek zadań Windows)
        if sys.platform == "win32":
            try:
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AIStudioPro.xAI")
            except Exception:
                pass
        try:
            if os.path.exists(ICON_FILE):
                self.iconbitmap(ICON_FILE)
        except Exception:
            pass

        # Modules
        self.history_mgr = HistoryManager()
        self.oauth = OAuthManager()
        self.chats = ChatStore()
        self.api_mgr = APIManager(self.get_api_key)

        # Migracja: jednorazowo przenieś starą historię czatu do pierwszej rozmowy
        _old_chat = self.history_mgr.get_chat_history()
        if _old_chat and not self.chats.messages():
            self.chats.set_messages([{"role": m.get("role", "user"),
                                      "content": m.get("content", "")} for m in _old_chat])

        # State
        self.current_tab = "Chat" # Default to Chat as requested
        self.api_key = self.load_api_key()
        self.chat_model = self.load_chat_model()
        self.available_models = list(DEFAULT_CHAT_MODELS)
        self.reference_images = []
        self.video_image_path: str | None = None
        self.video_model_name = DEFAULT_VIDEO_MODEL
        # Czat: kopia wiadomości aktywnej rozmowy (live może być multimodalna)
        self.chat_history = [dict(m) for m in self.chats.messages()]
        self.chat_attachments = []
        _s = self._read_settings()
        self.system_prompt = _s.get("system_prompt", "")
        self.chat_temperature = float(_s.get("chat_temperature", 0.7))
        self._chat_stop = threading.Event()
        self._chat_generating = False
        self._stream_label = None
        self._stream_body = None
        self._empty_widget = None
        self.results_cache = {"Generator": [], "Edit": [], "Video": []}

        self.build_ui()

        # Jeśli już zalogowani przez OAuth, pobierz w tle listę modeli (m.in. grok-build-0.1)
        if self.oauth.is_authenticated():
            threading.Thread(target=self._refresh_models, daemon=True).start()
        
    # --- Ustawienia aplikacji (osobny plik, by NIE nadpisywać historii w grok_config.json) ---
    def _read_settings(self):
        if SETTINGS_FILE.exists():
            try:
                return json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) or {}
            except: pass
        return {}

    def _write_settings(self, data):
        try:
            SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except: pass

    def load_api_key(self):
        key = self._read_settings().get("api_key", "")
        if not key:
            key = os.getenv("XAI_API_KEY", "")  # fallback z .env
        return key

    def save_api_key(self, key):
        self.api_key = (key or "").strip()
        settings = self._read_settings()
        settings["api_key"] = self.api_key
        self._write_settings(settings)
        self.update_auth_status()

    def load_chat_model(self):
        return self._read_settings().get("chat_model", DEFAULT_CHAT_MODEL)

    def save_chat_model(self, model):
        self.chat_model = model
        settings = self._read_settings()
        settings["chat_model"] = model
        self._write_settings(settings)

    def save_system_prompt(self, text):
        self.system_prompt = text
        settings = self._read_settings()
        settings["system_prompt"] = text
        self._write_settings(settings)

    def save_temperature(self, val):
        self.chat_temperature = round(float(val), 2)
        settings = self._read_settings()
        settings["chat_temperature"] = self.chat_temperature
        self._write_settings(settings)

    def get_api_key(self):
        """Token używany jako Bearer: token OAuth (jeśli zalogowany) albo klucz API."""
        token = self.oauth.get_access_token()
        if token:
            return token
        return self.api_key

    def is_authenticated(self):
        return bool(self.oauth.is_authenticated() or self.api_key)

    # --- Logowanie przez xAI account (OAuth) ---
    def update_auth_status(self):
        oauth_on = self.oauth.is_authenticated()
        active = bool(oauth_on or self.api_key)
        if hasattr(self, "status_pill"):
            self.status_pill.configure(fg_color=COLORS["success"] if active else COLORS["error"])
            self.status_label.configure(text="ACTIVE" if active else "MISSING")
        if hasattr(self, "account_btn"):
            if oauth_on:
                acc = self.oauth.get_account()
                email = acc.get("email") or acc.get("preferred_username") or "xAI account"
                self.account_btn.configure(text=f"✓ {email[:22]}",
                                           fg_color=COLORS["success"], hover_color="#0e9f6e")
            else:
                self.account_btn.configure(text="🔐 Sign in (xAI)",
                                           fg_color="#7c3aed", hover_color="#6d28d9")

    def on_account_button(self):
        if self.oauth.is_authenticated():
            if messagebox.askyesno("xAI Account", "Sign out of your xAI account?"):
                self.oauth.logout()
                self.update_auth_status()
                messagebox.showinfo("xAI Account", "Signed out.")
        else:
            self.start_oauth_login()

    def start_oauth_login(self):
        self.account_btn.configure(state="disabled", text="⏳ Signing in...")
        def status_cb(msg):
            self.after(0, lambda m=msg: self.account_btn.configure(text=f"⏳ {m[:18]}"))
        def worker():
            try:
                account = self.oauth.login(status_cb=status_cb)
                email = (account or {}).get("email", "xAI account")
                self.after(0, lambda e=email: self._on_login_done(True, e))
            except Exception as e:
                self.after(0, lambda err=str(e): self._on_login_done(False, err))
        threading.Thread(target=worker, daemon=True).start()

    def _on_login_done(self, ok, info):
        self.account_btn.configure(state="normal")
        self.update_auth_status()
        if ok:
            messagebox.showinfo("xAI Account", f"Signed in as: {info}")
            threading.Thread(target=self._refresh_models, daemon=True).start()
        else:
            messagebox.showerror("xAI Sign-in", info)

    # --- Lista modeli (m.in. grok-build-0.1) ---
    def _refresh_models(self):
        ids = self.api_mgr.list_models()
        chat_ids = [m for m in ids if m and "imagine" not in m]  # pomijamy modele obrazów/wideo
        merged = list(chat_ids)
        for m in DEFAULT_CHAT_MODELS:
            if m not in merged:
                merged.append(m)
        self.available_models = merged
        self.after(0, self._update_model_dropdown)

    def _update_model_dropdown(self):
        if hasattr(self, "chat_model_menu") and self.chat_model_menu.winfo_exists():
            self.chat_model_menu.configure(values=self.available_models)
            if self.chat_model not in self.available_models and self.available_models:
                self.chat_model = self.available_models[0]
            self.chat_model_menu.set(self.chat_model)

    def build_ui(self):
        # --- Top Header ---
        self.header = ctk.CTkFrame(self, height=70, fg_color="transparent")
        self.header.pack(fill="x", padx=30, pady=(20, 0))
        
        # Logo
        logo_frame = ctk.CTkFrame(self.header, fg_color="transparent")
        logo_frame.pack(side="left")
        ctk.CTkLabel(logo_frame, text="✨", font=("Inter", 24)).pack(side="left", padx=(0, 10))
        ctk.CTkLabel(logo_frame, text="AI Studio Pro", font=("Inter", 20, "bold"), text_color=COLORS["text"]).pack(side="left")
        
        # Navigation
        self.nav_frame = ctk.CTkFrame(self.header, fg_color="#1e293b", corner_radius=12)
        self.nav_frame.pack(side="left", padx=40)
        
        self.nav_buttons = {}
        for tab in ["Chat", "Generator", "Edit", "Video", "History", "Settings"]:
            btn = ctk.CTkButton(self.nav_frame, text=tab, width=100, height=36, 
                                corner_radius=10, fg_color="transparent", text_color=COLORS["text_secondary"],
                                font=("Inter", 13, "bold"), hover_color="#2d3748",
                                command=lambda t=tab: self.switch_tab(t))
            btn.pack(side="left", padx=2, pady=2)
            self.nav_buttons[tab] = btn
        
        self.update_nav_highlight()
        
        # API Key & Status
        status_frame = ctk.CTkFrame(self.header, fg_color="transparent")
        status_frame.pack(side="right")
        
        ctk.CTkLabel(status_frame, text="xAI API Key:", font=("Inter", 12), text_color=COLORS["text_secondary"]).pack(side="left", padx=(0, 5))
        
        self.key_entry = ctk.CTkEntry(status_frame, width=200, height=36, show="•", placeholder_text="Enter API Key...",
                                      fg_color="#1e293b", border_width=0, font=("Consolas", 12))
        self.key_entry.insert(0, self.api_key)
        self.key_entry.pack(side="left", padx=10)
        
        self.status_pill = ctk.CTkFrame(status_frame, width=80, height=28, corner_radius=14,
                                        fg_color=COLORS["success"] if self.api_key else COLORS["error"])
        self.status_pill.pack(side="left", padx=5)
        self.status_pill.pack_propagate(False)
        self.status_label = ctk.CTkLabel(self.status_pill, text="ACTIVE" if self.api_key else "MISSING", 
                                         font=("Inter", 10, "bold"), text_color="#fff")
        self.status_label.pack(expand=True)
        
        ctk.CTkButton(status_frame, text="Save", width=60, height=36, fg_color=COLORS["primary"], corner_radius=10,
                      command=lambda: self.save_api_key(self.key_entry.get())).pack(side="left", padx=(10, 0))

        # Logowanie przez xAI account (OAuth, jak Hermes / grok-cli)
        self.account_btn = ctk.CTkButton(status_frame, text="🔐 Sign in (xAI)", width=150, height=36,
                                         fg_color="#7c3aed", hover_color="#6d28d9", corner_radius=10,
                                         font=("Inter", 12, "bold"), command=self.on_account_button)
        self.account_btn.pack(side="left", padx=(10, 0))

        self.update_auth_status()

        # --- Main Layout ---
        self.main_container = ctk.CTkFrame(self, fg_color="transparent")
        self.main_container.pack(fill="both", expand=True, padx=30, pady=30)
        
        self.build_content_area()

    def switch_tab(self, tab):
        self.current_tab = tab
        self.update_nav_highlight()
        self.build_content_area()

    def update_nav_highlight(self):
        for name, btn in self.nav_buttons.items():
            if name == self.current_tab:
                btn.configure(fg_color=COLORS["primary"], text_color="#fff")
            else:
                btn.configure(fg_color="transparent", text_color=COLORS["text_secondary"])

    def build_content_area(self):
        for w in self.main_container.winfo_children(): w.destroy()
        
        # Content Column (Left, 8 cols)
        self.content_left = ctk.CTkFrame(self.main_container, fg_color="transparent")
        self.content_left.pack(side="left", fill="both", expand=True)
        
        # Sidebar Column (Right, 4 cols)
        self.sidebar = ctk.CTkFrame(self.main_container, width=350, fg_color="#161b30", corner_radius=15, border_width=1, border_color=COLORS["border"])
        self.sidebar.pack(side="right", fill="y", padx=(20, 0))
        self.sidebar.pack_propagate(False)
        
        if self.current_tab == "Generator":
            self.build_generator_view()
        elif self.current_tab == "Edit":
            self.build_edit_view()
        elif self.current_tab == "Video":
            self.build_video_view()
        elif self.current_tab == "Chat":
            self.build_chat_view()
        elif self.current_tab == "History":
            self.build_history_view()
        elif self.current_tab == "Settings":
            self.build_settings_view()
        else:
            self.build_placeholder_view()

    def build_generator_view(self):
        # Left Panel (Prompt + Results)
        title_frame = ctk.CTkFrame(self.content_left, fg_color="transparent")
        title_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(title_frame, text="Describe your image", font=FONTS["h1"]).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="Enter detailed parameters to generate photorealistic graphics.", 
                     font=FONTS["body"], text_color=COLORS["text_secondary"]).pack(anchor="w")
        
        prompt_box = ctk.CTkFrame(self.content_left, fg_color="#161b30", corner_radius=15, border_width=1, border_color="#2d3748")
        prompt_box.pack(fill="x", pady=20)
        
        self.gen_prompt = ctk.CTkTextbox(prompt_box, height=200, bg_color="transparent", fg_color="transparent", 
                                          font=("Inter", 16), border_width=0)
        self.gen_prompt.pack(fill="x", padx=15, pady=15)
        self.gen_prompt.insert("0.0", "Futuristic city in cyberpunk style, neon lights reflecting in puddles after rain...")
        
        btn_bar = ctk.CTkFrame(prompt_box, fg_color="#1c233a", height=60, corner_radius=0)
        btn_bar.pack(fill="x", side="bottom")
        
        self.gen_btn = ctk.CTkButton(btn_bar, text="🚀 GENERATE IMAGE", font=("Inter", 13, "bold"),
                                     fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
                                     height=40, width=180, corner_radius=10, command=self.run_generate)
        self.gen_btn.pack(side="right", padx=15, pady=10)
        
        self.gen_status_label = ctk.CTkLabel(btn_bar, text="Ready", font=FONTS["small"], text_color=COLORS["text_secondary"])
        self.gen_status_label.pack(side="left", padx=20)

        # Result Scroll Area
        self.gen_results_area = ctk.CTkScrollableFrame(self.content_left, fg_color="transparent")
        self.gen_results_area.pack(fill="both", expand=True)

        # Restore from cache
        if self.results_cache["Generator"]:
            self._restore_results("Generator", self.gen_results_area)

        # Sidebar Panel (Settings)
        ctk.CTkLabel(self.sidebar, text="GENERATION SETTINGS", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(pady=20, padx=25, anchor="w")
        
        # Variants Slider
        var_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        var_frame.pack(fill="x", padx=25, pady=10)
        ctk.CTkLabel(var_frame, text="Number of variants", font=("Inter", 13, "bold")).pack(side="left")
        self.var_count_lbl = ctk.CTkLabel(var_frame, text="1", font=FONTS["body"], text_color=COLORS["primary"])
        self.var_count_lbl.pack(side="right")
        
        self.num_variants = ctk.CTkSlider(self.sidebar, from_=1, to=10, number_of_steps=9, 
                                          command=lambda v: self.var_count_lbl.configure(text=str(int(v))))
        self.num_variants.set(1)
        self.num_variants.pack(fill="x", padx=25, pady=5)
        
        # Resolution
        ctk.CTkLabel(self.sidebar, text="Quality / Resolution", font=("Inter", 13, "bold")).pack(anchor="w", padx=25, pady=(20, 5))
        self.gen_res = ctk.CTkOptionMenu(self.sidebar, values=RESOLUTIONS, fg_color="#1e293b", button_color="#2d3748")
        self.gen_res.set("1k")
        self.gen_res.pack(fill="x", padx=25, pady=5)
        
        # Aspect Ratio
        ctk.CTkLabel(self.sidebar, text="Aspect Ratio", font=("Inter", 13, "bold")).pack(anchor="w", padx=25, pady=(20, 5))
        self.gen_ratio = ctk.CTkOptionMenu(self.sidebar, values=ASPECT_RATIOS, fg_color="#1e293b", button_color="#2d3748")
        self.gen_ratio.set("16:9")
        self.gen_ratio.pack(fill="x", padx=25, pady=5)

    def run_generate(self):
        prompt = self.gen_prompt.get("1.0", "end").strip()
        if not prompt or not self.is_authenticated(): return
        
        n = int(self.num_variants.get())
        res = self.gen_res.get()
        ratio = self.gen_ratio.get()
        
        self.gen_btn.configure(state="disabled")
        self.gen_status_label.configure(text="⏳ Generating images...")
        
        threading.Thread(target=self._worker_generate, args=(prompt, n, ratio, res), daemon=True).start()

    def _worker_generate(self, prompt, n, ratio, res):
        try:
            urls = self.api_mgr.generate_image(prompt, n, ratio, res)
            self.after(0, lambda: self.render_results(self.gen_results_area, urls, prompt, "generate", tab_name="Generator"))
            self.after(0, lambda: self.gen_status_label.configure(text="✅ Ready"))
        except Exception as e:
            self.after(0, lambda err=str(e): self.gen_status_label.configure(text=f"❌ Error: {err[:20]}"))
        finally:
            self.after(0, lambda: self.gen_btn.configure(state="normal"))

    # Shared UI rendering
    def render_results(self, container, urls, prompt, mode, tab_name=None):
        if not container: return
        # Result grid (3 columns)
        content_frame = None
        for child in container.winfo_children():
            if isinstance(child, ctk.CTkFrame):
                content_frame = child; break
        if not content_frame:
            content_frame = ctk.CTkFrame(container, fg_color="transparent")
            content_frame.pack(fill="x")
            
        current_idx = len(content_frame.winfo_children())
        for i, url in enumerate(urls):
            img, raw = download_image(url)
            if img:
                card = ResultCard(content_frame, img, raw, prompt, mode, self.history_mgr.save_to_history, self.history_mgr.get_save_path())
                card.grid(row=(current_idx+i)//3, column=(current_idx+i)%3, padx=10, pady=10)

                # Store in cache with the generated filepath
                if tab_name:
                    self.results_cache[tab_name].append((img, raw, prompt, mode, card.filepath))

    def _restore_results(self, tab_name, container):
        content_frame = ctk.CTkFrame(container, fg_color="transparent")
        content_frame.pack(fill="x")
        
        for i, data in enumerate(self.results_cache[tab_name]):
            # data is (img, raw, prompt, mode, filepath)
            img, raw, prompt, mode, filepath = data
            card = ResultCard(content_frame, img, raw, prompt, mode, self.history_mgr.save_to_history, self.history_mgr.get_save_path(), filepath=filepath)
            card.grid(row=i//3, column=i%3, padx=10, pady=10)

    # placeholder views
    def build_edit_view(self):
        # Left Panel (Title + Results)
        title_frame = ctk.CTkFrame(self.content_left, fg_color="transparent")
        title_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(title_frame, text="Image Editing & Style Transfer", font=FONTS["h1"]).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="Upload up to 3 images to modify or combine styles.", 
                     font=FONTS["body"], text_color=COLORS["text_secondary"]).pack(anchor="w")
        
        prompt_box = ctk.CTkFrame(self.content_left, fg_color="#161b30", corner_radius=15, border_width=1, border_color="#2d3748")
        prompt_box.pack(fill="x", pady=20)
        
        self.edit_prompt = ctk.CTkTextbox(prompt_box, height=180, bg_color="transparent", fg_color="transparent", 
                                          font=("Inter", 16), border_width=0)
        self.edit_prompt.pack(fill="x", padx=15, pady=15)
        self.edit_prompt.insert("0.0", "Change the background to a sunny beach")
        
        btn_bar = ctk.CTkFrame(prompt_box, fg_color="#1c233a", height=60, corner_radius=0)
        btn_bar.pack(fill="x", side="bottom")
        
        self.edit_btn = ctk.CTkButton(btn_bar, text="🎨 EXECUTE EDIT", font=("Inter", 13, "bold"),
                                     fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
                                     height=40, width=180, corner_radius=10, command=self.run_edit)
        self.edit_btn.pack(side="right", padx=15, pady=10)
        
        self.edit_status_label = ctk.CTkLabel(btn_bar, text="Ready", font=FONTS["small"], text_color=COLORS["text_secondary"])
        self.edit_status_label.pack(side="left", padx=20)

        # Result Scroll Area
        self.edit_results_area = ctk.CTkScrollableFrame(self.content_left, fg_color="transparent")
        self.edit_results_area.pack(fill="both", expand=True)

        # Restore from cache
        if self.results_cache["Edit"]:
            self._restore_results("Edit", self.edit_results_area)

        # Sidebar Panel (Settings)
        ctk.CTkLabel(self.sidebar, text="EDITING SETTINGS", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(pady=20, padx=25, anchor="w")
        
        # Image Upload
        ctk.CTkButton(self.sidebar, text="➕ Add image" + self._drop_hint(),
                      fg_color="#334155", hover_color="#475569", height=40,
                      command=self.load_edit_image).pack(fill="x", padx=25, pady=5)

        if self.dnd_enabled:
            drop_zone = ctk.CTkFrame(self.sidebar, fg_color="#0d1226", corner_radius=10,
                                     border_width=1, border_color="#334155", height=58)
            drop_zone.pack(fill="x", padx=25, pady=(4, 6))
            drop_zone.pack_propagate(False)
            dz_lbl = ctk.CTkLabel(drop_zone, text="⬇ Drop images here (max 3)",
                                  font=("Inter", 11), text_color=COLORS["text_secondary"])
            dz_lbl.pack(expand=True)
            self._register_drop(drop_zone, self._add_edit_images)
            self._register_drop(dz_lbl, self._add_edit_images)

        self.edit_ref_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.edit_ref_frame.pack(fill="x", padx=25, pady=10)
        self.update_edit_previews()

        # DnD także na polu promptu i ramce miniatur
        self._register_drop(getattr(self.edit_prompt, "_textbox", self.edit_prompt), self._add_edit_images)
        self._register_drop(self.edit_ref_frame, self._add_edit_images)

        # Variants
        ctk.CTkLabel(self.sidebar, text="Number of variants", font=("Inter", 13, "bold")).pack(anchor="w", padx=25, pady=(20, 5))
        self.edit_n = ctk.CTkOptionMenu(self.sidebar, values=["1", "2", "3", "4"], fg_color="#1e293b")
        self.edit_n.set("1")
        self.edit_n.pack(fill="x", padx=25, pady=5)
        
        # Resolution
        ctk.CTkLabel(self.sidebar, text="Resolution", font=("Inter", 13, "bold")).pack(anchor="w", padx=25, pady=(20, 5))
        self.edit_res = ctk.CTkOptionMenu(self.sidebar, values=RESOLUTIONS, fg_color="#1e293b")
        self.edit_res.set("1k")
        self.edit_res.pack(fill="x", padx=25, pady=5)
        
        # Aspect Ratio
        ctk.CTkLabel(self.sidebar, text="Aspect Ratio", font=("Inter", 13, "bold")).pack(anchor="w", padx=25, pady=(20, 5))
        self.edit_ratio = ctk.CTkOptionMenu(self.sidebar, values=ASPECT_RATIOS, fg_color="#1e293b")
        self.edit_ratio.set("auto")
        self.edit_ratio.pack(fill="x", padx=25, pady=5)

    def build_video_view(self):
        # Left Panel
        title_frame = ctk.CTkFrame(self.content_left, fg_color="transparent")
        title_frame.pack(fill="x", pady=(0, 10))
        ctk.CTkLabel(title_frame, text="Video Generation Studio", font=FONTS["h1"]).pack(anchor="w")
        ctk.CTkLabel(title_frame, text="Create cinematic clips using text or images.", 
                     font=FONTS["body"], text_color=COLORS["text_secondary"]).pack(anchor="w")
        
        prompt_box = ctk.CTkFrame(self.content_left, fg_color="#161b30", corner_radius=15, border_width=1, border_color="#2d3748")
        prompt_box.pack(fill="x", pady=20)
        
        self.video_prompt = ctk.CTkTextbox(prompt_box, height=180, bg_color="transparent", fg_color="transparent", 
                                          font=("Inter", 16), border_width=0)
        self.video_prompt.pack(fill="x", padx=15, pady=15)
        self.video_prompt.insert("0.0", "A beautiful forest at sunset, drone shot")
        
        btn_bar = ctk.CTkFrame(prompt_box, fg_color="#1c233a", height=60, corner_radius=0)
        btn_bar.pack(fill="x", side="bottom")
        
        self.video_btn = ctk.CTkButton(btn_bar, text="🎬 GENERATE VIDEO", font=("Inter", 13, "bold"),
                                      fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
                                      height=40, width=180, corner_radius=10, command=self.run_video)
        self.video_btn.pack(side="right", padx=15, pady=10)
        
        self.video_status_label = ctk.CTkLabel(btn_bar, text="Ready", font=FONTS["small"], text_color=COLORS["text_secondary"])
        self.video_status_label.pack(side="left", padx=20)

        # Video Preview Area
        self.video_display_frame = ctk.CTkFrame(self.content_left, fg_color="#111112", corner_radius=20)
        self.video_display_frame.pack(fill="both", expand=True, pady=20)
        
        self.video_main_status = ctk.CTkLabel(self.video_display_frame, text="Waiting for generation...", font=("Inter", 16))
        self.video_main_status.pack(expand=True)
        
        self.video_open_btn = ctk.CTkButton(self.video_display_frame, text="Open Generated Video", state="disabled", height=45)
        self.video_open_btn.pack(pady=30)
        
        # Restore from cache (Video)
        if self.results_cache["Video"]:
            # For video we might just want to show the last one since it's not a grid usually
            # But the user asked for it to stay visible.
            last_vid = self.results_cache["Video"][-1] # (img, raw, prompt, mode)
            # Find filepath from raw or just use what we have. 
            # Actually render_results handles images. For video, it's a bit different in the UI.
            self._restore_video_preview(last_vid)

        # Sidebar
        ctk.CTkLabel(self.sidebar, text="VIDEO SETTINGS", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(pady=20, padx=25, anchor="w")

        # Model selector (np. nowy grok-imagine-video-1.5-preview)
        ctk.CTkLabel(self.sidebar, text="Model", font=("Inter", 13, "bold")).pack(anchor="w", padx=25, pady=(0, 5))
        self.video_model = ctk.CTkOptionMenu(self.sidebar, values=VIDEO_MODELS, fg_color="#1e293b")
        self.video_model.set(self.video_model_name)
        self.video_model.configure(command=lambda v: setattr(self, "video_model_name", v))
        self.video_model.pack(fill="x", padx=25, pady=(0, 10))

        # Image-to-Video
        ctk.CTkButton(self.sidebar, text="📁 Load start image" + self._drop_hint(),
                      command=self.load_video_image, fg_color="#334155").pack(fill="x", padx=25, pady=5)
        _vid_hint = ("Drop an image here or click above\n(Text-to-Video)"
                     if self.dnd_enabled else "No image (Text-to-Video)")
        self.vid_img_preview = ctk.CTkLabel(self.sidebar, text=_vid_hint, height=100,
                                            fg_color="#111112", corner_radius=10)
        self.vid_img_preview.pack(fill="x", padx=25, pady=10)

        # DnD: podgląd, pole promptu i duży obszar podglądu
        _vid_drop = lambda imgs: self._set_video_image(imgs[0])
        self._register_drop(self.vid_img_preview, _vid_drop)
        self._register_drop(getattr(self.video_prompt, "_textbox", self.video_prompt), _vid_drop)
        self._register_drop(self.video_main_status, _vid_drop)
        
        # Duration Slider
        dur_frame = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        dur_frame.pack(fill="x", padx=25, pady=10)
        ctk.CTkLabel(dur_frame, text="Duration", font=("Inter", 13, "bold")).pack(side="left")
        self.dur_lbl = ctk.CTkLabel(dur_frame, text="5s", font=FONTS["body"], text_color=COLORS["primary"])
        self.dur_lbl.pack(side="right")
        
        self.video_duration = ctk.CTkSlider(self.sidebar, from_=1, to=15, number_of_steps=14, 
                                            command=lambda v: self.dur_lbl.configure(text=f"{int(v)}s"))
        self.video_duration.set(5)
        self.video_duration.pack(fill="x", padx=25, pady=5)
        
        # Resolution
        ctk.CTkLabel(self.sidebar, text="Quality", font=("Inter", 13, "bold")).pack(anchor="w", padx=25, pady=(20, 5))
        self.video_res = ctk.CTkOptionMenu(self.sidebar, values=VIDEO_RESOLUTIONS, fg_color="#1e293b")
        self.video_res.set("480p")
        self.video_res.pack(fill="x", padx=25, pady=5)
        
        # Ratio
        ctk.CTkLabel(self.sidebar, text="Aspect Ratio", font=("Inter", 13, "bold")).pack(anchor="w", padx=25, pady=(20, 5))
        self.video_ratio = ctk.CTkOptionMenu(self.sidebar, values=["Original"] + ASPECT_RATIOS[1:], fg_color="#1e293b")
        self.video_ratio.set("Original")
        self.video_ratio.pack(fill="x", padx=25, pady=5)

    # --- Drag & drop plików ---
    @staticmethod
    def _is_image_file(path):
        return os.path.splitext(path)[1].lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

    def _drop_hint(self):
        return " (or drag & drop)" if getattr(self, "dnd_enabled", False) else ""

    def _register_drop(self, widget, callback):
        """Rejestruje widget jako cel upuszczania plików (jeśli DnD dostępne)."""
        if not getattr(self, "dnd_enabled", False) or widget is None:
            return
        try:
            widget.drop_target_register(DND_FILES)
            widget.dnd_bind("<<Drop>>", lambda e: self._on_files_dropped(e, callback))
        except Exception:
            pass

    def _on_files_dropped(self, event, callback):
        try:
            paths = list(self.tk.splitlist(event.data))
        except Exception:
            paths = [event.data] if getattr(event, "data", None) else []
        imgs = [p for p in paths if self._is_image_file(p)]
        if imgs:
            callback(imgs)

    # --- Helper Logic ---
    def _add_edit_images(self, paths):
        for p in paths:
            if len(self.reference_images) >= 3:
                break
            if self._is_image_file(p) and p not in self.reference_images:
                self.reference_images.append(p)
        self.update_edit_previews()

    def load_edit_image(self):
        if len(self.reference_images) >= 3:
            return
        paths = filedialog.askopenfilenames(
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.gif *.bmp")])
        if paths:
            self._add_edit_images(list(paths))

    def update_edit_previews(self):
        for w in self.edit_ref_frame.winfo_children(): w.destroy()
        for idx, path in enumerate(self.reference_images):
            try:
                img = Image.open(path)
                img.thumbnail((80, 80))
                photo = ImageTk.PhotoImage(img)
                f = ctk.CTkFrame(self.edit_ref_frame, fg_color="#1e293b", corner_radius=8)
                f.pack(side="left", padx=5)
                lbl = ctk.CTkLabel(f, image=photo, text="")
                lbl.image = photo
                lbl.pack(padx=5, pady=5)
                ctk.CTkButton(f, text="×", width=20, height=20, fg_color="#ef4444", hover_color="#dc2626",
                              command=lambda i=idx: self.remove_edit_image(i)).pack(pady=(0, 5))
            except: pass

    def remove_edit_image(self, idx):
        self.reference_images.pop(idx)
        self.update_edit_previews()

    def _set_video_image(self, path):
        if not self._is_image_file(path):
            return
        try:
            self.video_image_path = path
            img = Image.open(path)
            img.thumbnail((250, 150))
            photo = ImageTk.PhotoImage(img)
            self.vid_img_preview.configure(image=photo, text="")
            self.vid_img_preview.image = photo
        except Exception as e:
            messagebox.showerror("Image", str(e))

    def load_video_image(self):
        path = filedialog.askopenfilename(filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.gif *.bmp")])
        if path:
            self._set_video_image(path)

    def run_edit(self):
        prompt = self.edit_prompt.get("1.0", "end").strip()
        if not prompt or not self.is_authenticated() or not self.reference_images: return
        self.edit_btn.configure(state="disabled")
        self.edit_status_label.configure(text="⏳ Editing images...")
        threading.Thread(target=self._worker_edit, args=(prompt, int(self.edit_n.get()), self.edit_ratio.get(), self.edit_res.get()), daemon=True).start()

    def _worker_edit(self, prompt, n, ratio, res):
        try:
            urls = self.api_mgr.edit_image(prompt, n, self.reference_images, ratio, res)
            self.after(0, lambda: self.render_results(self.edit_results_area, urls, prompt, "edit", tab_name="Edit"))
            self.after(0, lambda: self.edit_status_label.configure(text="✅ Done"))
        except Exception as e:
            self.after(0, lambda err=str(e): messagebox.showerror("Error", err))
            self.after(0, lambda: self.edit_status_label.configure(text="❌ Error"))
        finally:
            self.after(0, lambda: self.edit_btn.configure(state="normal"))

    def run_video(self):
        prompt = self.video_prompt.get("1.0", "end").strip()
        if not prompt or not self.is_authenticated(): return
        self.video_btn.configure(state="disabled")
        self.video_status_label.configure(text="⏳ Sending task...")
        self.video_main_status.configure(text="🎬 Generating video...\nThis can take up to 2 minutes.")
        model = self.video_model.get()
        threading.Thread(target=self._worker_video, args=(prompt, model), daemon=True).start()

    def _worker_video(self, prompt, model=None):
        try:
            job_id = self.api_mgr.create_video_job(prompt, int(self.video_duration.get()), self.video_res.get(), self.video_ratio.get(), self.video_image_path, model=model)
            while True:
                time.sleep(5)
                status = self.api_mgr.poll_video_status(job_id)
                if status.get("status") == "done" and status.get("video", {}).get("url"):
                    url = status["video"]["url"]
                    self.after(0, lambda u=url, p=prompt: self._auto_save_video(u, p))
                    break
                elif status.get("status") in ("failed", "expired"):
                    raise Exception("Video generation failed or expired.")
        except Exception as e:
            self.after(0, lambda err=str(e): messagebox.showerror("Video Error", err))
            self.after(0, lambda: self.video_status_label.configure(text="❌ Failed"))
        finally:
            self.after(0, lambda: self.video_btn.configure(state="normal"))


    def _auto_save_video(self, url, prompt):
        filename = f"studio_video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
        save_dir = Path(self.history_mgr.get_save_path())
        save_dir.mkdir(parents=True, exist_ok=True)
        filepath = save_dir / filename
        data = requests.get(url).content
        with open(filepath, "wb") as f: f.write(data)
        self.after(0, lambda: self.video_ready(str(filepath), prompt))

    def video_ready(self, filepath, prompt):
        self.video_status_label.configure(text="✅ Done!")
        self.video_main_status.configure(text="✨ Video ready!")
        self.video_open_btn.configure(state="normal", command=lambda: webbrowser.open(filepath))
        
        # Save to cache
        try:
            img = Image.open(filepath)
            img.thumbnail((400, 300))
            # For video, we store it like images but just the thumbnail for preview
            self.results_cache["Video"].append((img, None, prompt, "video", filepath))
        except: pass
        
        self.history_mgr.save_to_history("video", filepath, prompt)

    def _restore_video_preview(self, vid_data):
        # vid_data is (img, raw, prompt, mode, filepath)
        img, _, _, _, filepath = vid_data
        photo = ImageTk.PhotoImage(img)
        self.video_main_status.configure(image=photo, text="")
        self.video_main_status.image = photo
        self.video_open_btn.configure(state="normal", command=lambda p=filepath: webbrowser.open(p))
        self.video_status_label.configure(text="✅ Previous Video Restored")

    # ============================== CZAT (nowy UI) ==============================
    CHAT_WRAP = 720  # szerokość zawijania tekstu w dymkach

    def build_chat_view(self):
        container = ctk.CTkFrame(self.content_left, fg_color="transparent")
        container.pack(fill="both", expand=True)

        # --- Lewy panel: lista rozmów ---
        conv_col = ctk.CTkFrame(container, width=240, fg_color="#0d1226", corner_radius=14)
        conv_col.pack(side="left", fill="y", padx=(0, 12))
        conv_col.pack_propagate(False)
        ctk.CTkButton(conv_col, text="✚ New chat", height=34, corner_radius=10,
                      fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
                      command=self._new_conversation).pack(fill="x", padx=10, pady=10)
        ctk.CTkLabel(conv_col, text="CONVERSATIONS", font=FONTS["small"],
                     text_color=COLORS["text_secondary"]).pack(anchor="w", padx=14)
        self.conv_list = ctk.CTkScrollableFrame(conv_col, fg_color="transparent")
        self.conv_list.pack(fill="both", expand=True, padx=4, pady=(4, 10))

        # --- Główny obszar czatu ---
        main = ctk.CTkFrame(container, fg_color="transparent")
        main.pack(side="left", fill="both", expand=True)

        top = ctk.CTkFrame(main, fg_color="transparent")
        top.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(top, text="Model:", font=("Inter", 12),
                     text_color=COLORS["text_secondary"]).pack(side="left", padx=(2, 8))
        if self.chat_model not in self.available_models:
            self.available_models.insert(0, self.chat_model)
        self.chat_model_menu = ctk.CTkOptionMenu(top, values=self.available_models,
                                                 width=220, fg_color="#1e293b", button_color="#2d3748",
                                                 command=self.on_chat_model_change)
        self.chat_model_menu.set(self.chat_model)
        self.chat_model_menu.pack(side="left")
        ctk.CTkLabel(top, text="↳ grok-build-0.1 = Grok Build · commands: /image, /video",
                     font=("Inter", 11), text_color=COLORS["text_secondary"]).pack(side="left", padx=10)

        self.chat_scroll = ctk.CTkScrollableFrame(main, fg_color="#0b0f1f", corner_radius=16)
        self.chat_scroll.pack(fill="both", expand=True, pady=(0, 10))

        self.chips_frame = ctk.CTkFrame(main, fg_color="transparent")
        self.chips_frame.pack(fill="x")

        self.input_bar = ctk.CTkFrame(main, fg_color="#161b30", corner_radius=18,
                                      border_width=1, border_color="#2d3748")
        self.input_bar.pack(fill="x")
        self.attach_btn = ctk.CTkButton(self.input_bar, text="+", width=44, height=44, corner_radius=14,
                                        fg_color=COLORS["surface_alt"], hover_color="#2d3748",
                                        text_color=COLORS["primary"], font=("Segoe UI", 24, "bold"),
                                        command=self._add_attachments)
        self.attach_btn.pack(side="left", padx=(8, 4), pady=8)
        self.chat_input = ctk.CTkTextbox(self.input_bar, height=48, fg_color="transparent",
                                         border_width=0, font=("Inter", 14), wrap="word")
        self.chat_input.pack(side="left", fill="both", expand=True, padx=4, pady=8)
        self.chat_input.bind("<Return>", self._on_input_return)
        self.chat_input.bind("<Shift-Return>", lambda e: None)
        self.chat_input.bind("<KeyRelease>", self._grow_input)
        self.chat_input.bind("<Control-v>", self._paste_clipboard)
        self.send_btn = ctk.CTkButton(self.input_bar, text="Send", width=90, height=42, corner_radius=12,
                                      fg_color=COLORS["primary"], hover_color=COLORS["primary_hover"],
                                      font=("Inter", 13, "bold"), command=self.run_chat)
        self.send_btn.pack(side="right", padx=(4, 8), pady=8)
        self.stop_btn = ctk.CTkButton(self.input_bar, text="■ Stop", width=80, height=42, corner_radius=12,
                                      fg_color="#ef4444", hover_color="#dc2626",
                                      font=("Inter", 13, "bold"), command=self._stop_chat)

        self._build_chat_sidebar()

        self._empty_widget = None
        self._rerender_all()
        self._render_conv_list()
        self._render_attachment_chips()

        if self.oauth.is_authenticated():
            threading.Thread(target=self._refresh_models, daemon=True).start()

    def _build_chat_sidebar(self):
        ctk.CTkLabel(self.sidebar, text="CHAT SETTINGS", font=FONTS["small"],
                     text_color=COLORS["text_secondary"]).pack(pady=(18, 8), padx=25, anchor="w")

        ctk.CTkLabel(self.sidebar, text="System instruction", font=("Inter", 13, "bold")).pack(
            anchor="w", padx=25, pady=(5, 5))
        self.sys_prompt_box = ctk.CTkTextbox(self.sidebar, height=110, fg_color="#1e293b",
                                             border_width=0, font=("Inter", 12), wrap="word")
        self.sys_prompt_box.pack(fill="x", padx=25, pady=(0, 4))
        if self.system_prompt:
            self.sys_prompt_box.insert("1.0", self.system_prompt)
        self.sys_prompt_box.bind(
            "<FocusOut>",
            lambda e: self.save_system_prompt(self.sys_prompt_box.get("1.0", "end").strip()))

        temp_row = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        temp_row.pack(fill="x", padx=25, pady=(12, 0))
        ctk.CTkLabel(temp_row, text="Temperature", font=("Inter", 13, "bold")).pack(side="left")
        self.temp_lbl = ctk.CTkLabel(temp_row, text=f"{self.chat_temperature:.2f}",
                                     font=FONTS["body"], text_color=COLORS["primary"])
        self.temp_lbl.pack(side="right")
        self.temp_slider = ctk.CTkSlider(self.sidebar, from_=0, to=1, number_of_steps=20,
                                         command=self._on_temp_change)
        self.temp_slider.set(self.chat_temperature)
        self.temp_slider.pack(fill="x", padx=25, pady=(5, 14))

        ctk.CTkButton(self.sidebar, text="↻ Regenerate last", height=34, corner_radius=10,
                      fg_color="#334155", hover_color="#475569", command=self._regenerate).pack(
            fill="x", padx=25, pady=4)
        ctk.CTkButton(self.sidebar, text="⬇ Export chat (.md)", height=34, corner_radius=10,
                      fg_color="#334155", hover_color="#475569", command=self._export_markdown).pack(
            fill="x", padx=25, pady=4)

        ctk.CTkLabel(self.sidebar,
                     text="Enter sends · Shift+Enter newline · Ctrl+V pastes image\n"
                          "+ attaches images (vision) and text files.",
                     font=("Inter", 11), text_color=COLORS["text_secondary"],
                     wraplength=290, justify="left").pack(anchor="w", padx=25, pady=(12, 0))

    def _on_temp_change(self, val):
        self.temp_lbl.configure(text=f"{float(val):.2f}")
        self.save_temperature(val)

    def on_chat_model_change(self, value):
        self.save_chat_model(value)

    # --- Lista rozmów / przełączanie ---
    def _render_conv_list(self):
        if not hasattr(self, "conv_list") or not self.conv_list.winfo_exists():
            return
        for w in self.conv_list.winfo_children():
            w.destroy()
        active = self.chats.active_id()
        for c in self.chats.list():
            is_a = (c["id"] == active)
            row = ctk.CTkFrame(self.conv_list, fg_color="#1f2940" if is_a else "transparent",
                               corner_radius=8)
            row.pack(fill="x", pady=2, padx=(2, 6))  # prawy margines na pasek przewijania
            # WAŻNE: stałe przyciski pakujemy NAJPIERW side="right", by nie zniknęły pod
            # rozszerzającym się tytułem (expand). Inaczej 🗑 jest wypychany poza krawędź.
            ctk.CTkButton(row, text="🗑", width=28, height=28, corner_radius=6,
                          fg_color="transparent", hover_color="#ef4444",
                          command=lambda i=c["id"]: self._delete_chat(i)).pack(side="right", padx=(0, 2))
            ctk.CTkButton(row, text="✎", width=26, height=28, corner_radius=6,
                          fg_color="transparent", hover_color="#2d3748",
                          command=lambda i=c["id"]: self._rename_chat(i)).pack(side="right")
            ctk.CTkButton(row, text=c["title"][:18], anchor="w", height=28, corner_radius=6,
                          fg_color="transparent", hover_color="#2d3748",
                          text_color=COLORS["text"] if is_a else COLORS["text_secondary"],
                          command=lambda i=c["id"]: self._select_chat(i)).pack(
                side="left", fill="x", expand=True)

    def _select_chat(self, cid):
        if cid == self.chats.active_id():
            return
        if self._chat_generating:
            self._stop_chat()
        self._sync_store()
        self.chats.set_active(cid)
        self.chat_history = [dict(m) for m in self.chats.messages()]
        self.chat_attachments = []
        self._rerender_all()
        self._render_attachment_chips()
        self._render_conv_list()

    def _new_conversation(self):
        if self._chat_generating:
            self._stop_chat()
        self._sync_store()
        self.chats.new_chat()
        self.chat_history = []
        self.chat_attachments = []
        self._rerender_all()
        self._render_attachment_chips()
        self._render_conv_list()

    def _delete_chat(self, cid):
        if not messagebox.askyesno("Delete chat", "Delete this chat permanently?"):
            return
        was_active = (cid == self.chats.active_id())
        self.chats.delete(cid)
        if was_active:
            self.chat_history = [dict(m) for m in self.chats.messages()]
            self._rerender_all()
        self._render_conv_list()

    def _rename_chat(self, cid):
        dlg = ctk.CTkInputDialog(text="New chat name:", title="Rename")
        name = dlg.get_input()
        if name:
            self.chats.rename(cid, name)
            self._render_conv_list()

    # --- Trwałość (synchronizacja stanu live -> magazyn) ---
    def _content_to_text(self, content):
        if isinstance(content, list):
            texts, nimg = [], 0
            for p in content:
                if isinstance(p, dict):
                    if p.get("type") == "text":
                        texts.append(p.get("text", ""))
                    elif p.get("type") == "image_url":
                        nimg += 1
            s = "\n".join(t for t in texts if t).strip()
            if nimg:
                s = (s + f"\n📎 [image x{nimg}]").strip()
            return s
        return str(content)

    def _sync_store(self):
        msgs = [{"role": m.get("role", "assistant"),
                 "content": self._content_to_text(m.get("content", ""))}
                for m in self.chat_history]
        self.chats.set_messages(msgs)
        c = self.chats.get_active()
        if c and c["title"] == "New chat":
            for m in msgs:
                if m["role"] == "user" and m["content"].strip():
                    t = m["content"].strip().replace("\n", " ")
                    self.chats.rename(c["id"], (t[:34] + "…") if len(t) > 34 else t)
                    break
        self._render_conv_list()

    def _rerender_all(self):
        if not hasattr(self, "chat_scroll") or not self.chat_scroll.winfo_exists():
            return
        for w in self.chat_scroll.winfo_children():
            w.destroy()
        self._empty_widget = None
        self._stream_label = None
        self._stream_body = None
        if self.chat_history:
            for i, m in enumerate(self.chat_history):
                self._render_message(m.get("role", "assistant"), m.get("content", ""), idx=i)
        else:
            self._show_empty_state()
        self._scroll_chat_bottom()

    # --- Stan pusty ---
    def _show_empty_state(self):
        wrap = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        wrap.pack(expand=True, pady=80)
        ctk.CTkLabel(wrap, text="✨", font=("Inter", 46)).pack()
        ctk.CTkLabel(wrap, text="How can I help?", font=("Inter", 22, "bold")).pack(pady=(6, 2))
        ctk.CTkLabel(wrap, text="Ask a question, paste code, or attach an image/file (+).\n"
                               "Type /image <prompt> or /video <prompt> to generate media.",
                     font=("Inter", 13), text_color=COLORS["text_secondary"], justify="center").pack()
        self._empty_widget = wrap

    def _clear_empty_state(self):
        if self._empty_widget is not None:
            try:
                if self._empty_widget.winfo_exists():
                    self._empty_widget.destroy()
            except Exception:
                pass
            self._empty_widget = None

    # --- Schowek / przewijanie / pole wejściowe ---
    def _copy_to_clipboard(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
        except Exception:
            pass

    def _scroll_chat_bottom(self):
        try:
            self.update_idletasks()
            self.chat_scroll._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _on_input_return(self, event):
        if event.state & 0x0001:  # Shift -> nowa linia
            return None
        self.run_chat()
        return "break"

    def _grow_input(self, event=None):
        try:
            n = int(self.chat_input._textbox.index("end-1c").split(".")[0])
        except Exception:
            n = 1
        n = max(1, min(6, n))
        try:
            self.chat_input.configure(height=24 * n + 18)
        except Exception:
            pass

    def _reset_input_height(self):
        try:
            self.chat_input.configure(height=48)
        except Exception:
            pass

    def _paste_clipboard(self, event=None):
        try:
            from PIL import ImageGrab
            im = ImageGrab.grabclipboard()
        except Exception:
            im = None
        if isinstance(im, list) and im:
            for p in im:
                self._attach_path(p)
            self._render_attachment_chips()
            return "break"
        if im is not None and hasattr(im, "convert"):
            try:
                buf = io.BytesIO()
                im.convert("RGB").save(buf, "JPEG", quality=90)
                b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
                self.chat_attachments.append({"kind": "image", "name": "wklejony_obraz.jpg",
                                              "uri": f"data:image/jpeg;base64,{b64}"})
                self._render_attachment_chips()
            except Exception:
                pass
            return "break"
        return None

    # --- Attachmenti ---
    def _add_attachments(self):
        paths = filedialog.askopenfilenames(filetypes=[
            ("Supported", "*.png *.jpg *.jpeg *.webp *.gif *.bmp *.txt *.md *.py *.js *.ts "
                            "*.json *.csv *.html *.css *.log *.xml *.yaml *.yml *.ini *.cfg"),
            ("Images", "*.png *.jpg *.jpeg *.webp *.gif *.bmp"),
            ("Text files", "*.txt *.md *.py *.js *.ts *.json *.csv *.html *.css *.log *.xml *.yaml *.yml"),
            ("All files", "*.*"),
        ])
        for p in paths:
            self._attach_path(p)
        self._render_attachment_chips()

    def _attach_path(self, path):
        name = os.path.basename(path)
        ext = os.path.splitext(path)[1].lower()
        image_exts = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
        try:
            if ext in image_exts:
                uri = self._encode_image_data_uri(path)
                self.chat_attachments.append({"kind": "image", "name": name, "uri": uri})
            else:
                self.chat_attachments.append({"kind": "text", "name": name,
                                              "text": self._read_text_file(path)})
        except Exception as e:
            messagebox.showerror("Attachment", f"Cannot add {name}:\n{e}")

    def _encode_image_data_uri(self, path):
        img = Image.open(path)
        img.thumbnail((1536, 1536), Image.Resampling.LANCZOS)
        if img.mode != "RGB":
            img = img.convert("RGB")
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
        b64 = base64.b64encode(buf.getvalue()).decode("utf-8")
        return f"data:image/jpeg;base64,{b64}"

    def _read_text_file(self, path, limit=20000):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = f.read(limit + 1)
        if len(data) > limit:
            data = data[:limit] + "\n…[file truncated]"
        return data

    def _remove_attachment(self, idx):
        if 0 <= idx < len(self.chat_attachments):
            self.chat_attachments.pop(idx)
        self._render_attachment_chips()

    def _render_attachment_chips(self):
        if not hasattr(self, "chips_frame") or not self.chips_frame.winfo_exists():
            return
        for w in self.chips_frame.winfo_children():
            w.destroy()
        if not self.chat_attachments:
            return
        inner = ctk.CTkFrame(self.chips_frame, fg_color="transparent")
        inner.pack(fill="x", pady=(0, 6))
        for idx, att in enumerate(self.chat_attachments):
            chip = ctk.CTkFrame(inner, fg_color="#1b2236", corner_radius=12)
            chip.pack(side="left", padx=4, pady=2)
            icon = "🖼️" if att["kind"] == "image" else "📄"
            ctk.CTkLabel(chip, text=f"{icon} {att['name'][:26]}", font=("Inter", 11)).pack(
                side="left", padx=(10, 4), pady=4)
            ctk.CTkButton(chip, text="✕", width=22, height=22, fg_color="transparent",
                          hover_color="#ef4444", command=lambda i=idx: self._remove_attachment(i)).pack(
                side="left", padx=(0, 6))

    # --- Render wiadomości ---
    def _extract_display(self, content):
        if isinstance(content, list):
            texts, images = [], []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    texts.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    u = part.get("image_url", {})
                    images.append(u.get("url", "") if isinstance(u, dict) else u)
            return ("\n".join(t for t in texts if t).strip(), images)
        return (str(content), [])

    def _render_message(self, role, content, streaming=False, idx=None):
        self._clear_empty_state()
        text, image_uris = self._extract_display(content)
        is_user = (role == "user")

        row = ctk.CTkFrame(self.chat_scroll, fg_color="transparent")
        row.pack(fill="x", padx=6, pady=6)
        bubble = ctk.CTkFrame(row, fg_color=(COLORS["primary"] if is_user else "#1b2236"),
                              corner_radius=16)
        if is_user:
            bubble.pack(anchor="e", padx=(70, 4))          # użytkownik: wąski, po prawej
        else:
            bubble.pack(fill="x", anchor="w", padx=(4, 70))  # Grok: szeroki, na całość

        head = ctk.CTkFrame(bubble, fg_color="transparent")
        head.pack(fill="x", padx=14, pady=(8, 0))
        ctk.CTkLabel(head, text=("🧑  You" if is_user else "✨  Grok"), font=("Inter", 11, "bold"),
                     text_color="#dbeafe" if is_user else COLORS["text_secondary"]).pack(side="left")
        if is_user and idx is not None and not self._chat_generating:
            ctk.CTkButton(head, text="Edit", width=56, height=22, font=("Inter", 10),
                          fg_color="transparent", hover_color="#2d48cc",
                          command=lambda i=idx: self._edit_user_message(i)).pack(side="right")
        if not is_user:
            ctk.CTkButton(head, text="Copy", width=56, height=22, font=("Inter", 10),
                          fg_color="transparent", hover_color="#2d3748",
                          command=lambda t=text: self._copy_to_clipboard(t)).pack(side="right")

        body = ctk.CTkFrame(bubble, fg_color="transparent")
        body.pack(fill="both", padx=14, pady=(2, 10))

        for uri in image_uris:
            self._render_image_thumb(body, uri)

        if is_user:
            if text:
                ctk.CTkLabel(body, text=text, font=("Inter", 14), justify="left",
                             text_color="#ffffff", wraplength=self.CHAT_WRAP).pack(anchor="w")
        else:
            if streaming:
                lbl = ctk.CTkLabel(body, text=(text or "▌"), font=("Inter", 14), justify="left",
                                   text_color=COLORS["text"], wraplength=self.CHAT_WRAP)
                lbl.pack(anchor="w")
                self._stream_label = lbl
                self._stream_body = body
            else:
                self._render_assistant_body(body, text)

        self._scroll_chat_bottom()
        return row, bubble, body

    def _load_image_bytes(self, uri):
        """Pobiera PEŁNE bajty obrazu (raz) — z data-URI albo z URL."""
        try:
            if uri.startswith("data:"):
                return base64.b64decode(uri.split(",", 1)[1])
            return requests.get(uri, timeout=30).content
        except Exception:
            return None

    def _render_image_thumb(self, parent, uri):
        raw = self._load_image_bytes(uri)
        try:
            img = Image.open(io.BytesIO(raw)) if raw else None
        except Exception:
            img = None
        if img is None:
            ctk.CTkLabel(parent, text="🖼️ (cannot display image)", font=("Inter", 12),
                         text_color=COLORS["text_secondary"]).pack(anchor="w")
            return

        full_w, full_h = img.width, img.height
        holder = ctk.CTkFrame(parent, fg_color="transparent")
        holder.pack(anchor="w", pady=(2, 6))

        thumb = img.copy()
        thumb.thumbnail((340, 340))
        photo = ImageTk.PhotoImage(thumb)
        lbl = ctk.CTkLabel(holder, image=photo, text="", cursor="hand2")
        lbl.image = photo
        lbl.pack(anchor="w")
        lbl.bind("<Button-1>", lambda e, r=raw: self._open_image_viewer(r))

        bar = ctk.CTkFrame(holder, fg_color="transparent")
        bar.pack(anchor="w", pady=(4, 0))
        ctk.CTkButton(bar, text=f"🔍 Full size ({full_w}×{full_h})", height=26, font=("Inter", 11),
                      fg_color="#334155", hover_color="#475569",
                      command=lambda r=raw: self._open_image_viewer(r)).pack(side="left", padx=(0, 6))
        ctk.CTkButton(bar, text="⬇ Save", width=90, height=26, font=("Inter", 11),
                      fg_color="#334155", hover_color="#475569",
                      command=lambda r=raw: self._save_image_bytes(r)).pack(side="left")

    def _image_ext(self, raw):
        try:
            fmt = Image.open(io.BytesIO(raw)).format
            ext = "." + (fmt.lower() if fmt else "png")
            return ".jpg" if ext == ".jpeg" else ext
        except Exception:
            return ".png"

    def _save_image_bytes(self, raw, suggested=None):
        if not raw:
            return
        ext = self._image_ext(raw)
        fname = suggested or f"grok_obraz_{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
        path = filedialog.asksaveasfilename(
            defaultextension=ext, initialfile=fname,
            filetypes=[("Image", "*.png *.jpg *.jpeg *.webp"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "wb") as f:
                f.write(raw)
            messagebox.showinfo("Saved", f"Image saved:\n{path}")
        except Exception as e:
            messagebox.showerror("Save", str(e))

    def _open_in_system(self, raw):
        try:
            import tempfile
            tf = os.path.join(tempfile.gettempdir(),
                              f"grok_view_{datetime.now().strftime('%H%M%S_%f')}{self._image_ext(raw)}")
            with open(tf, "wb") as f:
                f.write(raw)
            try:
                os.startfile(tf)  # Windows
            except AttributeError:
                webbrowser.open("file://" + tf)
        except Exception as e:
            messagebox.showerror("Open", str(e))

    def _open_image_viewer(self, raw):
        """Okno podglądu obrazu w pełnej rozdzielczości (skalowane do ekranu) + zapis."""
        if not raw:
            return
        try:
            img = Image.open(io.BytesIO(raw))
        except Exception as e:
            messagebox.showerror("Preview", str(e))
            return
        full_w, full_h = img.width, img.height

        win = ctk.CTkToplevel(self)
        win.title(f"Preview — {full_w}×{full_h}")
        win.configure(fg_color=COLORS["background"])

        bar = ctk.CTkFrame(win, fg_color="transparent")
        bar.pack(fill="x", padx=12, pady=10)
        ctk.CTkLabel(bar, text=f"Resolution: {full_w}×{full_h}px", font=("Inter", 12),
                     text_color=COLORS["text_secondary"]).pack(side="left")
        ctk.CTkButton(bar, text="⬇ Save", width=100,
                      command=lambda r=raw: self._save_image_bytes(r)).pack(side="right", padx=4)
        ctk.CTkButton(bar, text="🖥 Open in system viewer", width=170, fg_color="#334155", hover_color="#475569",
                      command=lambda r=raw: self._open_in_system(r)).pack(side="right", padx=4)

        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        max_w, max_h = int(sw * 0.9), int(sh * 0.82)
        disp = img.copy()
        if disp.width > max_w or disp.height > max_h:
            disp.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(disp)
        img_lbl = ctk.CTkLabel(win, image=photo, text="")
        img_lbl.image = photo
        img_lbl.pack(padx=12, pady=(0, 12))
        if disp.width != full_w or disp.height != full_h:
            ctk.CTkLabel(win, text="Image scaled to fit the screen — click 'Open in system viewer' for a 1:1 view.",
                         font=("Inter", 10), text_color=COLORS["text_secondary"]).pack(pady=(0, 8))

        win.geometry(f"{max(420, disp.width + 40)}x{disp.height + 130}")
        win.after(120, win.lift)
        win.after(150, win.focus_force)

    # --- Bogaty tekst (markdown w widgecie Text z tagami) ---
    def _inline_tokens(self, s):
        out, i = [], 0
        pat = re.compile(
            r'\*\*(.+?)\*\*'
            r'|`([^`]+?)`'
            r'|(?<![\*\w])\*(?=\S)([^*]+?)(?<=\S)\*(?![\*\w])'
            r'|__(.+?)__'
            r'|(?<![_\w])_(?=\S)([^_]+?)(?<=\S)_(?![_\w])')
        for m in pat.finditer(s):
            if m.start() > i:
                out.append((s[i:m.start()], None))
            if m.group(1) is not None:
                out.append((m.group(1), "bold"))
            elif m.group(2) is not None:
                out.append((m.group(2), "icode"))
            elif m.group(3) is not None:
                out.append((m.group(3), "italic"))
            elif m.group(4) is not None:
                out.append((m.group(4), "bold"))
            elif m.group(5) is not None:
                out.append((m.group(5), "italic"))
            i = m.end()
        if i < len(s):
            out.append((s[i:], None))
        return out

    def _insert_inline(self, t, s, base=()):
        for chunk, tag in self._inline_tokens(s):
            tags = tuple(base) + ((tag,) if tag else ())
            t.insert("end", chunk, tags)

    def _readonly_key(self, e):
        if (e.state & 0x4) and e.keysym.lower() in ("c", "a"):
            return None  # zezwól na Ctrl+C / Ctrl+A
        if e.keysym in ("Left", "Right", "Up", "Down", "Prior", "Next", "Home", "End"):
            return None
        return "break"

    def _autosize_textbox(self, tb, raw):
        def apply():
            n = None
            try:
                self.update_idletasks()
                res = tb._textbox.count("1.0", "end-1c", "displaylines")
                if res:
                    n = int(res[0])
            except Exception:
                n = None
            if not n or n < 1:
                n = 0
                for ln in raw.split("\n"):
                    n += max(1, (len(ln) // 78) + 1)
            try:
                tb.configure(height=int(21 * n + 14))
            except Exception:
                pass
        apply()
        self.after_idle(apply)

    def _bind_resize(self, tb, raw):
        st = {"w": 0}
        def cb(e):
            if abs(e.width - st["w"]) > 12:
                st["w"] = e.width
                self._autosize_textbox(tb, raw)
        tb.bind("<Configure>", cb)

    def _render_richtext(self, parent, text):
        tb = ctk.CTkTextbox(parent, fg_color="transparent", border_width=0,
                            wrap="word", font=("Inter", 14), activate_scrollbars=False)
        tb.pack(fill="x", pady=1)
        t = tb._textbox
        t.configure(spacing3=4, cursor="arrow")
        t.tag_configure("bold", font=("Inter", 14, "bold"))
        t.tag_configure("italic", font=("Inter", 14, "italic"))
        t.tag_configure("icode", font=("Consolas", 12), background="#11172b")
        t.tag_configure("h1", font=("Inter", 18, "bold"), spacing1=6, spacing3=4)
        t.tag_configure("h2", font=("Inter", 15, "bold"), spacing1=4, spacing3=2)
        t.tag_configure("bullet", lmargin1=16, lmargin2=30)

        lines = text.split("\n")
        for li, line in enumerate(lines):
            s = line.strip()
            mh = re.match(r'^(#{1,6})\s+(.*)$', s)
            mb = re.match(r'^[-*+]\s+(.*)$', s)
            mn = re.match(r'^(\d+)\.\s+(.*)$', s)
            if mh:
                self._insert_inline(t, mh.group(2), base=("h1" if len(mh.group(1)) <= 2 else "h2",))
            elif mb:
                t.insert("end", "•  ", ("bullet",))
                self._insert_inline(t, mb.group(1), base=("bullet",))
            elif mn:
                t.insert("end", f"{mn.group(1)}.  ", ("bullet",))
                self._insert_inline(t, mn.group(2), base=("bullet",))
            else:
                self._insert_inline(t, line)
            if li != len(lines) - 1:
                t.insert("end", "\n")

        tb.bind("<Key>", self._readonly_key)  # tylko do odczytu, ale zaznaczalny
        self._autosize_textbox(tb, text)
        self._bind_resize(tb, text)
        return tb

    def _render_assistant_body(self, parent, text):
        if not text:
            ctk.CTkLabel(parent, text="(empty response)", font=("Inter", 13),
                         text_color=COLORS["text_secondary"]).pack(anchor="w")
            return
        parts = re.split(r"```", text)
        for i, part in enumerate(parts):
            if i % 2 == 1:  # blok kodu
                code = part
                lines = part.split("\n")
                lang = ""
                if lines and lines[0].strip() and " " not in lines[0].strip() and len(lines[0].strip()) < 20:
                    lang = lines[0].strip()
                    code = "\n".join(lines[1:])
                code = code.strip("\n")
                if code:
                    self._render_code_block(parent, code, lang)
            else:
                seg = part.strip("\n")
                if seg:
                    self._render_richtext(parent, seg)

    def _render_code_block(self, parent, code, lang=""):
        box = ctk.CTkFrame(parent, fg_color="#070b16", corner_radius=10,
                           border_width=1, border_color="#2d3748")
        box.pack(fill="x", pady=6)
        bar = ctk.CTkFrame(box, fg_color="#11172b", corner_radius=0, height=28)
        bar.pack(fill="x")
        ctk.CTkLabel(bar, text=(lang or "code"), font=("Consolas", 10),
                     text_color=COLORS["text_secondary"]).pack(side="left", padx=10)
        ctk.CTkButton(bar, text="Copy code", width=84, height=22, font=("Inter", 10),
                      fg_color="transparent", hover_color="#2d3748",
                      command=lambda c=code: self._copy_to_clipboard(c)).pack(side="right", padx=6, pady=2)
        n_lines = code.count("\n") + 1
        tb = ctk.CTkTextbox(box, font=("Consolas", 12), fg_color="#070b16", wrap="none",
                            height=min(380, 20 * max(1, n_lines) + 16), border_width=0)
        tb.pack(fill="both", padx=4, pady=(0, 6))
        tb.insert("1.0", code)
        self._highlight_code(tb, code)
        tb.bind("<Key>", self._readonly_key)  # tylko do odczytu, ale zaznaczalny

    def _highlight_code(self, tb, code):
        t = tb._textbox
        t.tag_configure("kw", foreground="#c792ea")
        t.tag_configure("str", foreground="#c3e88d")
        t.tag_configure("com", foreground="#637288")
        t.tag_configure("num", foreground="#f78c6c")

        def add(tag, a, b):
            try:
                t.tag_add(tag, f"1.0 + {a} chars", f"1.0 + {b} chars")
            except Exception:
                pass

        kw = (r'\b(def|class|return|if|elif|else|for|while|import|from|in|is|not|and|or|None|'
              r'True|False|function|const|let|var|new|public|private|protected|static|void|'
              r'int|float|double|bool|string|str|try|except|catch|finally|throw|throws|with|'
              r'as|lambda|await|async|yield|break|continue|pass|this|self|export|default|'
              r'enum|interface|struct|switch|case|do|using|namespace)\b')
        for m in re.finditer(kw, code):
            add("kw", m.start(), m.end())
        for m in re.finditer(r'\b\d+(?:\.\d+)?\b', code):
            add("num", m.start(), m.end())
        for m in re.finditer(r'"[^"\n]*"|\'[^\'\n]*\'|`[^`\n]*`', code):
            add("str", m.start(), m.end())
        for m in re.finditer(r'/\*.*?\*/', code, re.DOTALL):
            add("com", m.start(), m.end())
        for m in re.finditer(r'(#|//).*', code):
            add("com", m.start(), m.end())
        t.tag_raise("str")
        t.tag_raise("com")

    # --- Budowa wiadomości / komendy ---
    def _build_user_content(self, text):
        text_parts = [text] if text else []
        image_uris = []
        for att in self.chat_attachments:
            if att["kind"] == "image":
                image_uris.append(att["uri"])
            else:
                text_parts.append(f"\n[Attached file: {att['name']}]\n```\n{att['text']}\n```")
        full_text = "\n".join(text_parts).strip()
        if image_uris:
            content = []
            if full_text:
                content.append({"type": "text", "text": full_text})
            for u in image_uris:
                content.append({"type": "image_url", "image_url": {"url": u}})
            return content
        return full_text

    def _build_api_messages(self):
        msgs = []
        sp = (self.system_prompt or "").strip()
        if sp:
            msgs.append({"role": "system", "content": sp})
        msgs.extend(self.chat_history)
        return msgs

    def _parse_command(self, text):
        m = re.match(r'^/(obraz|image|img|wideo|video)\b\s*(.*)$', text.strip(),
                     re.IGNORECASE | re.DOTALL)
        if not m:
            return (None, None)
        name = m.group(1).lower()
        arg = m.group(2).strip()
        if name in ("obraz", "image", "img"):
            return ("image", arg)
        return ("video", arg)

    def _looks_like_media_request(self, text):
        return bool(re.search(
            r'(edytuj|zedytuj|edycj|wykonaj|przer[oó]b|popraw|zmie[nń]|wygeneruj|narysuj|'
            r'stw[oó]rz|utw[oó]rz|dorysuj|domaluj|generate|edit|draw|create)\w*.{0,40}'
            r'(obraz|obrazek|zdj[eę]ci|fotk|grafik|t[lł]o|background|wideo|film|klip|video|image|picture)',
            text, re.IGNORECASE | re.DOTALL))

    # --- Wysyłanie ---
    def run_chat(self):
        if self._chat_generating:
            return "break"
        if not self.is_authenticated():
            messagebox.showwarning("API", "Sign in with your xAI account or enter an API key first.")
            return "break"

        text = self.chat_input.get("1.0", "end").strip()
        if not text and not self.chat_attachments:
            return "break"

        cmd, arg = self._parse_command(text)
        # obrazy z bieżącej tury (potrzebne narzędziu edit_image) — zapamiętaj przed czyszczeniem
        turn_images = [a["uri"] for a in self.chat_attachments if a["kind"] == "image"]
        use_tools = bool(turn_images) or self._looks_like_media_request(text)

        user_content = self._build_user_content(text)
        self.chat_history.append({"role": "user", "content": user_content})
        self._render_message("user", user_content, idx=len(self.chat_history) - 1)
        self._sync_store()

        self.chat_input.delete("1.0", "end")
        self._reset_input_height()
        self.chat_attachments = []
        self._render_attachment_chips()

        self._render_message("assistant", "", streaming=True)
        self._begin_generation()

        if cmd == "image":
            threading.Thread(target=self._worker_image_cmd, args=(arg or text,), daemon=True).start()
        elif cmd == "video":
            threading.Thread(target=self._worker_video_cmd, args=(arg or text,), daemon=True).start()
        elif use_tools:
            api_messages = self._build_api_messages()
            threading.Thread(target=self._worker_chat_tools,
                             args=(api_messages, turn_images), daemon=True).start()
        else:
            api_messages = self._build_api_messages()
            threading.Thread(target=self._worker_chat, args=(api_messages,), daemon=True).start()
        return "break"

    def _begin_generation(self):
        self._chat_generating = True
        if hasattr(self, "send_btn") and self.send_btn.winfo_exists():
            self.send_btn.configure(state="disabled", text="…")
        if hasattr(self, "stop_btn") and self.stop_btn.winfo_exists():
            self.stop_btn.pack(side="right", padx=(0, 4), pady=8)

    def _stop_chat(self):
        self._chat_stop.set()

    def _worker_chat(self, api_messages):
        self._chat_stop.clear()
        got = {"any": False}

        def on_delta(delta, full):
            got["any"] = True
            self.after(0, lambda f=full: self._on_stream_delta(f))

        full = ""
        try:
            try:
                full = self.api_mgr.chat_completion_stream(
                    api_messages, model=self.chat_model, temperature=self.chat_temperature,
                    on_delta=on_delta, stop_flag=self._chat_stop.is_set)
            except Exception:
                if got["any"]:
                    raise
                full = self.api_mgr.chat_completion(
                    api_messages, model=self.chat_model, temperature=self.chat_temperature)
            self.chat_history.append({"role": "assistant", "content": full})
            self.after(0, lambda f=full: self._finalize_assistant(f))
        except Exception as e:
            self.after(0, lambda err=str(e): self._chat_error(err))
        finally:
            self.after(0, self._end_generation)

    def _worker_image_cmd(self, prompt):
        self._chat_stop.clear()
        try:
            urls = self.api_mgr.generate_image(prompt, 1, "16:9", "1k")
            for u in urls:
                try:
                    self.history_mgr.save_to_history("generate", u, prompt)
                except Exception:
                    pass
            cap = f"🖼️ Generated image: {prompt}"
            self.chat_history.append({"role": "assistant", "content": cap})
            self.after(0, lambda: self._replace_stream_with_media(urls=urls, caption=cap))
        except Exception as e:
            self.after(0, lambda err=str(e): self._chat_error(err))
        finally:
            self.after(0, self._end_generation)

    def _worker_video_cmd(self, prompt):
        self._chat_stop.clear()
        try:
            job = self.api_mgr.create_video_job(prompt, 5, "480p", "Original", None, model=self.video_model_name)
            path = None
            while True:
                if self._chat_stop.is_set():
                    break
                time.sleep(5)
                st = self.api_mgr.poll_video_status(job)
                if st.get("status") == "done" and st.get("video", {}).get("url"):
                    url = st["video"]["url"]
                    fn = f"chat_video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                    d = Path(self.history_mgr.get_save_path())
                    d.mkdir(parents=True, exist_ok=True)
                    path = str(d / fn)
                    with open(path, "wb") as f:
                        f.write(requests.get(url).content)
                    try:
                        self.history_mgr.save_to_history("video", path, prompt)
                    except Exception:
                        pass
                    break
                elif st.get("status") in ("failed", "expired"):
                    raise Exception("Video generation failed.")
            cap = f"🎬 Generated video: {prompt}"
            self.chat_history.append({"role": "assistant", "content": cap})
            self.after(0, lambda p=path: self._replace_stream_with_media(caption=cap, video_path=p))
        except Exception as e:
            self.after(0, lambda err=str(e): self._chat_error(err))
        finally:
            self.after(0, self._end_generation)

    # --- Czat z narzędziami (function calling): generowanie/edycja obrazu, wideo ---
    def _worker_chat_tools(self, api_messages, turn_images):
        self._chat_stop.clear()
        self.after(0, lambda: self._set_stream_text("⚙️ Analyzing request…"))
        msgs = [{"role": "system", "content": TOOL_SYSTEM}] + list(api_messages)
        media = []
        try:
            final = ""
            for _ in range(5):
                if self._chat_stop.is_set():
                    break
                msg = self.api_mgr.chat_with_tools(
                    msgs, model=self.chat_model, temperature=self.chat_temperature, tools=CHAT_TOOLS)
                tcs = msg.get("tool_calls")
                if not tcs:
                    final = msg.get("content") or ""
                    break
                msgs.append(msg)  # wiadomość asystenta z tool_calls
                for tc in tcs:
                    fn = tc.get("function", {}) or {}
                    name = fn.get("name", "")
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except Exception:
                        args = {}
                    self.after(0, lambda n=name: self._set_stream_text(f"⚙️ Using tool: {n}…"))
                    res_text, items = self._exec_tool(name, args, turn_images)
                    media.extend(items)
                    msgs.append({"role": "tool", "tool_call_id": tc.get("id"), "content": res_text})
            if not final and not media:
                final = "(brak odpowiedzi)"
            self.after(0, lambda f=final, m=list(media): self._finalize_tools(f, m))
        except Exception as e:
            self.after(0, lambda err=str(e): self._chat_error(err))
        finally:
            self.after(0, self._end_generation)

    def _exec_tool(self, name, args, turn_images):
        prompt = (args.get("prompt") or "").strip()
        ratio = args.get("aspect_ratio") or "16:9"
        try:
            if name == "generate_image":
                urls = self.api_mgr.generate_image(prompt or "obraz", 1, ratio, "1k")
                for u in urls:
                    try:
                        self.history_mgr.save_to_history("generate", u, prompt)
                    except Exception:
                        pass
                return ("Generated an image and showed it to the user.",
                        [{"kind": "image", "url": u} for u in urls])
            if name == "edit_image":
                if not turn_images:
                    return ("No attached image to edit. Ask the user to attach a photo (📎).", [])
                urls = self.api_mgr.edit_image_b64(prompt or "popraw obraz", turn_images, 1,
                                                   args.get("aspect_ratio") or "auto", "1k")
                for u in urls:
                    try:
                        self.history_mgr.save_to_history("edit", u, prompt)
                    except Exception:
                        pass
                return ("Edited the image and showed it to the user.",
                        [{"kind": "image", "url": u} for u in urls])
            if name == "generate_video":
                job = self.api_mgr.create_video_job(prompt or "wideo", 5, "480p", "Original", None, model=self.video_model_name)
                path = None
                while not self._chat_stop.is_set():
                    time.sleep(5)
                    st = self.api_mgr.poll_video_status(job)
                    if st.get("status") == "done" and st.get("video", {}).get("url"):
                        url = st["video"]["url"]
                        fn = f"chat_video_{datetime.now().strftime('%Y%m%d_%H%M%S')}.mp4"
                        d = Path(self.history_mgr.get_save_path())
                        d.mkdir(parents=True, exist_ok=True)
                        path = str(d / fn)
                        with open(path, "wb") as f:
                            f.write(requests.get(url).content)
                        try:
                            self.history_mgr.save_to_history("video", path, prompt)
                        except Exception:
                            pass
                        break
                    elif st.get("status") in ("failed", "expired"):
                        return ("Video generation failed.", [])
                return ("Generated a video and showed it to the user.",
                        ([{"kind": "video", "path": path}] if path else []))
        except Exception as e:
            return (f"Tool {name} returned an error: {e}", [])
        return (f"Unknown tool: {name}", [])

    def _set_stream_text(self, txt):
        if self._stream_label is not None and self._stream_label.winfo_exists():
            self._stream_label.configure(text=txt)
            self._scroll_chat_bottom()

    def _finalize_tools(self, text, media):
        if self._stream_body is not None and self._stream_body.winfo_exists():
            for w in self._stream_body.winfo_children():
                w.destroy()
            if text.strip() and text.strip() != "(brak odpowiedzi)":
                self._render_assistant_body(self._stream_body, text)
            for m in media:
                if m["kind"] == "image":
                    self._render_image_thumb(self._stream_body, m["url"])
                elif m["kind"] == "video" and m.get("path"):
                    ctk.CTkButton(self._stream_body, text="▶ Open video", fg_color=COLORS["primary"],
                                  hover_color=COLORS["primary_hover"],
                                  command=lambda p=m["path"]: webbrowser.open(p)).pack(anchor="w", pady=4)
        markers = "".join(("\n🖼️ [image]" if m["kind"] == "image" else "\n🎬 [video]") for m in media)
        self.chat_history.append({"role": "assistant", "content": (text + markers).strip() or "[media]"})
        self._stream_label = None
        self._stream_body = None
        self._sync_store()
        self._scroll_chat_bottom()

    def _on_stream_delta(self, full):
        if self._stream_label is not None and self._stream_label.winfo_exists():
            self._stream_label.configure(text=full + " ▌")
            self._scroll_chat_bottom()

    def _finalize_assistant(self, full):
        if self._stream_body is not None and self._stream_body.winfo_exists():
            for w in self._stream_body.winfo_children():
                w.destroy()
            self._render_assistant_body(self._stream_body, full)
        self._stream_label = None
        self._stream_body = None
        self._sync_store()
        self._scroll_chat_bottom()

    def _replace_stream_with_media(self, urls=None, caption="", video_path=None):
        if self._stream_body is not None and self._stream_body.winfo_exists():
            for w in self._stream_body.winfo_children():
                w.destroy()
            if caption:
                ctk.CTkLabel(self._stream_body, text=caption, font=("Inter", 14), justify="left",
                             text_color=COLORS["text"], wraplength=self.CHAT_WRAP).pack(anchor="w", pady=(0, 6))
            for u in (urls or []):
                self._render_image_thumb(self._stream_body, u)
            if video_path:
                ctk.CTkButton(self._stream_body, text="▶ Open video", fg_color=COLORS["primary"],
                              hover_color=COLORS["primary_hover"],
                              command=lambda p=video_path: webbrowser.open(p)).pack(anchor="w", pady=4)
        self._stream_label = None
        self._stream_body = None
        self._sync_store()
        self._scroll_chat_bottom()

    def _chat_error(self, err):
        msg = f"⚠️ Error: {err}"
        if self._stream_body is not None and self._stream_body.winfo_exists():
            for w in self._stream_body.winfo_children():
                w.destroy()
            ctk.CTkLabel(self._stream_body, text=msg, font=("Inter", 13),
                         text_color=COLORS["error"], wraplength=self.CHAT_WRAP,
                         justify="left").pack(anchor="w")
        else:
            messagebox.showerror("Czat", msg)
        self._stream_label = None
        self._stream_body = None

    def _end_generation(self):
        self._chat_generating = False
        if hasattr(self, "send_btn") and self.send_btn.winfo_exists():
            self.send_btn.configure(state="normal", text="Send")
        if hasattr(self, "stop_btn") and self.stop_btn.winfo_exists():
            self.stop_btn.pack_forget()

    # --- Regeneracja / edycja / eksport ---
    def _regenerate(self):
        if self._chat_generating:
            return
        while self.chat_history and self.chat_history[-1].get("role") == "assistant":
            self.chat_history.pop()
        if not self.chat_history:
            return
        self._sync_store()
        self._rerender_all()
        self._render_message("assistant", "", streaming=True)
        self._begin_generation()
        api_messages = self._build_api_messages()
        threading.Thread(target=self._worker_chat, args=(api_messages,), daemon=True).start()

    def _edit_user_message(self, idx):
        if self._chat_generating:
            return
        if idx < 0 or idx >= len(self.chat_history):
            return
        raw = self._content_to_text(self.chat_history[idx].get("content", ""))
        raw = re.sub(r'\n?📎.*$', '', raw, flags=re.DOTALL).strip()
        self.chat_history = self.chat_history[:idx]
        self._sync_store()
        self._rerender_all()
        try:
            self.chat_input.delete("1.0", "end")
            self.chat_input.insert("1.0", raw)
            self._grow_input()
            self.chat_input.focus_set()
        except Exception:
            pass

    def _export_markdown(self):
        if not self.chat_history:
            messagebox.showinfo("Export", "The conversation is empty.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".md",
                                            filetypes=[("Markdown", "*.md"), ("Tekst", "*.txt")],
                                            initialfile="conversation.md")
        if not path:
            return
        c = self.chats.get_active()
        out = [f"# {c['title'] if c else 'Rozmowa'}", ""]
        for m in self.chat_history:
            who = "**You**" if m.get("role") == "user" else "**Grok**"
            out.append(f"### {who}")
            out.append("")
            out.append(self._content_to_text(m.get("content", "")))
            out.append("")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(out))
            messagebox.showinfo("Export", f"Saved:\n{path}")
        except Exception as e:
            messagebox.showerror("Export", str(e))


    def build_history_view(self):
         # Redesigned history tab
        self.hist_scroll = ctk.CTkScrollableFrame(self.content_left, fg_color="transparent")
        self.hist_scroll.pack(fill="both", expand=True)
        entries = self.history_mgr.get_entries()
        for idx, entry in enumerate(entries):
            row = ctk.CTkFrame(self.hist_scroll, fg_color="#161b30", corner_radius=10, border_width=1, border_color="#2d3748")
            row.pack(fill="x", pady=5, padx=5)
            ctk.CTkLabel(row, text=entry["timestamp"][:16], font=FONTS["mono"], text_color=COLORS["text_secondary"]).pack(side="left", padx=15)
            ctk.CTkLabel(row, text=entry["prompt"], font=FONTS["body"], wraplength=500).pack(side="left", padx=15, pady=10)
            ctk.CTkButton(row, text="Open", width=80, fg_color=COLORS["primary"], command=lambda u=entry["url"]: webbrowser.open(u)).pack(side="right", padx=15)

    def build_placeholder_view(self):
        ctk.CTkLabel(self.content_left, text="Feature Coming Soon", font=FONTS["h2"]).pack(pady=100)

    def build_settings_view(self):
        frame = ctk.CTkFrame(self.content_left, fg_color="#161b30", corner_radius=15, border_width=1, border_color="#2d3748")
        frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        ctk.CTkLabel(frame, text="Application Settings", font=FONTS["h1"]).pack(pady=(30, 10))
        ctk.CTkLabel(frame, text="Everything is powered by the official xAI API (Grok).",
                     font=FONTS["body"], text_color=COLORS["text_secondary"]).pack(pady=5)

        # --- xAI Account (logowanie OAuth, jak Hermes / grok-cli) ---
        account_box = ctk.CTkFrame(frame, fg_color="#1c233a", corner_radius=12)
        account_box.pack(fill="x", padx=40, pady=20)

        ctk.CTkLabel(account_box, text="xAI Account (SuperGrok / X Premium+)",
                     font=("Inter", 14, "bold")).pack(anchor="w", padx=20, pady=(15, 5))

        if self.oauth.is_authenticated():
            acc = self.oauth.get_account()
            who = acc.get("email") or acc.get("preferred_username") or acc.get("sub") or "zalogowano"
            ctk.CTkLabel(account_box, text=f"✓ Signed in as: {who}", font=FONTS["body"],
                         text_color=COLORS["success"]).pack(anchor="w", padx=20, pady=(0, 10))
            ctk.CTkButton(account_box, text="Sign out", width=120, fg_color="#ef4444", hover_color="#dc2626",
                          command=self.on_account_button).pack(anchor="w", padx=20, pady=(0, 15))
        else:
            ctk.CTkLabel(account_box, text="Sign in via your browser to use account models (incl. Grok Build) without an API key.",
                         font=FONTS["body"], text_color=COLORS["text_secondary"], wraplength=600,
                         justify="left").pack(anchor="w", padx=20, pady=(0, 10))
            ctk.CTkButton(account_box, text="🔐 Sign in with xAI account", width=220, fg_color="#7c3aed",
                          hover_color="#6d28d9", command=self.start_oauth_login).pack(anchor="w", padx=20, pady=(0, 15))

        # Output Folder Section
        folder_box = ctk.CTkFrame(frame, fg_color="#1c233a", corner_radius=12)
        folder_box.pack(fill="x", padx=40, pady=20)
        
        ctk.CTkLabel(folder_box, text="Generation Output Folder", font=("Inter", 14, "bold")).pack(anchor="w", padx=20, pady=(15, 5))
        
        self.path_entry = ctk.CTkEntry(folder_box, width=400, fg_color="#1e293b", border_width=0)
        self.path_entry.insert(0, self.history_mgr.get_save_path())
        self.path_entry.pack(side="left", padx=20, pady=(0, 20), fill="x", expand=True)
        
        ctk.CTkButton(folder_box, text="Browse", width=80, fg_color="#334155", 
                      command=self.change_output_folder).pack(side="right", padx=20, pady=(0, 20))

        # Info
        info_box = ctk.CTkFrame(frame, fg_color="#1c233a", corner_radius=12)
        info_box.pack(fill="x", padx=40, pady=10)
        
        ctk.CTkLabel(info_box, text="Auto-save is enabled. Media will be stored in the selected folder.",
                     font=FONTS["body"]).pack(padx=20, pady=20)
        
        ctk.CTkButton(frame, text="New chat (clear current)", fg_color="#ef4444", hover_color="#dc2626",
                      command=self._new_conversation).pack(pady=20)

        ctk.CTkLabel(frame, text="Language: English (US)", font=FONTS["small"]).pack(pady=20)
        ctk.CTkLabel(frame, text="v2.2.0 - Chat: streaming, attachments, system prompt", font=FONTS["small"], text_color=COLORS["text_secondary"]).pack(side="bottom", pady=20)

    def change_output_folder(self):
        new_path = filedialog.askdirectory()
        if new_path:
            self.history_mgr.set_save_path(new_path)
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, new_path)
            messagebox.showinfo("Settings", "Output folder updated successfully!")

if __name__ == "__main__":
    app = AIStudioPro()
    app.mainloop()
