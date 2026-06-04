"""Generuje appicon.ico — prosta, nowoczesna ikona (iskra na tle indygo).
Uruchom raz przed budową: `python make_icon.py`.
"""
import math
from PIL import Image, ImageDraw

SIZE = 256
img = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# Tło: zaokrąglony kwadrat w kolorze akcentu (indigo #6366f1)
pad = 6
d.rounded_rectangle([pad, pad, SIZE - pad, SIZE - pad], radius=58, fill=(99, 102, 241, 255))

# Iskra (czteroramienna gwiazda) — biała, na środku
c = SIZE / 2
R = 82   # promień ramion (na osiach)
r = 26   # promień wcięć (na przekątnych)
pts = []
for i in range(8):
    rad = R if i % 2 == 0 else r
    ang = math.radians(-90 + 45 * i)  # start: ramię do góry
    pts.append((c + rad * math.cos(ang), c + rad * math.sin(ang)))
d.polygon(pts, fill=(255, 255, 255, 255))

# Mały akcentowy błysk w prawym górnym rogu
d.polygon([(188, 70), (196, 86), (212, 94), (196, 102), (188, 118),
           (180, 102), (164, 94), (180, 86)], fill=(224, 231, 255, 255))

img.save("appicon.ico", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("Zapisano appicon.ico")
