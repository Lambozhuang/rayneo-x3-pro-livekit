"""Build the GPT-Live architecture diagram (the Gemini Live architecture has none): SVG + 2x PNG, white background, black text.

Hand-laid-out SVG (no diagram engine), sized tight around its content so it can
be dropped onto a slide at any scale.

Icons come from docs/icons/, fetched from simple-icons (brand marks, CC0) and
lucide (the glasses glyph, ISC); their inner markup is inlined so the SVG is
self-contained.

    python docs/make_diagram.py

The PNG is a headless-Chrome screenshot, so it renders identically everywhere;
README links it and keeps the SVG as source.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ICONS = HERE / "icons"

MONO = "JetBrains Mono, Cascadia Mono, Consolas, monospace"

# geometry ----------------------------------------------------------------
PAD = 40           # canvas margin
CW, CH = 262, 168  # card
GAP = 120          # between cards — must clear the widest link label
ROW_Y = 116        # top of the card row
W = PAD * 2 + CW * 4 + GAP * 3
H = ROW_Y + CH + PAD

# white background, black text; colour only on the lines, the icons and the card edges
THEME = dict(
    background="#ffffff", card="#0f172a08", edge="#0f172a26", text="#000000",
    muted="#475569", accent="#0369a1", cloud="#0d8a6a",
    livekit="#000000", python="#3776AB",
)


def icon(name: str) -> str:
    """Inner markup of an icon SVG, with its own fill/stroke attributes dropped."""
    svg = (ICONS / f"{name}.svg").read_text(encoding="utf-8")
    inner = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    inner = re.sub(r"<title>.*?</title>", "", inner, flags=re.S)
    return inner.strip()


def place(name: str, cx: float, y: float, size: float, style: str) -> str:
    """Icon horizontally centred on cx, top edge at y."""
    s = size / 24
    return (f'<g transform="translate({cx - size / 2},{y}) scale({s:g})" '
            f'{style}>{icon(name)}</g>')


def build(t: dict) -> str:
    out: list[str] = []
    add = out.append

    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{MONO}">')
    add(f'<rect width="{W}" height="{H}" fill="{t["background"]}"/>')
    add(f'''<defs>
  <marker id="head" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
    <path d="M0 0.8 L9.2 5 L0 9.2 Z" fill="{t["accent"]}"/>
  </marker>
  <marker id="headm" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
    <path d="M0 0.8 L9.2 5 L0 9.2 Z" fill="{t["muted"]}"/>
  </marker>
  <marker id="headv" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
    <path d="M0 0.8 L9.2 5 L0 9.2 Z" fill="{t["cloud"]}"/>
  </marker>
</defs>''')

    # title
    add(f'<text x="{PAD}" y="46" font-size="28" fill="{t["text"]}">'
        'GPT-Live architecture</text>')
    add(f'<text x="{PAD}" y="74" font-size="15" fill="{t["text"]}">'
        'RayNeo X3 Pro live AI assistant</text>')

    glasses = (f'fill="none" stroke="{t["accent"]}" stroke-width="1.9" '
               'stroke-linecap="round" stroke-linejoin="round"')
    # each card says what it is and where it runs; what it does is in README
    nodes = [
        ("glasses", glasses, 48, "RayNeo X3 Pro", "on the wearer"),
        ("livekit", f'fill="{t["livekit"]}"', 40, "livekit-server", "our server"),
        ("python", f'fill="{t["python"]}"', 44, "Python agent", "our server"),
        ("openai", f'fill="{t["cloud"]}"', 42, "GPT-Live", "OpenAI cloud"),
    ]
    cols = [PAD + i * (CW + GAP) for i in range(4)]

    for x, (name, style, size, title, sub) in zip(cols, nodes):
        cx = x + CW / 2
        edge = t["cloud"] if name == "openai" else t["edge"]
        add(f'<rect x="{x}" y="{ROW_Y}" width="{CW}" height="{CH}" rx="11" '
            f'fill="{t["card"]}" stroke="{edge}" stroke-width="1.4"/>')
        add(place(name, cx, ROW_Y + 26, size, style))
        add(f'<text x="{cx}" y="{ROW_Y + 111}" font-size="19.5" '
            f'fill="{t["text"]}" text-anchor="middle">{title}</text>')
        add(f'<text x="{cx}" y="{ROW_Y + 134}" font-size="13" '
            f'fill="{t["text"]}" text-anchor="middle">{sub}</text>')

    link_y = ROW_Y + CH / 2
    # protocol above the line, the network it crosses below; the first hop is
    # the one the experiment shapes
    for i, (labels, colour, marker) in enumerate([
        (["WebRTC", "Wi-Fi", "under test"], t["accent"], "head"),
        (["WebRTC", "localhost"], t["muted"], "headm"),
        (["WSS", "internet"], t["cloud"], "headv"),
    ]):
        x1, x2 = cols[i] + CW + 12, cols[i + 1] - 12
        add(f'<line x1="{x1}" y1="{link_y}" x2="{x2}" y2="{link_y}" '
            f'stroke="{colour}" stroke-width="1.8" '
            f'marker-start="url(#{marker})" marker-end="url(#{marker})"/>')
        for label, y, size in zip(labels, (link_y - 14, link_y + 26, link_y + 46),
                                  (13.5, 13.5, 12)):
            add(f'<text x="{(x1 + x2) / 2}" y="{y}" font-size="{size}" '
                f'letter-spacing="0.6" fill="{t["text"]}" text-anchor="middle">'
                f'{label}</text>')

    add("</svg>")
    return "\n".join(out)


CHROME = next(
    (p for p in (
        shutil.which("chrome"),
        shutil.which("chromium"),
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        "/usr/bin/google-chrome",
    ) if p and Path(p).exists()),
    None,
)


def screenshot(svg: Path, png: Path) -> None:
    """2x PNG of an SVG."""
    if not CHROME:
        raise SystemExit("no Chrome/Edge found — SVGs written, PNGs skipped")
    with tempfile.TemporaryDirectory() as tmp:
        wrap = Path(tmp) / "wrap.html"
        wrap.write_text(
            '<!doctype html><meta charset="utf-8">'
            "<style>html,body{margin:0;background:%s}"
            "img{display:block;width:%dpx;height:%dpx}</style>"
            '<img src="%s">' % (THEME["background"], W, H, svg.as_uri()),
            encoding="utf-8",
        )
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=2", f"--window-size={W},{H}",
             f"--screenshot={png}", wrap.as_uri()],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "CHROME_LOG_FILE": os.devnull},
        )


svg_path = HERE / "architecture.svg"
svg_path.write_text(build(THEME), encoding="utf-8")
png_path = HERE / "architecture.png"
screenshot(svg_path, png_path)
print("wrote", svg_path.name, "and", png_path.name)
