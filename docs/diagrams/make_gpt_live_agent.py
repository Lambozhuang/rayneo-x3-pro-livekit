"""Build the GPT-Live path's agent architecture diagram: the three parts inside the agent (the GPT-Live session, the
eyes, the consult), the lines between them, and what each connection carries. SVG + 2x PNG, white background.

Written for a technical reader: components and mechanisms by the names the code gives them (GPT-Live session, eyes,
consult, commentary, words, set_progress), each connection labelled with what it carries and its key figures. Sized
for a slide: a slide shrinks the figure to the screen's width, so the type is set large against the figure's width and
long explanations wrap rather than widen it. Same recipe as make_gpt_live_overview.py (hand-laid-out SVG,
headless-Chrome 2x PNG); the helpers are copied rather than imported because that script renders on import.

    python docs/diagrams/make_gpt_live_agent.py
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

# one palette for both figures: dark text, slate lines and borders, blue for the link under test; every hop
# between machines sits on a band of its own, blue for the one under test, grey for the others
THEME = dict(
    background="#ffffff", card="#ffffff", frame="#f8fafc", edge="#cbd5e1", text="#0f172a", body="#334155",
    muted="#64748b", accent="#0369a1", band="#0369a1", hop="#64748b", api="#475569", api_edge="#94a3b8", python="#3776AB", livekit="#000000",
)

# type scale ----------------------------------------------------------------
T_TITLE, T_SUB = 30, 17          # figure title, subtitle
T_CARD = 21                      # a card's name
T_ROW = 16                       # rows inside a card, mechanism names
T_LABEL = 15                     # what a connection carries
LEAD = 21                        # between the lines of one row
ROW_GAP = 8                      # added between rows

# geometry ----------------------------------------------------------------
PAD = 28
GAP = 8                                          # around the band: glasses | band | agent
INSET = 16                                       # inside the agent frame
LINK = 204                                       # from a card to its model API card

GX, GW = PAD, 132                                # glasses card
BX1 = GX + GW + GAP                              # the WebRTC hop under test
BX2 = BX1 + 190
LX, LW = BX2 + GAP, 150                          # livekit-server: every connection to the glasses goes through it
LOOP = 92                                        # livekit-server to the agent frame: loopback on our server
NET = GAP                                        # the internet band stands this far off the frame and the API cards
FX, FY = LX + LW + LOOP, 104                     # agent frame
CX, CW = FX + INSET, 560                         # the three cards
FW = CW + 2 * INSET
INDENT = 16                                      # the rows sit this far in from the card's name
TERM = 150                                       # the explanation column inside a card, after the functions
BETWEEN = 122                                    # between two cards: room for the lines and their tags

SESSION = [
    ("Conversation", ["full-duplex speech with the wearer, the", "steps in its prompt; takes audio only"]),
    ("Instructor", ["gives each step as brick and place, answers", "what the steps and the conversation answer"]),
    ("Facts to words", ["puts the eyes' lines into speech: \"yep, that's", "the one\", \"good, that's step one\", \"hmm, not quite\""]),
]
EYES = [
    ("Reading", ["the newest frame, every 0.7 s with a hand at", "work, 2 s still, at once on words; 7 typed answers"]),
    ("Rules", ["two readings agreeing: the brick in the hand,", "the step done, a brick placed but not right, a doubt"]),
    ("Progress", ["records the steps built right (set_progress),", "updates the step list on the glasses"]),
    ("Words", ["sorts the wearer's words: about the scene", "or in dispute, to the consult; the picture, shown"]),
]
CONSULT = [
    ("Ask", ["one request with the frame, the step, the eyes'", "reading, the last lines, and the question"]),
    ("Answer", ["one sentence for the voice: what is wrong and", "how to fix it, or the answer; may move the progress"]),
]


def card_height(rows) -> float:
    """The card's name, then every line of every row, with the gap between rows."""
    lines = sum(len(r[1]) for r in rows)
    return 48 + lines * LEAD + (len(rows) - 1) * ROW_GAP + 14


