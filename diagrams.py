#!/usr/bin/env python3
"""Render the diagram planner's specs as hand-written SVG figures.

Usage:
    python3 diagrams.py            # write site/figures/<id>.svg for every spec
    python3 diagrams.py <chapter>  # one chapter

The planner decided every chapter needs a figure and said which kind. This renders that
kind with a fixed small vocabulary of shapes, so the book's figures look like one set:

    flow        boxes left to right with arrows, wrapping into rows
    layout      boxes stacked in a column, for memory and tensor layout
    comparison  two labelled rows sharing one set of column headers
    shapes      a labelled grid, for an n-by-n matrix
    curve       axes with a plotted polyline and labelled points

Nothing here invents a number: every label comes from the spec, and the spec was told to
use only quantities that appear in the chapter. The figure is inline SVG with no script,
so it prints and survives a reader with JS off.
"""
import html
import json
import os
import sys

import review

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "site", "figures")

INK = "var(--ink)"
MUTED = "var(--muted, #666)"
ACCENT = "var(--accent, #b4532a)"
FONT = '"Nimbus Sans", "Liberation Sans", Helvetica, sans-serif'

# Every figure is rendered into a column of about 816px on a wide screen. To land
# a label at TARGET_PX, the authored size is TARGET_PX * viewBox_width / 816,
# so each renderer derives its own size from the viewBox it actually built.
# Sizing per figure KIND was wrong: layout figures went two-column, their
# viewBox doubled, and their 9-unit labels rendered at 7.5px.
RENDER_WIDTH = 700   # the narrowest column a figure lands in (1280px screen)
TARGET_PX = 14.0

SIZE_WIDE = 15      # fallbacks for callers that want a fixed size
SIZE_NARROW = 11
SIZE_POINT = 11
SIZE_SMALL = 11


def size_for(viewbox_width, target_px=TARGET_PX):
    """Authored font size that renders at `target_px` in the prose column."""
    return round(target_px * viewbox_width / RENDER_WIDTH, 1)


def esc(s):
    return html.escape(str(s), quote=True)


def wrap(text, width):
    """Greedy wrap for box labels, honouring explicit newlines.

    A single word longer than `width` is broken rather than left on one line:
    leaving it whole is what let long identifiers push past the viewBox.
    """
    width = max(1, width)
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for w in para.split():
            while len(w) > width:
                if cur:
                    lines.append(cur)
                    cur = ""
                lines.append(w[:width])
                w = w[width:]
            cand = (cur + " " + w).strip()
            if len(cand) > width and cur:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        lines.append(cur)
    return lines


# The renderer must never emit a label wider than the box it sits in. Character
# counts are a poor proxy for rendered width, so every placement measures the
# string first. 0.55em per character is the conservative average for the
# sans-serif stack this book uses; wrapping and viewBox sizing both read it.
CHAR_EM = 0.55


def text_width(s, size=SIZE_NARROW):
    """Rendered width of one line, in user units."""
    return len(str(s)) * size * CHAR_EM


def wrap_px(text, size, max_px):
    """Greedy wrap that keeps every line inside `max_px` rendered units."""
    return wrap(text, max(1, int(max_px / (size * CHAR_EM))))


def widest(lines, size):
    """Width of the widest line in a wrapped block."""
    return max((text_width(ln, size) for ln in lines), default=0)


def text_block(x, y, lines, size=SIZE_NARROW, anchor="middle", fill=INK, weight="400", lh=None):
    lh = lh or round(size * 1.18)
    out = []
    for i, ln in enumerate(lines):
        out.append(
            f'<text x="{x}" y="{y + i * lh}" font-family=\'{FONT}\' font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{esc(ln)}</text>'
        )
    return "".join(out)


def box(x, y, w, h, label, fill="none", stroke=INK, size=SIZE_NARROW, width=None, bold=False,
        pad=12):
    # `width` used to be a character count picked per shape kind, which let a long
    # label run out of its own rect. It is now derived from the rect's inner width.
    lines = wrap_px(label, size, w - 2 * pad) if width is None else wrap(label, width)
    lh = round(size * 1.18)
    total = len(lines) * lh
    ty = y + h / 2 - total / 2 + size * 0.72
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="4" fill="{fill}" '
        f'stroke="{stroke}" stroke-width="1.2"/>'
        + text_block(x + w / 2, ty, lines, size=size, weight="600" if bold else "400")
    )


