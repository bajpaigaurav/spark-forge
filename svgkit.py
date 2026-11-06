#!/usr/bin/env python3
"""Shared drawing layer for the book's figures.

Every figure in this book is inline SVG with no script: it prints, it survives a reader
with JS off, and it inherits the page's colours from CSS variables. That last part is why
nothing here carries a literal colour. The marks read --color-ink, --color-muted,
--color-rule, --color-accent and --color-sheet, so a figure flips with the page's theme
instead of sitting in a light box on a dark page.

Two rules shaped the module:

1. Every label is measured before it is placed. Character counts are a poor proxy for
   rendered width -- the old renderer used them and let long identifiers run out of their
   boxes. `text_width()` is the single place that decides how wide a string is, and every
   wrap and every viewBox size goes through it.

2. A figure's label size is derived from the width it will actually render at, not picked
   per shape kind. A wide flow figure and a narrow one then land at the same on-screen
   size, which is what makes the set look like one set.
"""
import html

# The prose column a figure lands in. Font sizes are authored in viewBox units and
# scaled to this, so a 900-unit figure and a 600-unit one render the same size.
RENDER_WIDTH = 700
TARGET_PX = 14.0

# Conservative average advance for the sans stack this book uses. Wrapping and viewBox
# sizing both read it, so it is the one number that decides whether a label fits.
CHAR_EM = 0.55

FONT_DISPLAY = "'Hanken Grotesk', ui-sans-serif, system-ui, sans-serif"
FONT_MONO = "'IBM Plex Mono', ui-monospace, monospace"

INK = "var(--color-ink, #1a1d24)"
MUTED = "var(--color-muted, #5a6070)"
RULE = "var(--color-rule, #b8bcc4)"
ACCENT = "var(--color-accent, #8a3324)"
SHEET = "var(--color-sheet, #f2f1ed)"

# Tints of the one accent. SVG has no colour-mix, so these are fixed low-alpha washes
# over whatever the sheet is; they read the same in light and dark.
WASH = "rgba(138, 51, 36, 0.10)"
WASH_2 = "rgba(138, 51, 36, 0.20)"
WASH_3 = "rgba(138, 51, 36, 0.34)"


def esc(s):
    return html.escape(str(s), quote=True)


def size_for(viewbox_width, target_px=TARGET_PX):
    """Authored font size that renders at `target_px` in the prose column."""
    return round(target_px * viewbox_width / RENDER_WIDTH, 1)


def text_width(s, size):
    """Rendered width of one line, in user units."""
    return len(str(s)) * size * CHAR_EM


def wrap_px(text, size, max_px):
    """Greedy wrap that keeps every line inside `max_px` rendered units.

    A word longer than the measure is broken rather than left on one line: leaving it
    whole is what let long identifiers push past the viewBox.
    """
    limit = max(1, int(max_px / (size * CHAR_EM)))
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split():
            while len(word) > limit:
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(word[:limit])
                word = word[limit:]
            cand = (cur + " " + word).strip()
            if len(cand) > limit and cur:
                lines.append(cur)
                cur = word
            else:
                cur = cand
        lines.append(cur)
    return lines


def widest(lines, size):
    return max((text_width(ln, size) for ln in lines), default=0)