SY, SH = FY + 44, card_height(SESSION)           # GPT-Live session card
EY, EH = SY + SH + BETWEEN, card_height(EYES)    # eyes card
QY, QH = EY + EH + BETWEEN, card_height(CONSULT)  # consult card
FH = QY + QH + INSET - FY
GY, GH = SY, QY + QH - SY                        # the glasses card is as tall as the three cards
X_WORDS, X_FACTS = CX + 40, CX + 300             # the lines between the session and the eyes
X_ASK, X_SENT = CX + 40, CX + 300                # the lines between the eyes and the consult
KX, KW, KH = CX + CW + LINK, 250, 92             # model API cards
W, H = int(KX + KW + PAD), int(FY + FH + 24)
Y_AUDIO_UP, Y_AUDIO_DOWN = SY + SH / 2 - 24, SY + SH / 2 + 60
Y_VIDEO, Y_STEPS = EY + EH / 2 - 30, QY + QH / 2


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
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        add(f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" fill="{colour or t["text"]}" '
            f'text-anchor="{anchor}">{s}</text>')

    def box(x, y, w, h, edge=None, fill=None, width=1.3):
        add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="9" fill="{fill or t["card"]}" '
            f'stroke="{edge or t["edge"]}" stroke-width="{width}"/>')

    def wire(points, colour, marker, both=False):
        d = "M" + " L".join(f"{x} {y}" for x, y in points)
        ms = f' marker-start="url(#{marker})"' if both else ""
        add(f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="1.8" '
            f'stroke-linejoin="round"{ms} marker-end="url(#{marker})"/>')

    def component(y, title, rows, sub=None):
        """A card's name, then one row per function: the function on the left, what it does on the right."""
        text(CX + 20, y + 34, title, T_CARD, "start", weight=600)
        if sub:
            text(CX + 20 + len(title) * 12.5 + 10, y + 34, sub, T_LABEL, "start", t["muted"])
        ry = y + 48 + LEAD - 4
        for term, lines in rows:
            text(CX + 20 + INDENT, ry, term, T_ROW, "start", t["text"], 600)
            for k, line in enumerate(lines):
                text(CX + 20 + INDENT + TERM, ry + k * LEAD, line, T_ROW, "start", t["body"])
            ry += len(lines) * LEAD + ROW_GAP

    def tag(x, y, term, lines):
        """A mechanism's name in bold, what it carries below it."""
        text(x, y, term, T_ROW, "start", weight=600)
        for k, line in enumerate(lines):
            text(x, y + 20 + k * 19, line, T_LABEL, "start", t["body"])

    def label(cx, y, lines, colour=None):
        """What a connection carries, the last line just above it."""
        for k, line in enumerate(lines):
            text(cx, y - 10 - (len(lines) - 1 - k) * 19, line, T_LABEL, colour=colour or t["body"])

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

    text(PAD, 46, "GPT-Live path: agent architecture", T_TITLE, "start", weight=600)
    text(PAD, 78, "GPT-Live speaks; the eyes read the frame through the Decisions API and state the facts; "
                  "the brain's model is consulted for the words that take judgement", T_SUB, "start", t["muted"])

    # glasses and the hop under test
    box(GX, GY, GW, GH)
    gcx = GX + GW / 2
    add(place("glasses", gcx, GY + GH / 2 - 64, 54,
              f'fill="none" stroke="{t["accent"]}" stroke-width="1.9" '
              'stroke-linecap="round" stroke-linejoin="round"'))
    text(gcx, GY + GH / 2 + 22, "Glasses", T_CARD, weight=600)
    text(gcx, GY + GH / 2 + 48, "RayNeo X3 Pro", T_LABEL, colour=t["body"])
    text(gcx, GY + GH / 2 + 68, "Android app", T_LABEL, colour=t["body"])
    add(f'<rect x="{BX1}" y="{GY}" width="{BX2 - BX1}" height="{GH}" rx="6" '
        f'fill="{t["band"]}" fill-opacity="0.06"/>')
    bcx = (BX1 + BX2) / 2
    band_y = (SY + SH + EY) / 2 + 2
    text(bcx, band_y, "WebRTC over Wi-Fi", T_ROW, colour=t["accent"], weight=600)
    text(bcx, band_y + 22, "the link under test", T_LABEL, colour=t["accent"])

    # the agent
    box(FX, FY, FW, FH, fill=t["frame"])
    add(place("python", FX + INSET + 10, FY + 12, 22, f'fill="{t["python"]}"'))
    text(FX + INSET + 30, FY + 30, "Python agent · LiveKit Agents · our server", T_LABEL, "start", t["muted"], 600)
    box(CX, SY, CW, SH)
    component(SY, "GPT-Live session", SESSION, "the mouth")
    box(CX, EY, CW, EH)
    component(EY, "Eyes", EYES, "gpt/eyes.py")
    box(CX, QY, CW, QH)
    component(QY, "Consult", CONSULT, "gpt/consult.py")

    # session <-> eyes
    y1, y2 = SY + SH + 6, EY - 6
    ym = (y1 + y2) / 2 - 14
    wire([(X_WORDS, y1), (X_WORDS, y2)], t["muted"], "headm")
    wire([(X_FACTS, y2), (X_FACTS, y1)], t["muted"], "headm")
    tag(X_WORDS + 12, ym, "words", ["the wearer's turn as text,", "sorted by what it asks:", "scene, dispute, picture, placed, other"])
    tag(X_FACTS + 12, ym, "commentary", ["a line of facts, spoken: \"the blue one,",
                                         "in your hand\", \"1 of 5 steps done\",",
                                         "\"on the plate but not in its place yet\""])

    # eyes <-> consult
    y1, y2 = EY + EH + 6, QY - 6
    ym = (y1 + y2) / 2 - 14
    wire([(X_ASK, y1), (X_ASK, y2)], t["muted"], "headm")
    wire([(X_SENT, y2), (X_SENT, y1)], t["muted"], "headm")
    tag(X_ASK + 12, ym, "ask", ["a brick placed wrong, a question", "about the desk, \"I placed it\";", "a few a call"])
    tag(X_SENT + 12, ym, "one sentence", ["\"one column too far right, move it", "left\", spoken by the voice after", "\"hmm, not quite\""])

    # livekit-server, the SFU between the glasses and the agent: it forwards the media and the attributes as they
    # are, and holds a WebRTC connection of its own to each side
    box(LX, GY, LW, GH)
    lcx = LX + LW / 2
    add(place("livekit", lcx, GY + GH / 2 - 60, 40, f'fill="{t["livekit"]}"'))
    text(lcx, GY + GH / 2 + 18, "livekit-server", T_ROW + 2, weight=600)
    text(lcx, GY + GH / 2 + 44, "SFU: forwards", T_LABEL, colour=t["body"])
    text(lcx, GY + GH / 2 + 64, "without decoding", T_LABEL, colour=t["body"])
    lb1, lb2 = LX + LW + GAP, FX - GAP
    add(f'<rect x="{lb1}" y="{GY}" width="{lb2 - lb1}" height="{GH}" rx="6" fill="{t["hop"]}" fill-opacity="0.08"/>')
    loop_cx = (lb1 + lb2) / 2
    text(loop_cx, band_y, "WebRTC", T_LABEL, colour=t["muted"], weight=600)
    text(loop_cx, band_y + 20, "loopback", T_LABEL, colour=t["muted"])

    # glasses <-> livekit-server <-> agent: each connection in two legs, labelled on the one under test
    gx1, lx0, lx1, cx0 = GX + GW + 4, LX - 4, LX + LW + 4, CX - 6
    lx = (gx1 + lx0) / 2
    for y, lines, to_agent in ((Y_AUDIO_UP, ["mic audio, Opus + RED", "~75 kbps while speaking"], True),
                               (Y_AUDIO_DOWN, ["agent speech, Opus + RED", "~125 kbps while speaking"], False),
                               (Y_VIDEO, ["video, H.265", "1080x1920, 15 fps, ~4 Mbps;", "the eyes and the consult take", "the newest frame"], True),
                               (Y_STEPS, ["step list (attributes),", "a step's picture when asked"], False)):
        if to_agent:
            wire([(gx1, y), (lx0, y)], t["accent"], "head")
            wire([(lx1, y), (cx0, y)], t["muted"], "headm")
        else:
            wire([(cx0, y), (lx1, y)], t["muted"], "headm")
            wire([(lx0, y), (gx1, y)], t["accent"], "head")
        label(lx, y, lines)

    # model APIs, across the internet
    nb1, nb2 = FX + FW + NET, KX - NET
    add(f'<rect x="{nb1}" y="{GY}" width="{nb2 - nb1}" height="{GH}" rx="6" fill="{t["hop"]}" fill-opacity="0.08"/>')
    ncx = (nb1 + nb2) / 2
    text(ncx, GY + 26, "internet", T_LABEL, colour=t["muted"], weight=600)
    for line_y, title, sub, above, below in (
        (SY + SH / 2, "gpt-live-1", "OpenAI Live API", ["audio, session events"], "WebSocket"),
        (EY + EH / 2, "gpt-6-luna", "OpenAI Decisions API", ["the frame, 7 questions,", "typed answers back, ~0.4 s"], "HTTPS, 2 requests a frame"),
        (QY + QH / 2, "gpt-6.1-terra", "OpenAI Responses API", ["the frame and the question,", "one sentence back, ~1.3 s"], "WebSocket"),
    ):
        y, h = line_y - KH / 2, KH
        box(KX, y, KW, h, t["api_edge"], width=1.5)
        add(place("openai", KX + 32, y + h / 2 - 15, 30, f'fill="{t["text"]}"'))
        text(KX + 60, y + h / 2 - 4, title, T_ROW + 2, "start", weight=600)
        text(KX + 60, y + h / 2 + 19, sub, T_LABEL, "start", t["body"])
        wire([(CX + CW + 6, line_y), (KX - 6, line_y)], t["api"], "headv", both=True)
        label(ncx, line_y, above)
        text(ncx, line_y + 22, below, T_LABEL, colour=t["muted"])

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


svg_path = HERE / "gpt-live-agent.svg"
svg_path.write_text(build(THEME), encoding="utf-8")
png_path = HERE / "gpt-live-agent.png"
screenshot(svg_path, png_path)
print("wrote", svg_path.name, "and", png_path.name)
