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


def text_width(s, size=11):
    """Rendered width of one line, in user units."""
    return len(str(s)) * size * CHAR_EM


def wrap_px(text, size, max_px):
    """Greedy wrap that keeps every line inside `max_px` rendered units."""
    return wrap(text, max(1, int(max_px / (size * CHAR_EM))))


def widest(lines, size):
    """Width of the widest line in a wrapped block."""
    return max((text_width(ln, size) for ln in lines), default=0)


def text_block(x, y, lines, size=11, anchor="middle", fill=INK, weight="400", lh=13):
    out = []
    for i, ln in enumerate(lines):
        out.append(
            f'<text x="{x}" y="{y + i * lh}" font-family=\'{FONT}\' font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{esc(ln)}</text>'
        )
    return "".join(out)


def box(x, y, w, h, label, fill="none", stroke=INK, size=11, width=None, bold=False,
        pad=10):
    # `width` used to be a character count picked per shape kind, which let a long
    # label run out of its own rect. It is now derived from the rect's inner width.
    lines = wrap_px(label, size, w - 2 * pad) if width is None else wrap(label, width)
    lh = 13
    total = len(lines) * lh
    ty = y + h / 2 - total / 2 + 10
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
    per_row = min(4, len(nodes))
    bw, gap = 168, 46
    rows = (len(nodes) + per_row - 1) // per_row
    # A box must be tall enough for its wrapped label: the old fixed 62 clipped
    # four-line labels at this width. Height is the max over the whole figure so
    # the rows stay aligned.
    bh = max(62, 24 + 13 * max(len(wrap_px(n, 11, bw - 20)) for n in nodes))
    w = per_row * bw + (per_row - 1) * gap + 24
    h = rows * (bh + 46) + 30
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    for i, label in enumerate(nodes):
        r, c = divmod(i, per_row)
        x = 12 + c * (bw + gap)
        y = 16 + r * (bh + 46)
        out.append(box(x, y, bw, bh, label))
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
    bw, gap = 460, 22
    # 58 characters was a guess that happened to fit 460px, but the fixed 54px
    # height then clipped any label that wrapped to three lines. Size the row
    # from the wrapped text instead.
    bh = max(54, 24 + 13 * max(len(wrap_px(n, 11, bw - 20)) for n in nodes))
    w = bw + 24
    h = len(nodes) * (bh + gap) + 24
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    for i, label in enumerate(nodes):
        y = 12 + i * (bh + gap)
        out.append(box(12, y, bw, bh, label))
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
    bh = max(46, 24 + 13 * max(len(wrap_px(n, 11, bw - 20)) for n in nodes))
    w = 2 * bw + 60
    h = max(len(left), len(right)) * (bh + gap) + 56
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    out.append(text_block(bw / 2 + 12, 20, ["first configuration"], size=12,
                          fill=ACCENT, weight="600"))
    out.append(text_block(bw + 48 + bw / 2, 20, ["second configuration"], size=12,
                          fill=ACCENT, weight="600"))
    for i, label in enumerate(left):
        out.append(box(12, 34 + i * (bh + gap), bw, bh, label))
    for i, label in enumerate(right):
        out.append(box(bw + 48, 34 + i * (bh + gap), bw, bh, label))
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
    cell, pad = 34, 12
    gutter = 26          # room for the rotated 'queries i' axis label
    grid_w = n * cell
    grid_x = gutter + pad
    grid_top = 30
    grid_h = n * cell

    labels = list(spec.get("nodes") or [])[:4]
    size = 10
    col_w = 0
    col_lines = []
    if labels:
        # Wrap to a readable measure rather than to whatever is left over. 190px
        # is roughly 34 characters at this size, which keeps each line legible
        # when the figure is scaled down to a phone.
        col_lines = [ln for label in labels for ln in wrap_px(label, size, 190)]
        col_w = widest(col_lines, size)

    gap = 24 if col_lines else 0
    w = grid_x + grid_w + (gap + col_w if col_lines else 0) + pad
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
    out.append(text_block(grid_x + grid_w / 2, 20, ["keys j, 0 to n-1"], size=11,
                          fill=MUTED))
    # The rotated axis label sits in the gutter. Rotating -90 about its anchor
    # turns the text into a vertical run, so the gutter only has to cover one
    # line height (~11px) -- 26px clears it with room to spare.
    axis_x = gutter - 12
    axis_y = grid_top + grid_h / 2
    out.append(
        f'<text x="{axis_x}" y="{axis_y}" font-family=\'{FONT}\' font-size="11" '
        f'fill="{MUTED}" text-anchor="middle" transform="rotate(-90 {axis_x} '
        f'{axis_y})">queries i</text>'
    )
    if col_lines:
        out.append(text_block(grid_x + grid_w + gap, grid_top + 22, col_lines,
                              size=size, anchor="start", fill=INK))
    out.append("</svg>")
    return "".join(out)


def render_curve(spec):
    nodes = spec.get("nodes") or []
    if not nodes:
        return ""
    size = 9
    # Labels sit beside points, and the last point is close to the right edge, so
    # a label centered on it hung past the viewBox (29-roofline's 'batching shifts
    # decode' ran to 550 in a 520-wide box). Wrap to a fixed measure and clamp the
    # anchor into the plot area instead of trusting the point's x.
    max_label_px = 140
    wrapped = [wrap_px(n, size, max_label_px) for n in nodes]
    label_w = max(widest(lines, size) for lines in wrapped)
    margin = 12
    w = max(520, 56 + 2 * (label_w / 2 + margin))
    h = 260
    x0, y0, x1, y1 = 56, 20, w - 24, h - 46
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
        out.append(text_block(f"{cx:.1f}", py - 10, lines, size=size, fill=INK))
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
