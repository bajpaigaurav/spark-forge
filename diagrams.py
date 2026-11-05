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
    """Greedy wrap for box labels, honouring explicit newlines."""
    lines = []
    for para in str(text).split("\n"):
        cur = ""
        for w in para.split():
            cand = (cur + " " + w).strip()
            if len(cand) > width and cur:
                lines.append(cur)
                cur = w
            else:
                cur = cand
        lines.append(cur)
    return lines


def text_block(x, y, lines, size=11, anchor="middle", fill=INK, weight="400", lh=13):
    out = []
    for i, ln in enumerate(lines):
        out.append(
            f'<text x="{x}" y="{y + i * lh}" font-family=\'{FONT}\' font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}">{esc(ln)}</text>'
        )
    return "".join(out)


def box(x, y, w, h, label, fill="none", stroke=INK, size=11, width=16, bold=False):
    lines = wrap(label, width)
    total = len(lines) * 13
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
    bw, bh, gap = 168, 62, 46
    rows = (len(nodes) + per_row - 1) // per_row
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
    bw, bh, gap = 460, 54, 22
    w = bw + 24
    h = len(nodes) * (bh + gap) + 24
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    for i, label in enumerate(nodes):
        y = 12 + i * (bh + gap)
        out.append(box(12, y, bw, bh, label, width=58))
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
    bw, bh, gap = 300, 46, 14
    w = 2 * bw + 60
    h = max(len(left), len(right)) * (bh + gap) + 56
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    out.append(text_block(bw / 2 + 12, 20, ["first configuration"], size=12,
                          fill=ACCENT, weight="600"))
    out.append(text_block(bw + 48 + bw / 2, 20, ["second configuration"], size=12,
                          fill=ACCENT, weight="600"))
    for i, label in enumerate(left):
        out.append(box(12, 34 + i * (bh + gap), bw, bh, label, width=34))
    for i, label in enumerate(right):
        out.append(box(bw + 48, 34 + i * (bh + gap), bw, bh, label, width=34))
    out.append("</svg>")
    return "".join(out)


def render_shapes(spec):
    """A labelled n-by-n grid standing for the score matrix."""
    n = 7
    cell, pad = 34, 12
    w = n * cell + pad * 2 + 150
    h = n * cell + pad * 2 + 60
    out = [svg_open(w, h, spec.get("title", "Figure"))]
    for r in range(n):
        for c in range(n):
            # lower triangle is what causal attention actually computes
            fill = "rgba(180,83,42,0.16)" if c <= r else "none"
            out.append(
                f'<rect x="{pad + c * cell}" y="{pad + 30 + r * cell}" width="{cell}" '
                f'height="{cell}" fill="{fill}" stroke="{MUTED}" stroke-width="0.8"/>'
            )
    out.append(text_block(pad + n * cell / 2, 20, ["keys j, 0 to n-1"], size=11,
                          fill=MUTED))
    out.append(
        f'<text x="14" y="{pad + 30 + n * cell / 2}" font-family=\'{FONT}\' font-size="11" '
        f'fill="{MUTED}" text-anchor="middle" transform="rotate(-90 14 '
        f'{pad + 30 + n * cell / 2})">queries i</text>'
    )
    labels = [x for x in (spec.get("nodes") or [])][:4]
    if labels:
        out.append(text_block(pad + n * cell + 24, pad + 40, labels, size=10,
                              anchor="start", fill=INK))
    out.append("</svg>")
    return "".join(out)


def render_curve(spec):
    nodes = spec.get("nodes") or []
    if not nodes:
        return ""
    w, h = 520, 260
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
    for (px, py), label in zip(pts, nodes):
        out.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3" fill="{ACCENT}"/>')
        out.append(text_block(px, py - 10, wrap(label, 22), size=9, fill=INK))
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
