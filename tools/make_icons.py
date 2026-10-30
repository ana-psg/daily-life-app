"""Gera os ícones do Daily Life (PNG e .ico) com o Pillow.

Uso: python tools/make_icons.py
"""

import os

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dailylife", "static", "img")
VIOLET = (113, 82, 240, 255)
WHITE = (255, 255, 255, 255)


def draw(size):
    s = size * 4  # desenha grande e reduz (bordas suaves)
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.24), fill=VIOLET)
    # folha de calendário
    m = s * 0.22
    top = s * 0.27
    d.rounded_rectangle([m, top, s - m, s - m], radius=int(s * 0.08), outline=WHITE, width=int(s * 0.055))
    d.line([m, top + s * 0.14, s - m, top + s * 0.14], fill=WHITE, width=int(s * 0.055))
    for x in (s * 0.37, s * 0.63):
        d.line([x, top - s * 0.07, x, top + s * 0.05], fill=WHITE, width=int(s * 0.06))
    # check
    w = int(s * 0.065)
    pts = [(s * 0.36, s * 0.62), (s * 0.46, s * 0.71), (s * 0.65, s * 0.52)]
    d.line(pts, fill=WHITE, width=w, joint="curve")
    for p in (pts[0], pts[-1]):
        d.ellipse([p[0] - w / 2, p[1] - w / 2, p[0] + w / 2, p[1] + w / 2], fill=WHITE)
    return img.resize((size, size), Image.LANCZOS)


def main():
    os.makedirs(OUT, exist_ok=True)
    for size in (192, 256, 512):
        draw(size).save(os.path.join(OUT, f"icon-{size}.png"))
    big = draw(256)
    big.save(
        os.path.join(ROOT, "icon.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    print("ícones gerados em", OUT)


if __name__ == "__main__":
    main()
