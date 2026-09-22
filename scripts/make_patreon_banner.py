"""Generuje promocyjny baner 16:9 na Patreon z prawdziwym zrzutem ekranu aplikacji.
Wynik: assets/brand/patreon-banner.png (1280x720)."""
import os
import sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOTS = os.path.join(ROOT, "assets", "screenshots")
SHOT_NAME = sys.argv[1] if len(sys.argv) > 1 else "hero.png"
OUT = os.path.join(ROOT, "assets", "brand", "patreon-banner.png")

W, H = 1280, 720


def font(name, size):
    for p in (f"C:/Windows/Fonts/{name}", name):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            continue
    return ImageFont.load_default()


F_WORD = font("segoeuib.ttf", 92)       # wordmark (bold)
F_EYE = font("segoeui.ttf", 16)         # eyebrow
F_TAG = font("segoeui.ttf", 25)         # tagline
F_PILL = font("segoeui.ttf", 20)        # feature pills
F_BADGE = font("segoeuib.ttf", 18)      # badge
F_URL = font("segoeuib.ttf", 23)        # github url
F_SUB = font("segoeui.ttf", 17)         # subline


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_tracked(draw, xy, text, fnt, fill, tracking=0):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking


# --- tlo: pionowy gradient nocnego nieba ---
img = Image.new("RGB", (W, H))
top, bot = (24, 27, 74), (7, 10, 22)
px = img.load()
for y in range(H):
    c = lerp(top, bot, y / H)
    for x in range(W):
        px[x, y] = c

# poswiata (mglawica) - rozmyta elipsa fioletowa
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse((620, 40, 1280, 640), fill=(124, 58, 237, 120))
glow = glow.filter(ImageFilter.GaussianBlur(150))
img = Image.alpha_composite(img.convert("RGBA"), glow)

draw = ImageDraw.Draw(img)

# --- gwiazdy ---
import random
random.seed(7)
for _ in range(70):
    sx, sy = random.randint(0, W), random.randint(0, H)
    r = random.choice([1, 1, 1, 2])
    a = random.randint(70, 200)
    draw.ellipse((sx - r, sy - r, sx + r, sy + r), fill=(255, 255, 255, a))

# --- okno z prawdziwym zrzutem ekranu ---
shot = Image.open(os.path.join(SHOTS, SHOT_NAME)).convert("RGB")
WIN_X, WIN_Y = 60, 178
IMG_W, TITLE_H = 620, 34
IMG_H = round(IMG_W * shot.height / shot.width)   # 349
win = Image.new("RGBA", (IMG_W, TITLE_H + IMG_H), (0, 0, 0, 0))
wd = ImageDraw.Draw(win)
# pasek tytulu (zaokraglone gorne rogi)
wd.rounded_rectangle((0, 0, IMG_W - 1, TITLE_H + 16), radius=16,
                     corners=(True, True, False, False), fill=(20, 26, 60, 255))
# zrzut (zaokraglone dolne rogi)
shot_r = shot.resize((IMG_W - 2, IMG_H), Image.LANCZOS)
mask = Image.new("L", shot_r.size, 0)
ImageDraw.Draw(mask).rounded_rectangle((0, 0, shot_r.width - 1, shot_r.height - 1),
                                       radius=16, corners=(False, False, True, True), fill=255)
win.paste(shot_r, (1, TITLE_H), mask)
# kropki "traffic lights"
for i, col in enumerate([(237, 106, 94), (244, 191, 79), (91, 197, 106)]):
    cx = 26 + i * 20
    wd.ellipse((cx - 6, 11, cx + 6, 23), fill=col)
# ramka
wd.rounded_rectangle((0, 0, IMG_W - 1, TITLE_H + IMG_H - 1), radius=16,
                     outline=(54, 62, 110, 255), width=2)
img.alpha_composite(win, (WIN_X, WIN_Y))

# --- logo (5 promieni + iskra) prawy gorny rog ---
RAYS = [((-18, -26), (-56, 44), (99, 102, 241)),
        ((-9, -30), (-29, 48), (139, 92, 246)),
        ((0, -32), (0, 50), (168, 85, 247)),
        ((9, -30), (29, 48), (59, 130, 246)),
        ((18, -26), (56, 44), (56, 189, 248))]
lcx, lcy, s = 1158, 80, 0.62
for (x1, y1), (x2, y2), col in RAYS:
    draw.line((lcx + x1 * s, lcy + y1 * s, lcx + x2 * s, lcy + y2 * s),
              fill=col, width=4)
star = [(0, -11), (3, -3), (11, 0), (3, 3), (0, 11), (-3, 3), (-11, 0), (-3, -3)]
draw.polygon([(lcx + x * s, lcy - 46 * s + y * s) for x, y in star], fill=(255, 255, 255))

# --- prawa kolumna: tekst ---
RX = 710
draw_tracked(draw, (RX + 2, 196), "AURAVIX STUDIO  ·  NEW RELEASE", F_EYE, (143, 151, 200), tracking=2)

# wordmark "Caelo" - bialy, z gradientowa litera C
WY = 224
draw.text((RX, WY), "Caelo", font=F_WORD, fill=(255, 255, 255))
cw = round(draw.textlength("C", font=F_WORD))
ch = round(draw.textlength("Caelo", font=F_WORD))  # noqa: F841
grad = Image.new("RGB", (W, H))
gp = grad.load()
g1, g2 = (91, 84, 230), (56, 189, 248)
for x in range(W):
    col = lerp(g1, g2, min(1.0, max(0.0, (x - RX) / max(cw, 1))))
    for y in range(H):
        gp[x, y] = col
cmask = Image.new("L", (W, H), 0)
ImageDraw.Draw(cmask).text((RX, WY), "C", font=F_WORD, fill=255)
img.paste(grad, (0, 0), cmask)
draw = ImageDraw.Draw(img)

# tagline
draw.text((RX + 2, 332), "Every mode of Grok — in one desktop app.", font=F_TAG, fill=(174, 183, 218))

# pills
PILLS = [("2K image generation", (168, 85, 247), 296),
         ("15-second video clips", (56, 189, 248), 296),
         ("Grok Build in a real GUI", (139, 92, 246), 320)]
py = 380
for text, dot, pw in PILLS:
    draw.rounded_rectangle((RX, py, RX + pw, py + 42), radius=21,
                           fill=(22, 28, 64), outline=(48, 56, 115), width=1)
    cy = py + 21
    draw.ellipse((RX + 20, cy - 6, RX + 32, cy + 6), fill=dot)
    draw.text((RX + 46, py + 9), text, font=F_PILL, fill=(231, 235, 251))
    py += 54

# badge FREE & OPEN SOURCE
by = py + 4
draw.rounded_rectangle((RX, by, RX + 262, by + 44), radius=22, outline=(56, 189, 248), width=2)
btxt = "FREE & OPEN SOURCE"
bw = sum(draw.textlength(c, font=F_BADGE) + 2 for c in btxt) - 2
draw_tracked(draw, (RX + (262 - bw) / 2, by + 11), btxt, F_BADGE, (92, 203, 248), tracking=2)

# --- stopka ---
draw.line((64, 606, 632, 606), fill=(38, 44, 82), width=1)
draw.text((64, 622), "github.com/AuraVixStudio/caelo", font=F_URL, fill=(210, 218, 242))
draw.text((64, 656), "Sign in with your Grok account or API key  ·  Zero telemetry  ·  Apache-2.0",
          font=F_SUB, fill=(114, 125, 170))

img.convert("RGB").save(OUT, "PNG")
print("saved", OUT, img.size)
