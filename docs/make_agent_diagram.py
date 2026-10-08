"""Build the 'Inside the agent' diagram: transparent SVG + 2x PNG, dark and light.

Same recipe and look as make_diagram.py (hand-laid-out SVG, transparent
background, semi-transparent cards, headless-Chrome 2x PNG); the helpers are
copied rather than imported because make_diagram.py renders on import.

    python docs/make_agent_diagram.py
    python docs/make_agent_diagram.py --check   # also write proof sheets on white/black
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

THEMES = {
    "dark": dict(
        card="#ffffff0a", edge="#ffffff29", text="#f1f5f9", muted="#a3b2c2",
        dim="#7c8b9c", accent="#38bdf8", cloud="#3fbf9a",
        livekit="#ffffff", python="#4B8BBE", check="#0b1017",
    ),
    "light": dict(
        card="#0f172a08", edge="#0f172a26", text="#0f172a", muted="#475569",
        dim="#64748b", accent="#0369a1", cloud="#0d8a6a",
        livekit="#0f172a", python="#3776AB", check="#ffffff",
    ),
}

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

    def text(x, y, s, size, fill, anchor="middle", extra=""):
        add(f'<text x="{x}" y="{y}" font-size="{size}" fill="{fill}" '
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

    def label(x, y, lines, colour, size=11.5, step=14):
        """Lines stacked upward so the last one sits at y."""
        for i, s in enumerate(lines):
            text(x, y - (len(lines) - 1 - i) * step, s, size, colour)

    add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{MONO}">')
    add('<defs>')
    for mid, colour in (("head", t["accent"]), ("headm", t["muted"]),
                        ("headv", t["cloud"])):
        add(f'''  <marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5"
          markerWidth="6.5" markerHeight="6.5" orient="auto-start-reverse">
    <path d="M0 0.8 L9.2 5 L0 9.2 Z" fill="{colour}"/>
  </marker>''')
    add('</defs>')

    # title
    text(PAD, 46, "Inside the agent", 28, t["text"], "start")
    text(PAD, 74, "voice path and camera path", 15, t["muted"], "start")

    # glasses ------------------------------------------------------------
    gtop, gbot = VY, Y_STEPS + 24
    card(GX, gtop, GW, gbot - gtop)
    gcx = GX + GW / 2
    add(place("glasses", gcx, 318, 46,
              f'fill="none" stroke="{t["accent"]}" stroke-width="1.9" '
              'stroke-linecap="round" stroke-linejoin="round"'))
    text(gcx, 392, "Glasses", 17, t["text"])
    text(gcx, 412, "RayNeo X3 Pro", 12, t["dim"])

    # the WebRTC hop, the one the experiment shapes
    bx1, bx2 = GX + GW + 6, FX - 6
    add(f'<rect x="{bx1}" y="{gtop}" width="{bx2 - bx1}" height="{gbot - gtop}" '
        f'rx="8" fill="{t["accent"]}" fill-opacity="0.07"/>')
    bcx = (bx1 + bx2) / 2
    label(bcx, 318, ["WebRTC via", "LiveKit"], t["accent"], 13, 17)
    label(bcx, 380, ["the experiment's", "variable:", "loss / jitter"],
          t["accent"], 11.5, 15)

    # agent frame ----------------------------------------------------------
    fr = CX0 - 110
    add(f'<rect x="{FX}" y="{FTOP}" width="{fr - FX}" height="{FBOT - FTOP}" '
        f'rx="16" fill="none" stroke="{t["edge"]}" stroke-width="1.4"/>')
    add(place("python", FX + IN + 10, 111, 20, f'fill="{t["python"]}"'))
    text(FX + IN + 30, 127, "Python agent, lab PC", 15, t["text"], "start")
    text(FX + IN, 152, "Voice path", 12, t["dim"], "start", ' letter-spacing="0.6"')
    text(FX + IN, PY - 10, "Camera path", 12, t["dim"],
         "start", ' letter-spacing="0.6"')

    # GPT-Live session
    sx, sy, sw, sh = SESS
    card(sx, sy, sw, sh)
    text(sx + sw / 2, sy + 34, "GPT-Live session", 16, t["text"])
    text(sx + sw / 2, sy + 58, "persona = every step's wording (say)", 12, t["muted"])

    # FrameTap and the brain
    tx0 = FX + IN
    card(tx0, PY, TAP_W, PH)
    text(tx0 + TAP_W / 2, PY + 30, "FrameTap", 16, t["text"])
    text(tx0 + TAP_W / 2, PY + 52, "frames.py", 12, t["dim"])
    text(tx0 + TAP_W / 2, PY + 74, "no frame reaches", 11.5, t["muted"])
    text(tx0 + TAP_W / 2, PY + 90, "GPT-Live", 11.5, t["muted"])
    card(BRAIN_X, PY, BRAIN_W, PH)
    bcx0 = BRAIN_X + BRAIN_W / 2
    text(bcx0, PY + 30, "brain", 16, t["text"])
    text(bcx0, PY + 52, "gpt/brain.py", 12, t["dim"])
    text(bcx0, PY + 74, "per delegation: the next frame + the call so far", 11.5, t["muted"])
    text(bcx0, PY + 90, "→ one vision call → seen, say, step, end_call", 11.5, t["muted"])
    wire([(tx0 + TAP_W + 8, Y_PIPE), (BRAIN_X - 8, Y_PIPE)], t["muted"], "headm")
    text((tx0 + TAP_W + BRAIN_X) / 2, Y_PIPE - 9, "next frame", 11.5, t["muted"])

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
    text(tx + 14, ty + 26, "guides/truck/task.toml", 13, t["text"], "start")
    for j, s in enumerate(["say → voice", "all of it → brain"]):
        text(tx + 14, ty + 50 + j * 18, s, 11.5, t["muted"], "start")
    wire([(400, ty - 2), (400, sy + sh + 4)], t["muted"], "headm", 1.2, dash=True)
    wire([(tx + tw - 30, ty + th + 2), (tx + tw - 30, ty + th + 18), (BRAIN_X + 20, ty + th + 18),
          (BRAIN_X + 20, PY - 4)], t["muted"], "headm", 1.2, dash=True)

    # voice <-> brain
    wire([(X_DELEG, sy + sh + 2), (X_DELEG, PY - 4)], t["muted"], "headm")
    wire([(X_ANSWER, PY - 2), (X_ANSWER, sy + sh + 4)], t["muted"], "headm")
    text(X_ANSWER + 14, 304, "↓ delegation: id + the wearer's words", 11.5, t["muted"], "start")
    text(X_ANSWER + 14, 324, "↑ commentary on that id (the answer)", 11.5, t["muted"], "start")
    text(X_ANSWER + 14, 344, "↑ thinking: the wearer is on step N", 11.5, t["muted"], "start")

    # glasses <-> agent, over WebRTC
    wire([(GX + GW + 2, Y_AUDIO), (sx - 4, Y_AUDIO)], t["accent"], "head", 1.8)
    text(bcx, Y_AUDIO - 8, "mic audio", 11.5, t["accent"])
    wire([(sx - 2, Y_SPEECH), (GX + GW + 4, Y_SPEECH)], t["accent"], "head", 1.8)
    text(bcx, Y_SPEECH - 8, "speech", 11.5, t["accent"])
    wire([(GX + GW + 2, Y_PIPE), (tx0 - 4, Y_PIPE)], t["accent"], "head", 1.8)
    label(bcx, Y_PIPE - 9, ["camera video", "1080p 15 fps"], t["accent"])
    wire([(BRAIN_X + 60, PY + PH + 2), (BRAIN_X + 60, Y_STEPS), (GX + GW + 4, Y_STEPS)],
         t["accent"], "head", 1.8)
    label(bcx, Y_STEPS - 9, ["step list", "(attributes)"], t["accent"])

    # OpenAI cloud ---------------------------------------------------------
    add(f'<rect x="{CX0}" y="{FTOP}" width="{CCW}" height="{FBOT - FTOP}" rx="16" '
        f'fill="none" stroke="{t["cloud"]}" stroke-opacity="0.55" stroke-width="1.4"/>')
    ccx = CX0 + CCW / 2
    text(ccx, 127, "OpenAI cloud", 13.5, t["cloud"], extra=' letter-spacing="0.6"')
    cx1, cw = CX0 + CI, CCW - 2 * CI

    card(cx1, VY, cw, VH, edge=t["cloud"])
    add(place("openai", ccx, VY + 12, 26, f'fill="{t["cloud"]}"'))
    text(ccx, VY + 60, "gpt-live-1", 16, t["text"])
    text(ccx, VY + 77, "GPT-Live", 12, t["dim"])

    vy, vh = Y_PIPE - 40, 80
    card(cx1, vy, cw, vh, edge=t["cloud"])
    text(ccx, vy + 28, "vision model", 15, t["text"])
    text(ccx, vy + 52, "OPENAI_BRAIN_MODEL", 11, t["muted"])

    # agent <-> cloud
    gx_mid = (fr + CX0) / 2
    wire([(sx + sw + 2, Y_WS), (cx1 - 2, Y_WS)], t["cloud"], "headv", 1.8, start=True)
    text((sx + sw + cx1) / 2, Y_WS - 9, "WebSocket", 12.5, t["cloud"], extra=' letter-spacing="0.6"')
    wire([(BRAIN_X + BRAIN_W + 2, Y_PIPE), (cx1 - 3, Y_PIPE)], t["cloud"], "headv", 1.4, start=True)
    text((BRAIN_X + BRAIN_W + cx1) / 2, Y_PIPE - 9, "Responses, JSON", 11.5, t["cloud"])

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
    svg_path = HERE / f"agent-{variant}.svg"
    svg_path.write_text(build(theme), encoding="utf-8")
    png_path = HERE / f"agent-{variant}.png"
    screenshot(svg_path, png_path)
    print("wrote", svg_path.name, "and", png_path.name)

    if "--check" in sys.argv:
        proof = HERE / f"_check-agent-{variant}.png"
        screenshot(svg_path, proof, backdrop=theme["check"])
        print("wrote", proof.name)