def arrow(x1, y1, x2, y2, dashed=False):
    dash = ' stroke-dasharray="4 3"' if dashed else ""
    return (
        f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{MUTED}" '
        f'stroke-width="1.2"{dash} marker-end="url(#arrow)"/>'
    )


def svg_open(w, h, title):
    # Round up: fractional viewBoxes are legal but render blurry at some scales.
    w, h = int(-(-w // 1)), int(-(-h // 1))
    return (
        f'<svg class="fig-svg" viewBox="0 0 {w} {h}" width="100%" role="img" '
        f'aria-label="{esc(title)}" xmlns="http://www.w3.org/2000/svg">'
        f'<defs><marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" '
        f'markerHeight="7" orient="auto"><path d="M0,0 L8,4 L0,8 z" fill="{MUTED}"/>'
        f'</marker></defs>'
        f'<title>{esc(title)}</title>'
    )


def render_flow(spec):
    nodes = spec.get("nodes") or []
    if not nodes:
        return ""
    # Aim for a viewBox near TARGET_W so every flow figure lands at the same
    # on-screen scale. Fewer columns need wider boxes; more columns narrower.
    TARGET_W = 900
    gap = 52
    per_row = max(2, min(4, -(-len(nodes) // 2)))      # 2 rows for <=8 nodes
    if len(nodes) <= 3:
        per_row = len(nodes)
    bw = int((TARGET_W - 24 - (per_row - 1) * gap) / per_row)
    bw = max(150, min(240, bw))
    rows = (len(nodes) + per_row - 1) // per_row
    w = per_row * bw + (per_row - 1) * gap + 24
    # The size is derived from the width this figure actually has, so a wide
    # flow figure and a narrow one both land at the same on-screen size.
    size = size_for(w)
    lh = round(size * 1.18)
    bh = max(72, 2 * 12 + lh * max(len(wrap_px(n, size, bw - 24)) for n in nodes))
    h = rows * (bh + 46) + 30
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    for i, label in enumerate(nodes):
        r, c = divmod(i, per_row)
        x = 12 + c * (bw + gap)
        y = 16 + r * (bh + 46)
        out.append(box(x, y, bw, bh, label, size=size))
        if c < per_row - 1 and i + 1 < len(nodes):
            out.append(arrow(x + bw, y + bh / 2, x + bw + gap, y + bh / 2))
        elif i + 1 < len(nodes):
            # wrap to the next row: down, then back to the left margin
            out.append(
                f'<path d="M{x + bw / 2},{y + bh} L{x + bw / 2},{y + bh + 23} '
                f'L{12 + bw / 2},{y + bh + 23} L{12 + bw / 2},{y + bh + 46}" '
                f'fill="none" stroke="{MUTED}" stroke-width="1.2" marker-end="url(#arrow)"/>'
            )
    out.append("</svg>")
    return "".join(out)


def render_layout(spec):
    nodes = spec.get("nodes") or []
    if not nodes:
        return ""
    # A stack of four or more steps is tall enough that it renders over 900px
    # in the column. Split it into two columns, reading down the first then the
    # second, with a connector between the columns.
    two_col = len(nodes) >= 4
    bw, gap = (420, 26) if two_col else (460, 22)
    w = (2 * bw + 60 + 24) if two_col else (bw + 24)
    size = size_for(w)
    lh = round(size * 1.18)
    bh = max(60, 2 * 12 + lh * max(len(wrap_px(n, size, bw - 24)) for n in nodes))
    if two_col:
        half = (len(nodes) + 1) // 2
        cols = [nodes[:half], nodes[half:]]
        col_h = max(len(cols[0]), len(cols[1])) * (bh + gap) - gap
        h = col_h + 24
        out = [svg_open(w, h, spec.get("title", "Figure"))]
        for ci, col in enumerate(cols):
            ox = 12 + ci * (bw + 60)
            for i, label in enumerate(col):
                y = 12 + i * (bh + gap)
                out.append(box(ox, y, bw, bh, label, size=size))
                if i + 1 < len(col):
                    out.append(arrow(ox + bw / 2, y + bh, ox + bw / 2, y + bh + gap))
        # connector from the foot of column one to the head of column two
        x1 = 12 + bw / 2
        x2 = 12 + bw + 60 + bw / 2
        y1 = 12 + len(cols[0]) * (bh + gap) - gap - bh / 2
        out.append(
            f'<path d="M{x1},{y1} L{x1},{y1 + bh / 2 + 26} L{x2},{y1 + bh / 2 + 26} '
            f'L{x2},{12 + bh / 2}" fill="none" stroke="{MUTED}" stroke-width="1.2" '
            f'marker-end="url(#arrow)"/>'
        )
        out.append("</svg>")
        return "".join(out)
    h = len(nodes) * (bh + gap) + 24
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    for i, label in enumerate(nodes):
        y = 12 + i * (bh + gap)
        out.append(box(12, y, bw, bh, label, size=size))
        if i + 1 < len(nodes):
            out.append(arrow(bw / 2 + 12, y + bh, bw / 2 + 12, y + bh + gap))
    out.append("</svg>")
    return "".join(out)


def render_comparison(spec):
    nodes = spec.get("nodes") or []
    if not nodes:
        return ""
    half = (len(nodes) + 1) // 2
    left, right = nodes[:half], nodes[half:]
    bw, gap = 300, 14
    # Same defect as layout: `width=34` chars was tuned to 300px, but two lines
    # at 46px left the label hanging over the rect's edge. Both grow here.
    w = 2 * bw + 60
    size = size_for(w)
    lh = round(size * 1.18)
    bh = max(56, 2 * 12 + lh * max(len(wrap_px(n, size, bw - 24)) for n in nodes))
    h = max(len(left), len(right)) * (bh + gap) + 56
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    out.append(text_block(bw / 2 + 12, size + 6, ["first configuration"], size=size,
                          fill=ACCENT, weight="600"))
    out.append(text_block(bw + 48 + bw / 2, size + 6, ["second configuration"], size=size,
                          fill=ACCENT, weight="600"))
    top = size + 20
    for i, label in enumerate(left):
        out.append(box(12, top + i * (bh + gap), bw, bh, label, size=size))
    for i, label in enumerate(right):
        out.append(box(bw + 48, top + i * (bh + gap), bw, bh, label, size=size))
    out.append("</svg>")
    return "".join(out)


def render_shapes(spec):
    """A labelled n-by-n grid standing for the score matrix, with a notes column.

    Two panels share one viewBox: the grid on the left, a wrapped label column on
    the right. The old code reserved a flat 150px for the column and then printed
    the labels unwrapped from x=274, so any label longer than 138px ran off the
    right edge (23-logits lost four of its five labels that way). The column width
    is now measured from the wrapped text, and the viewBox is the sum of both.
    """
    n = 7
    cell, pad = 40, 14
    gutter = 30          # room for the rotated 'queries i' axis label
    grid_w = n * cell
    grid_x = gutter + pad
    grid_top = 30
    grid_h = n * cell

    labels = list(spec.get("nodes") or [])[:4]
    # The grid alone fixes a floor width; the notes column adds to it. Solve for
    # a size that renders at TARGET_PX given the final width: start from the
    # grid-only width, wrap at that size, then recompute once. One extra pass is
    # enough because the column width only depends on the size, not on itself.
    size = size_for(grid_x + grid_w + pad)
    col_w = 0
    col_lines = []
    for _ in range(2):
        if labels:
            col_lines = [ln for label in labels for ln in wrap_px(label, size, 220)]
            col_w = widest(col_lines, size)
        gap = 24 if col_lines else 0
        w = grid_x + grid_w + (gap + col_w if col_lines else 0) + pad
        size = size_for(w)

    h = grid_top + grid_h + pad

    out = [svg_open(w, h, spec.get("title", "Figure"))]
    for r in range(n):
        for c in range(n):
            # lower triangle is what causal attention actually computes
            fill = "rgba(180,83,42,0.16)" if c <= r else "none"
            out.append(
                f'<rect x="{grid_x + c * cell}" y="{grid_top + r * cell}" width="{cell}" '
                f'height="{cell}" fill="{fill}" stroke="{MUTED}" stroke-width="0.8"/>'
            )
    small = round(size * 0.92, 1)
    out.append(text_block(grid_x + grid_w / 2, 22, ["keys j, 0 to n-1"], size=small,
                          fill=MUTED))
    # The rotated axis label sits in the gutter. Rotating -90 about its anchor
    # turns the text into a vertical run, so the gutter only has to cover one
    # line height (~11px) -- 26px clears it with room to spare.
    axis_x = gutter - 14
    axis_y = grid_top + grid_h / 2
    out.append(
        f'<text x="{axis_x}" y="{axis_y}" font-family=\'{FONT}\' font-size="{small}" '
        f'fill="{MUTED}" text-anchor="middle" transform="rotate(-90 {axis_x} '
        f'{axis_y})">queries i</text>'
    )
    if col_lines:
        out.append(text_block(grid_x + grid_w + gap, grid_top + 26, col_lines,
                              size=size, anchor="start", fill=INK))
    out.append("</svg>")
    return "".join(out)


def render_curve(spec):
    nodes = spec.get("nodes") or []
    if not nodes:
        return ""
    # Labels sit beside points, and the last point is close to the right edge, so
    # a label centered on it hung past the viewBox (29-roofline's 'batching shifts
    # decode' ran to 550 in a 520-wide box). Wrap to a fixed measure and clamp the
    # anchor into the plot area instead of trusting the point's x.
    margin = 12
    max_label_px = 170
    size = size_for(600)
    wrapped = []
    for _ in range(2):
        wrapped = [wrap_px(n, size, max_label_px) for n in nodes]
        label_w = max(widest(lines, size) for lines in wrapped)
        w = max(600, 64 + 2 * (label_w / 2 + margin))
        size = size_for(w)
    h = 280
    x0, y0, x1, y1 = 64, 22, w - 28, h - 46
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    out.append(f'<line x1="{x0}" y1="{y1}" x2="{x1}" y2="{y1}" stroke="{INK}" stroke-width="1"/>')
    out.append(f'<line x1="{x0}" y1="{y0}" x2="{x0}" y2="{y1}" stroke="{INK}" stroke-width="1"/>')
    pts = []
    for i in range(len(nodes)):
        t = i / max(1, len(nodes) - 1)
        pts.append((x0 + t * (x1 - x0), y1 - (0.08 + 0.84 * t * t) * (y1 - y0)))
    out.append(
        '<polyline fill="none" stroke="%s" stroke-width="2" points="%s"/>'
        % (ACCENT, " ".join(f"{px:.1f},{py:.1f}" for px, py in pts))
    )
    for (px, py), lines in zip(pts, wrapped):
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{ACCENT}"/>')
        # Clamp the centered anchor so the widest line of this label stays inside.
        half = widest(lines, size) / 2
        cx = min(max(px, half + margin), w - half - margin)
        out.append(text_block(f"{cx:.1f}", py - size, lines, size=size, fill=INK))
    out.append("</svg>")
    return "".join(out)


RENDER = {
    "flow": render_flow,
    "layout": render_layout,
    "comparison": render_comparison,
    "shapes": render_shapes,
    "curve": render_curve,
}


def build(cid):
    spec = review.load_diagram(cid)
    if not spec or not spec.get("needed"):
        return None
    kind = spec.get("kind") or "flow"
    fn = RENDER.get(kind, render_flow)
    svg = fn(spec)
    if not svg:
        return None
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, cid + ".svg")
    open(p, "w", encoding="utf-8").write(svg)
    return p


def main():
    ids = sys.argv[1:] or review.published_ids()
    n = 0
    for cid in ids:
        try:
            p = build(cid)
        except Exception as e:
            print(f"{cid}: ERROR {type(e).__name__}: {e}")
            continue
        if p:
            n += 1
            print(f"{cid}: {os.path.getsize(p)} bytes")
        else:
            print(f"{cid}: no figure")
    print(f"{n} figures written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
