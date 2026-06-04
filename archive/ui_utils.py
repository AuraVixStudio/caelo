import tkinter as tk
from pathlib import Path
import customtkinter as ctk
import requests
import io
import webbrowser
from PIL import Image, ImageTk
from datetime import datetime
from config import COLORS, HISTORY_DIR

def download_image(url, size=(300, 300)):
    try:
        data = requests.get(url).content
        img = Image.open(io.BytesIO(data))
        img.thumbnail(size)
        return img, data
    except Exception as e:
        print(f"Error downloading image: {e}")
        return None, None

class ResultCard(ctk.CTkFrame):
    def __init__(self, master, img_obj, raw_data, prompt, mode, save_callback, save_dir, filepath=None, **kwargs):
        super().__init__(master, fg_color=COLORS["background"], corner_radius=12, border_width=1, border_color=COLORS["border"], **kwargs)
        
        photo = ImageTk.PhotoImage(img_obj)
        lbl = ctk.CTkLabel(self, image=photo, text="")
        lbl.image = photo
        lbl.pack(padx=10, pady=(10, 5))
        
        if not filepath:
            # Auto-save logic (only if filepath is not provided)
            filename = f"studio_{mode}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
            save_path = Path(save_dir)
            save_path.mkdir(parents=True, exist_ok=True)
            self.filepath = str(save_path / filename)
            with open(self.filepath, "wb") as f:
                f.write(raw_data)
            # Notify history manager
            save_callback(mode, self.filepath, prompt)
        else:
            self.filepath = filepath
            
        btn = ctk.CTkButton(self, text="Open File", height=28, fg_color=COLORS["border"], hover_color=COLORS["primary"],
                            command=lambda: webbrowser.open(self.filepath))
        btn.pack(pady=(0, 10), padx=10, fill="x")
