"""Build the 'Inside the GPT-Live agent' diagram: SVG + 2x PNG, white background, black text.

Same recipe and look as make_diagram.py (hand-laid-out SVG, headless-Chrome 2x
PNG); the helpers are copied rather than imported because make_diagram.py
renders on import.

    python docs/make_agent_diagram.py
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

# white background, black text; colour only on the lines, the icons and the card edges
THEME = dict(
    background="#ffffff", card="#0f172a08", edge="#0f172a26", text="#000000",
    muted="#475569", accent="#0369a1", cloud="#0d8a6a",
    livekit="#000000", python="#3776AB",
)

# geometry ----------------------------------------------------------------
PAD = 32
W, H = 1302, 686

GX, GW = PAD, 130                 # glasses card
FX = GX + GW + 124                # agent frame
FTOP, FBOT = 100, 654
IN = 20                           # frame inner padding
CX0 = 1110                        # cloud column
CCW = 160
CI = 12                           # cloud card inset

# voice row
VY, VH = 162, 84
SESS = (FX + IN, VY, 294, VH)     # GPT-Live session
Y_AUDIO, Y_SPEECH = 186, 228
Y_WS = VY + VH / 2
Y_COMMENT = 280

# middle band
TASK = (306, 294, 220, 90)
X_DELEG, X_ANSWER = 556, 586      # voice <-> brain wires

# camera row
PY, PH = 418, 120
Y_PIPE = PY + PH / 2
Y_STEPS = 570
Y_VISION = 600

# camera row: FrameTap, brain
TAP_W, BRAIN_X, BRAIN_W = 128, 520, 360


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

    def text(x, y, s, size, anchor="middle", extra=""):
        add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{t["text"]}" '
            f'text-anchor="{anchor}"{extra}>{s}</text>')

    def card(x, y, w, h, edge=None, dash=False):
        d = ' stroke-dasharray="5 4"' if dash else ""
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" '
            f'fill="{t["card"]}" stroke="{edge or t["edge"]}" stroke-width="1.4"{d}/>')

    def wire(points, colour, marker, width=1.6, dash=False, start=False):
        d = "M" + " L".join(f"{x} {y}" for x, y in points)
        dd = ' stroke-dasharray="5 4"' if dash else ""
        ms = f' marker-start="url(#{marker})"' if start else ""
        add(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}" '
            f'stroke-linejoin="round"{dd}{ms} marker-end="url(#{marker})"/>')

    def label(x, y, lines, size=11.5, step=14):
        """Lines stacked upward so the last one sits at y."""
        for i, s in enumerate(lines):
            text(x, y - (len(lines) - 1 - i) * step, s, size)

    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{MONO}">')
    add(f'<rect width="{W}" height="{H}" fill="{t["background"]}"/>')
    add('<defs>')
    for mid, colour in (("head", t["accent"]), ("headm", t["muted"]),
                        ("headv", t["cloud"])):
        add(f'''  <marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
    <path d="M0 0.8 L9.2 5 L0 9.2 Z" fill="{colour}"/>
  </marker>''')
    add('</defs>')

    # title
    text(PAD, 46, "Inside the GPT-Live agent", 28, "start")
    text(PAD, 74, "voice path and camera path", 15, "start")

    # glasses ------------------------------------------------------------
    gtop, gbot = VY, Y_STEPS + 24
    card(GX, gtop, GW, gbot - gtop)
    gcx = GX + GW / 2
    add(place("glasses", gcx, 318, 46,
              f'fill="none" stroke="{t["accent"]}" stroke-width="1.9" '
              'stroke-linecap="round" stroke-linejoin="round"'))
    text(gcx, 392, "Glasses", 17)
    text(gcx, 412, "RayNeo X3 Pro", 12)

    # the WebRTC hop, the one the experiment shapes
    bx1, bx2 = GX + GW + 6, FX - 6
    add(f'<rect x="{bx1}" y="{gtop}" width="{bx2 - bx1}" height="{gbot - gtop}" '
        f'rx="8" fill="{t["accent"]}" fill-opacity="0.07"/>')
    bcx = (bx1 + bx2) / 2
    label(bcx, 318, ["WebRTC via", "LiveKit"], 13, 17)
    label(bcx, 380, ["the experiment's", "variable:", "loss / jitter"], 11.5, 15)

    # agent frame ----------------------------------------------------------
    fr = CX0 - 110
    add(f'<rect x="{FX}" y="{FTOP}" width="{fr - FX}" height="{FBOT - FTOP}" '
        f'rx="16" fill="none" stroke="{t["edge"]}" stroke-width="1.4"/>')
    add(place("python", FX + IN + 10, 111, 20, f'fill="{t["python"]}"'))
    text(FX + IN + 30, 127, "Python agent, lab PC", 15, "start")
    text(FX + IN, 152, "Voice path", 12, "start", ' letter-spacing="0.6"')
    text(FX + IN, PY - 10, "Camera path", 12,
         "start", ' letter-spacing="0.6"')

    # GPT-Live session
    sx, sy, sw, sh = SESS
    card(sx, sy, sw, sh)
    text(sx + sw / 2, sy + 34, "GPT-Live session", 16)
    text(sx + sw / 2, sy + 58, "persona + every step's instructions", 12)

    # FrameTap and the brain
    tx0 = FX + IN
    card(tx0, PY, TAP_W, PH)
    text(tx0 + TAP_W / 2, PY + 30, "FrameTap", 16)
    text(tx0 + TAP_W / 2, PY + 52, "frames.py", 12)
    text(tx0 + TAP_W / 2, PY + 74, "no frame reaches", 11.5)
    text(tx0 + TAP_W / 2, PY + 90, "GPT-Live", 11.5)
    card(BRAIN_X, PY, BRAIN_W, PH)
    bcx0 = BRAIN_X + BRAIN_W / 2
    text(bcx0, PY + 30, "brain", 16)
    text(bcx0, PY + 52, "gpt/brain.py", 12)
    text(bcx0, PY + 74, "per delegation: the newest frame + the call's turns", 11.5)
    text(bcx0, PY + 90, "→ one vision call → a reply, maybe a new progress", 11.5)
    wire([(tx0 + TAP_W + 8, Y_PIPE), (BRAIN_X - 8, Y_PIPE)], t["muted"], "headm")
    text((tx0 + TAP_W + BRAIN_X) / 2, Y_PIPE - 9, "newest frame", 11.5)

    # task file
    tx, ty, tw, th = TASK
    fold = 14
    add(f'<path d="M{tx + 10} {ty} H{tx + tw - fold} L{tx + tw} {ty + fold} '
        f'V{ty + th - 10} Q{tx + tw} {ty + th} {tx + tw - 10} {ty + th} '
        f'H{tx + 10} Q{tx} {ty + th} {tx} {ty + th - 10} V{ty + 10} '
        f'Q{tx} {ty} {tx + 10} {ty} Z" fill="{t["card"]}" stroke="{t["edge"]}" '
        f'stroke-width="1.4"/>')
    add(f'<path d="M{tx + tw - fold} {ty} V{ty + fold} H{tx + tw}" fill="none" '
        f'stroke="{t["edge"]}" stroke-width="1.4"/>')
    text(tx + 14, ty + 26, "guides/&lt;task&gt;/task.toml", 13, "start")
    for j, s in enumerate(["what the wearer hears → voice", "all of it → brain"]):
        text(tx + 14, ty + 50 + j * 18, s, 11.5, "start")
    wire([(400, ty - 2), (400, sy + sh + 4)], t["muted"], "headm", 1.2, dash=True)
    wire([(tx + tw - 30, ty + th + 2), (tx + tw - 30, ty + th + 18), (BRAIN_X + 20, ty + th + 18),
          (BRAIN_X + 20, PY - 4)], t["muted"], "headm", 1.2, dash=True)

    # voice <-> brain
    wire([(X_DELEG, sy + sh + 2), (X_DELEG, PY - 4)], t["muted"], "headm")
    wire([(X_ANSWER, PY - 2), (X_ANSWER, sy + sh + 4)], t["muted"], "headm")
    text(X_ANSWER + 14, 304, "↓ delegation: an id (+ words, sometimes)", 11.5, "start")
    text(X_ANSWER + 14, 324, "↑ commentary on that id (the answer)", 11.5, "start")

    # glasses <-> agent, over WebRTC
    wire([(GX + GW + 2, Y_AUDIO), (sx - 4, Y_AUDIO)], t["accent"], "head", 1.8)
    text(bcx, Y_AUDIO - 8, "mic audio", 11.5)
    wire([(sx - 2, Y_SPEECH), (GX + GW + 4, Y_SPEECH)], t["accent"], "head", 1.8)
    text(bcx, Y_SPEECH - 8, "speech", 11.5)
    wire([(GX + GW + 2, Y_PIPE), (tx0 - 4, Y_PIPE)], t["accent"], "head", 1.8)
    label(bcx, Y_PIPE - 9, ["camera video", "1080p 15 fps"])
    wire([(BRAIN_X + 60, PY + PH + 2), (BRAIN_X + 60, Y_STEPS), (GX + GW + 4, Y_STEPS)],
         t["accent"], "head", 1.8)
    label(bcx, Y_STEPS - 9, ["step list", "(attributes)"])

    # model APIs -----------------------------------------------------------
    add(f'<rect x="{CX0}" y="{FTOP}" width="{CCW}" height="{FBOT - FTOP}" rx="16" '
        f'fill="none" stroke="{t["cloud"]}" stroke-opacity="0.55" stroke-width="1.4"/>')
    ccx = CX0 + CCW / 2
    text(ccx, 127, "model APIs", 13.5, extra=' letter-spacing="0.6"')
    cx1, cw = CX0 + CI, CCW - 2 * CI

    card(cx1, VY, cw, VH, edge=t["cloud"])
    add(place("openai", ccx, VY + 12, 26, f'fill="{t["cloud"]}"'))
    text(ccx, VY + 60, "gpt-live-1", 16)
    text(ccx, VY + 77, "GPT-Live", 12)

    vy, vh = Y_PIPE - 40, 80
    card(cx1, vy, cw, vh, edge=t["cloud"])
    text(ccx, vy + 28, "vision model", 15)
    text(ccx, vy + 50, "BRAIN_MODEL", 11)
    text(ccx, vy + 66, "OpenAI / Anthropic", 11)

    # agent <-> cloud
    gx_mid = (fr + CX0) / 2
    wire([(sx + sw + 2, Y_WS), (cx1 - 2, Y_WS)], t["cloud"], "headv", 1.8, start=True)
    text((sx + sw + cx1) / 2, Y_WS - 9, "WebSocket", 12.5, extra=' letter-spacing="0.6"')
    wire([(BRAIN_X + BRAIN_W + 2, Y_PIPE), (cx1 - 3, Y_PIPE)], t["cloud"], "headv", 1.4, start=True)
    text((BRAIN_X + BRAIN_W + cx1) / 2, Y_PIPE - 9, "one call per look", 11.5)

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


svg_path = HERE / "agent.svg"
svg_path.write_text(build(THEME), encoding="utf-8")
png_path = HERE / "agent.png"
screenshot(svg_path, png_path)
print("wrote", svg_path.name, "and", png_path.name)
