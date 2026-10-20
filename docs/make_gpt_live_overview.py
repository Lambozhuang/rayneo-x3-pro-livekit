"""Build the GPT-Live path's deployment diagram: where each component runs and what each hop crosses. SVG + 2x PNG,
white background.

Hand-laid-out SVG (no diagram engine), sized tight around its content so it can
be dropped onto a slide at any scale. Same look as make_gpt_live_agent.py.

Icons come from docs/icons/, fetched from simple-icons (brand marks, CC0) and
lucide (the glasses glyph, ISC); their inner markup is inlined so the SVG is
self-contained.

    python docs/make_gpt_live_overview.py

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

SANS = "Segoe UI, Inter, Helvetica Neue, Arial, sans-serif"

# the palette of make_gpt_live_agent.py
THEME = dict(
    background="#ffffff", card="#ffffff", frame="#f8fafc", edge="#cbd5e1", text="#0f172a", body="#334155",
    muted="#64748b", accent="#0369a1", hop="#64748b", api="#475569", api_edge="#94a3b8", livekit="#000000", python="#3776AB",
)

# type scale: the agent figure's, sized for a slide ------------------------
T_TITLE, T_SUB = 30, 17          # figure title, subtitle
T_CARD = 18                      # a component's name
T_LABEL = 15                     # what it is, what a connection carries

# geometry ----------------------------------------------------------------
PAD = 28
INSET = 16                       # inside the server frame
CW, CH = 236, 84                 # a component card
RC = 200                         # the row's centre line
GLX = PAD                        # glasses
SX1 = GLX + CW + 170             # our server: room for the Wi-Fi link's label
LKX = SX1 + INSET                # livekit-server
AGX = LKX + CW + 92              # the agent
SX2 = AGX + CW + INSET
KX = SX2 + 176                   # the model APIs
K1, K2 = RC - 54, RC + 54        # their centre lines
W, H = int(KX + CW + PAD), int(K2 + CH / 2 + 24)


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

    def text(x, y, s, size, anchor="middle", colour=None, weight=400):
        add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{colour or t["text"]}" '
            f'text-anchor="{anchor}">{s}</text>')

    def box(x, y, w, h, edge=None, fill=None, width=1.3):
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill or t["card"]}" '
            f'stroke="{edge or t["edge"]}" stroke-width="{width}"/>')

    def component(x, cy, name, style, size, title, sub, edge=None):
        """A card: the icon on the left, the name and what it is beside it."""
        box(x, cy - CH / 2, CW, CH, edge, width=1.5 if edge else 1.3)
        add(place(name, x + 34, cy - size / 2, size, style))
        text(x + 64, cy - 4, title, T_CARD, "start", weight=600)
        text(x + 64, cy + 20, sub, T_LABEL, "start", t["body"])

    def band(x1, x2, y1, y2, colour):
        """The ground under one hop between machines."""
        add(f'<rect x="{x1}" y="{y1}" width="{x2 - x1}" height="{y2 - y1}" rx="6" fill="{colour}" '
            f'fill-opacity="{0.06 if colour == t["accent"] else 0.08}"/>')

    def link(points, colour, marker, above, below, below_colour=None):
        """A two-way connection: the protocol above its last stretch, the network it crosses below, one line
        each or several."""
        d = "M" + " L".join(f"{x} {y}" for x, y in points)
        add(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="1.8" stroke-linejoin="round" '
            f'marker-start="url(#{marker})" marker-end="url(#{marker})"/>')
        (x1, y), (x2, _) = points[-2], points[-1]
        text((x1 + x2) / 2, y - 10, above, T_LABEL, colour=t["body"])
        for k, line in enumerate([below] if isinstance(below, str) else below):
            text((x1 + x2) / 2, y + 22 + k * 19, line, T_LABEL, colour=below_colour or t["muted"])

    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{SANS}">')
    add(f'<rect width="{W}" height="{H}" fill="{t["background"]}"/>')
    add('<defs>')
    for mid, colour in (("head", t["accent"]), ("headm", t["muted"]), ("headv", t["api"])):
        add(f'''  <marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="5.5" markerHeight="5.5" orient="auto-start-reverse">
    <path d="M0 0.8 L9.2 5 L0 9.2 Z" fill="{colour}"/>
  </marker>''')
    add('</defs>')

    text(PAD, 46, "GPT-Live path: deployment", T_TITLE, "start", weight=600)
    text(PAD, 78, "The glasses and one server on the lab network; only the server reaches the model APIs",
         T_SUB, "start", t["muted"])

    glasses = (f'fill="none" stroke="{t["accent"]}" stroke-width="1.9" '
               'stroke-linecap="round" stroke-linejoin="round"')
    component(GLX, RC, "glasses", glasses, 36, "Glasses", "RayNeo X3 Pro")

    # each hop between machines on a band: blue for the one under test, grey for the others
    xf = SX2 + 32                # where the agent's two links fork
    ftop, fbot = RC - CH / 2 - 44, RC + CH / 2 + INSET
    band(GLX + CW + 8, SX1 - 8, ftop, fbot, t["accent"])
    band(SX2 + 8, KX - 8, ftop, fbot, t["hop"])
    text((xf + KX) / 2, RC + 6, "internet", T_LABEL, colour=t["muted"], weight=600)
    box(SX1, ftop, SX2 - SX1, fbot - ftop, fill=t["frame"])
    band(LKX + CW + 8, AGX - 8, RC - CH / 2, RC + CH / 2, t["hop"])
    text(SX1 + INSET, RC - CH / 2 - 16, "Our server · lab PC", T_LABEL, "start", t["muted"], 600)
    component(LKX, RC, "livekit", f'fill="{t["livekit"]}"', 28, "livekit-server", "SFU, relays the media")
    component(AGX, RC, "python", f'fill="{t["python"]}"', 30, "Python agent", "LiveKit Agents")

    component(KX, K1, "openai", f'fill="{t["text"]}"', 30, "gpt-live-1", "OpenAI", t["api_edge"])
    component(KX, K2, "anthropic", f'fill="{t["text"]}"', 26, "Claude Sonnet 5.5", "Anthropic", t["api_edge"])

    link([(GLX + CW + 6, RC), (LKX - 6, RC)], t["accent"], "head", "WebRTC over Wi-Fi", "the link under test", t["accent"])
    link([(LKX + CW + 6, RC), (AGX - 6, RC)], t["muted"], "headm", "WebRTC", "loopback")
    link([(AGX + CW + 6, RC - 16), (xf, RC - 16), (xf, K1), (KX - 6, K1)], t["api"], "headv",
         "WebSocket", [])
    link([(AGX + CW + 6, RC + 16), (xf, RC + 16), (xf, K2), (KX - 6, K2)], t["api"], "headv",
         "HTTPS", [])

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


svg_path = HERE / "gpt-live-overview.svg"
svg_path.write_text(build(THEME), encoding="utf-8")
png_path = HERE / "gpt-live-overview.png"
screenshot(svg_path, png_path)
print("wrote", svg_path.name, "and", png_path.name)
