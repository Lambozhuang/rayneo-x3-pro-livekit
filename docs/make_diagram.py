"""Build the architecture diagram: transparent SVG + 2x PNG, dark and light.

Hand-laid-out SVG (no diagram engine), sized tight around its content so it can
be dropped onto a slide at any scale. Backgrounds are transparent, so two colour
variants ship: `-dark` for dark decks, `-light` for light ones. Card fills are
semi-transparent, which keeps them readable over any nearby backdrop tone.

Icons come from docs/icons/, fetched from simple-icons (brand marks, CC0) and
lucide (the glasses glyph, ISC); their inner markup is inlined so the SVG is
self-contained.

    python docs/make_diagram.py
    python docs/make_diagram.py --check   # also write proof sheets on white/black

The PNGs are headless-Chrome screenshots, so they render identically everywhere;
README links them and keeps the SVGs as source.
"""

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).parent
ICONS = HERE / "icons"

MONO = "JetBrains Mono, Cascadia Mono, Consolas, monospace"

# geometry ----------------------------------------------------------------
PAD = 40           # canvas margin
CW, CH = 262, 226  # card
GAP = 100          # between cards — must clear the widest link label
ROW_Y = 116        # top of the card row
W = PAD * 2 + CW * 4 + GAP * 3
H = ROW_Y + CH + PAD

THEMES = {
    "dark": dict(
        card="#ffffff0a", edge="#ffffff29", text="#f1f5f9", muted="#a3b2c2",
        dim="#7c8b9c", accent="#38bdf8", gemini="#a78bda",
        livekit="#ffffff", python="#4B8BBE", check="#0b1017",
    ),
    "light": dict(
        card="#0f172a08", edge="#0f172a26", text="#0f172a", muted="#475569",
        dim="#64748b", accent="#0369a1", gemini="#6d4fa3",
        livekit="#0f172a", python="#3776AB", check="#ffffff",
    ),
}


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
    add(f'''<defs>
  <marker id="head" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
    <path d="M0 0.8 L9.2 5 L0 9.2 Z" fill="{t["accent"]}"/>
  </marker>
  <marker id="headv" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
    <path d="M0 0.8 L9.2 5 L0 9.2 Z" fill="{t["gemini"]}"/>
  </marker>
</defs>''')

    # title
    add(f'<text x="{PAD}" y="46" font-size="28" fill="{t["text"]}">'
        'Architecture</text>')
    add(f'<text x="{PAD}" y="74" font-size="15" fill="{t["muted"]}">'
        'RayNeo X3 Pro live AI assistant</text>')

    glasses = (f'fill="none" stroke="{t["accent"]}" stroke-width="1.9" '
               'stroke-linecap="round" stroke-linejoin="round"')
    nodes = [
        ("glasses", glasses, 48, "RayNeo X3 Pro", "android/",
         ["publishes mic + camera,", "plays the agent's voice"]),
        ("livekit", f'fill="{t["livekit"]}"', 40, "livekit-server",
         "self-hosted", ["one room, forwards", "tracks between peers"]),
        ("python", f'fill="{t["python"]}"', 44, "Python agent", "agent/",
         ["joins the room, bridges", "it to Gemini Live"]),
        ("googlegemini", f'fill="{t["gemini"]}"', 42, "Gemini Live API",
         "Google cloud", ["speech-to-speech,", "video in"]),
    ]
    cols = [PAD + i * (CW + GAP) for i in range(4)]

    for x, (name, style, size, title, sub, lines) in zip(cols, nodes):
        cx = x + CW / 2
        edge = t["gemini"] if name == "googlegemini" else t["edge"]
        add(f'<rect x="{x}" y="{ROW_Y}" width="{CW}" height="{CH}" rx="11" '
            f'fill="{t["card"]}" stroke="{edge}" stroke-width="1.4"/>')
        add(place(name, cx, ROW_Y + 26, size, style))
        add(f'<text x="{cx}" y="{ROW_Y + 111}" font-size="19.5" '
            f'fill="{t["text"]}" text-anchor="middle">{title}</text>')
        add(f'<text x="{cx}" y="{ROW_Y + 134}" font-size="13" '
            f'fill="{t["dim"]}" text-anchor="middle">{sub}</text>')
        for i, line in enumerate(lines):
            add(f'<text x="{cx}" y="{ROW_Y + 168 + i * 22}" font-size="13.5" '
                f'fill="{t["muted"]}" text-anchor="middle">{line}</text>')

    link_y = ROW_Y + CH / 2
    for i, (label, colour, marker) in enumerate([
        ("WebRTC", t["accent"], "head"),
        ("WebRTC", t["accent"], "head"),
        ("WebSocket", t["gemini"], "headv"),
    ]):
        x1, x2 = cols[i] + CW + 12, cols[i + 1] - 12
        add(f'<line x1="{x1}" y1="{link_y}" x2="{x2}" y2="{link_y}" '
            f'stroke="{colour}" stroke-width="1.8" '
            f'marker-start="url(#{marker})" marker-end="url(#{marker})"/>')
        add(f'<text x="{(x1 + x2) / 2}" y="{link_y - 14}" font-size="13.5" '
            f'letter-spacing="0.6" fill="{colour}" text-anchor="middle">'
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


def screenshot(svg: Path, png: Path, backdrop: str = "transparent") -> None:
    """2x PNG of an SVG. backdrop='transparent' keeps the alpha channel."""
    if not CHROME:
        raise SystemExit("no Chrome/Edge found — SVGs written, PNGs skipped")
    with tempfile.TemporaryDirectory() as tmp:
        wrap = Path(tmp) / "wrap.html"
        wrap.write_text(
            '<!doctype html><meta charset="utf-8">'
            "<style>html,body{margin:0;background:%s}"
            "img{display:block;width:%dpx;height:%dpx}</style>"
            '<img src="%s">' % (backdrop, W, H, svg.as_uri()),
            encoding="utf-8",
        )
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--force-device-scale-factor=2", f"--window-size={W},{H}",
             "--default-background-color=00000000",
             f"--screenshot={png}", wrap.as_uri()],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            env={**os.environ, "CHROME_LOG_FILE": os.devnull},
        )


for variant, theme in THEMES.items():
    svg_path = HERE / f"architecture-{variant}.svg"
    svg_path.write_text(build(theme), encoding="utf-8")
    png_path = HERE / f"architecture-{variant}.png"
    screenshot(svg_path, png_path)
    print("wrote", svg_path.name, "and", png_path.name)

    if "--check" in sys.argv:
        # proof sheet: the transparent art over the tone it's meant for
        proof = HERE / f"_check-{variant}.png"
        screenshot(svg_path, proof, backdrop=theme["check"])
        print("wrote", proof.name)