class Canvas:
    """Accumulates SVG marks and knows the box they fit in."""

    def __init__(self, width, height, title):
        self.w = width
        self.h = height
        self.title = title
        self.parts = []
        self.defs = [
            '<marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
            f'markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{MUTED}"/></marker>',
            '<marker id="arrow-accent" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
            f'markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{ACCENT}"/></marker>',
        ]

    def add(self, markup):
        self.parts.append(markup)

    def text(self, x, y, s, size, anchor="middle", fill=INK, weight="400",
             family=FONT_DISPLAY, cls="", rotate=None):
        attrs = f'x="{x:.2f}" y="{y:.2f}"'
        if rotate is not None:
            attrs += f' transform="rotate({rotate} {x:.2f} {y:.2f})"'
        c = f' class="{cls}"' if cls else ""
        return (f'<text {attrs} font-family="{family}" font-size="{size}" '
                f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{c}>'
                f'{esc(s)}</text>')

    def block(self, x, y, lines, size, anchor="middle", fill=INK, weight="400",
              family=FONT_DISPLAY, lh=None, cls="", rotate=None):
        """A wrapped block; y is the baseline of its first line."""
        lh = lh or round(size * 1.2)
        return "".join(self.text(x, y + i * lh, ln, size, anchor=anchor, fill=fill,
                                 weight=weight, family=family, cls=cls, rotate=rotate)
                       for i, ln in enumerate(lines))

    def note_lines(self, s, size, max_px):
        return len(wrap_px(s, size, max_px))

    def block_centered(self, x, y_mid, lines, size, **kw):
        """A wrapped block centred on y_mid as a whole, not on its first baseline."""
        lh = kw.get("lh") or round(size * 1.2)
        total = len(lines) * lh
        first = y_mid - total / 2 + size * 0.72
        return self.block(x, first, lines, size, **kw)

    def rect(self, x, y, w, h, fill="none", stroke=INK, sw=1.2, rx=0, cls="", dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        c = f' class="{cls}"' if cls else ""
        return (f'<rect x="{x:.2f}" y="{y:.2f}" width="{w:.2f}" height="{h:.2f}" '
                f'rx="{rx}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"{d}{c}/>')

    def line(self, x1, y1, x2, y2, stroke=MUTED, sw=1.2, dash=None, arrow=False,
             accent=False):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        marker = ""
        if arrow:
            marker = ' marker-end="url(#arrow-accent)"' if accent else ' marker-end="url(#arrow)"'
        return (f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" '
                f'stroke="{stroke}" stroke-width="{sw}"{d}{marker}/>')

    def path(self, d, stroke=MUTED, sw=1.2, fill="none", dash=None, arrow=False,
             accent=False):
        ds = f' stroke-dasharray="{dash}"' if dash else ""
        marker = ""
        if arrow:
            marker = ' marker-end="url(#arrow-accent)"' if accent else ' marker-end="url(#arrow)"'
        return (f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"'
                f'{ds}{marker}/>')

    def circle(self, cx, cy, r, fill=ACCENT, stroke="none", sw=0):
        return (f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" fill="{fill}" '
                f'stroke="{stroke}" stroke-width="{sw}"/>')

    def bracket(self, x1, x2, y, tick=6, label=None, size=11, above=True):
        """A measure bracket: a line with end ticks, label above or below its middle."""
        out = [self.line(x1, y, x2, y, stroke=MUTED, sw=1),
               self.line(x1, y - tick, x1, y + tick, stroke=MUTED, sw=1),
               self.line(x2, y - tick, x2, y + tick, stroke=MUTED, sw=1)]
        if label:
            ly = y - 6 if above else y + size + 4
            out.append(self.text((x1 + x2) / 2, ly, label, size, fill=MUTED))
        return "".join(out)

    def caption(self, x, y, s, size=11, fill=MUTED, anchor="start"):
        return self.text(x, y, s, size, anchor=anchor, fill=fill)

    def note(self, x, y, s, size, max_px):
        """A one- or two-line note wrapped to the figure's measure, so it never
        runs past the viewBox the way a fixed caption did."""
        lines = wrap_px(s, size, max_px)
        return self.block(x, y, lines, size, anchor="start", fill=MUTED)

    def render(self):
        w, h = int(-(-self.w // 1)), int(-(-self.h // 1))
        head = (f'<svg class="fig-svg" viewBox="0 0 {w} {h}" width="100%" role="img" '
                f'aria-label="{esc(self.title)}" xmlns="http://www.w3.org/2000/svg">'
                f'<defs>{"".join(self.defs)}</defs><title>{esc(self.title)}</title>')
        return head + "".join(self.parts) + "</svg>"


def arrow_between(c, x1, y1, x2, y2, dashed=False, accent=False):
    """A straight connector with a marker, kept clear of both boxes."""
    return c.line(x1, y1, x2, y2, stroke=ACCENT if accent else MUTED,
                  dash="4 3" if dashed else None, arrow=True, accent=accent)
