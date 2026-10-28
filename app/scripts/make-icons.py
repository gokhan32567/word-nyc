#!/usr/bin/env python3
"""App icon (1024x1024, no transparency) and launch splash for the iPhone app, from icons/icon-512.png.

  python3 app/scripts/make-icons.py
"""
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "icons" / "icon-512.png"
ASSETS = ROOT / "app" / "ios" / "App" / "App" / "Assets.xcassets"
NAVY = (13, 18, 48)

icon = Image.open(SRC).convert("RGB").resize((1024, 1024), Image.LANCZOS)
icon = icon.filter(ImageFilter.UnsharpMask(radius=2, percent=60, threshold=2))
icon.save(ASSETS / "AppIcon.appiconset" / "AppIcon-512@2x.png", optimize=True)
icon.save(ROOT / "app" / "store" / "app-icon-1024.png", optimize=True)

# Launch screen: the icon art centered on navy (aspect-fill crops the edges on phones).
splash = Image.new("RGB", (2732, 2732), NAVY)
art = Image.open(SRC).convert("RGB").resize((600, 600), Image.LANCZOS)
mask = Image.new("L", art.size, 0)
from PIL import ImageDraw  # noqa: E402
ImageDraw.Draw(mask).rounded_rectangle((0, 0, 599, 599), radius=134, fill=255)
splash.paste(art, ((2732 - 600) // 2, (2732 - 600) // 2), mask)
for name in ("splash-2732x2732.png", "splash-2732x2732-1.png", "splash-2732x2732-2.png"):
    splash.save(ASSETS / "Splash.imageset" / name, optimize=True)
print("icons written")
