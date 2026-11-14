#!/usr/bin/env python3
"""Render the diagram planner's specs as hand-written SVG figures.

Usage:
    python3 diagrams.py            # write site/figures/<id>.svg for every spec
    python3 diagrams.py <chapter>  # one chapter

The planner decided every chapter needs a figure and said what it should show. The old
renderer had five kinds and every figure came out as boxes with arrows, because that is
what the kinds were. This one draws the mechanism instead: a row of tokens with weights
fanned between them, a score matrix with its real values, a cache that grows across
decode steps, a memory pool drawn to scale, three bit fields that are actually bit
fields. The vocabulary is below; a spec names one in `kind`.

    tokens     a sequence as cells, with attention weights between them
    matrix     a grid of real values with row/column headers, a highlighted row or column
    timeline   steps across the x axis, lanes down the y axis, one lane persistent
    memory     a pool drawn to scale, spans on it, a block table mapping into it
    bits       one bar split into fields, with a scale under it
    bars       aligned horizontal bars with their numbers
    logaxes    a log-log plot with a roof, a diagonal limit, or labelled points
    panels     two aligned panels of the same structure, before and after
    lane       a block diagram with a bypass lane that runs past every stage
    flow       a left-to-right sequence of stages, wrapping into rows
    grid       an n-by-n grid with an axis (the causal score matrix)
    merge_forest  a merge genealogy: bytes at the leaves, each merge a node above them
    vocab_stack  a vocabulary split into its two halves with the shared rows
    vectors    rows as rays from a shared origin, before and after centering
    bus        one persistent lane, sublayers above and below reading and writing it
    wiring     two chains on one shared column grid, so a moved step lines up
    slab       two tensors drawn by depth, one sheet against a materialised stack
    keep       to-scale strips: how much of a sentence reaches the decoder
    mixture    value vectors scaled by their shares, added head to tail

Nothing here invents a number: every label comes from the spec, and the spec was told to
use only quantities that appear in the chapter. The figure is inline SVG with no script,
so it prints and survives a reader with JS off. Colours come from the page's CSS
variables, so a figure flips with the page's theme.
"""
import json
import math
import os
import sys

import review
from svgkit import (ACCENT, FONT_MONO, INK, MUTED, RULE, SHEET, WASH, WASH_2,
                    WASH_3, Canvas, arrow_between, size_for, text_width, widest,
                    wrap_px)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "site", "figures")


# ---------------------------------------------------------------------------
# small helpers shared by the renderers
# ---------------------------------------------------------------------------

def _size(c, base=900):
    return size_for(c.w)


def _fit(spec, base_w, build, min_w=520):
    """Two-pass sizing: build once at a guess, measure, rebuild at the real width.

    Label size depends on the figure's width, and a label's width can depend on its
    size. One extra pass settles it, because after the first pass the wrap is fixed.
    """
    c = build(base_w, size_for(base_w))
    w = max(min_w, c.w)
    if abs(w - base_w) < 1:
        return c
    return build(w, size_for(w))


def _part_at(parts, key, idx):
    """Return the part name for one item in a spec's optional `parts` map."""
    if not parts:
        return None
    seq = parts.get(key)
    if isinstance(seq, str):
        return seq if idx == 0 else None
    if isinstance(seq, list) and idx < len(seq):
        return seq[idx] or None
    return None


def _grp(part, inner):
    """Wrap marks in a part group, or leave them ungrouped when the spec has none."""
    return f'<g data-part="{part}">{inner}</g>' if part else inner


def _cell_part(parts, row, col):
    """Return a per-cell part name, or None when the spec has no cell map."""
    if not parts:
        return None
    grid = parts.get("cells") or []
    if row < len(grid) and col < len(grid[row]):
        return grid[row][col] or None
    return None


# ---------------------------------------------------------------------------
# tokens -- a sequence as cells, with attention between them
# ---------------------------------------------------------------------------

def render_tokens(spec):
    tokens = spec.get("tokens") or []
    if not tokens:
        return None
    weights = spec.get("weights") or []          # [[j, w], ...] or {j: w}
    focus = spec.get("focus")                    # index of the query token
    sublabels = spec.get("sublabels") or []
    note = spec.get("note")

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        cell = min(96, max(56, (w - 2 * pad) / max(1, len(tokens)) - 8))
        gap = 8
        row_w = len(tokens) * cell + (len(tokens) - 1) * gap
        x0 = (w - row_w) / 2
        y = 26
        h = 44
        note_h = 0
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, 14, note, size * 0.86, w - 2 * pad))
            note_h = nl * size * 1.2 + 8
        # the cells
        for i, t in enumerate(tokens):
            x = x0 + i * (cell + gap)
            on = (focus is not None and i == focus)
            c.add(c.rect(x, y, cell, h, fill=WASH_3 if on else "none",
                         stroke=ACCENT if on else INK, sw=1.6 if on else 1.2))
            lines = wrap_px(t, size, cell - 12)
            c.add(c.block_centered(x + cell / 2, y + h / 2, lines, size,
                                   weight="600" if on else "400"))
            if i < len(sublabels):
                c.add(c.text(x + cell / 2, y + h + size + 6, sublabels[i], size * 0.86,
                             fill=MUTED))
        # weights: a fan from the query cell to each weighted token
        if weights and focus is not None:
            qx = x0 + focus * (cell + gap) + cell / 2
            qy = y + h + (size * 1.9 if sublabels else 0)
            base_y = qy + 34
            pairs = weights.items() if isinstance(weights, dict) else weights
            for j, val in pairs:
                j = int(j)
                tx = x0 + j * (cell + gap) + cell / 2
                sw = 0.8 + 4.0 * float(val)
                op = 0.35 + 0.65 * float(val)
                c.add(f'<path d="M{qx:.1f},{qy:.1f} C{qx:.1f},{base_y:.1f} '
                      f'{tx:.1f},{base_y:.1f} {tx:.1f},{y + h + 2:.1f}" '
                      f'fill="none" stroke="{ACCENT}" stroke-width="{sw:.2f}" '
                      f'stroke-opacity="{op:.2f}" stroke-linecap="round"/>')
                c.add(c.text(tx, base_y + size + 2, f"{float(val):.3f}", size * 0.86,
                             fill=ACCENT))
            c.add(c.text(qx, qy + size + 2, "query", size * 0.86, fill=MUTED))
            c.h = base_y + size * 2 + 18
        else:
            c.h = y + h + size * 2 + 18
        return c

    return _fit(spec, 900, build).render()


# ---------------------------------------------------------------------------
# matrix -- a grid of real values with headers and a highlighted row or column
# ---------------------------------------------------------------------------

def render_matrix(spec):
    rows = spec.get("rows") or []
    if not rows:
        return None
    cols = spec.get("cols") or [str(j) for j in range(len(rows[0]))]
    col_head = spec.get("col_head")
    row_head = spec.get("row_head")
    highlight_row = spec.get("highlight_row")
    highlight_col = spec.get("highlight_col")
    note = spec.get("note")
    corner = spec.get("corner")
    scale = spec.get("scale") or 1.0       # 0..1, how much of the cell is inked
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        ncol = len(cols)
        nrow = len(rows)
        row_head_w = text_width(row_head, size * 0.82) if row_head else 0
        left_margin = max(78, row_head_w + 44) if row_head else 78
        cell = min(72, max(34, (w - 2 * pad - left_margin) / max(1, ncol)))
        hcell = max(30, min(cell, 52))
        grid_x = pad + left_margin
        note_h = 0
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, 24, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            note_h = nl * size * 1.2 + 16
        grid_y = 44 + note_h
        for r in range(nrow):
            for k in range(ncol):
                val = rows[r][k] if k < len(rows[r]) else ""
                fill = "none"
                stroke = RULE
                sw = 0.8
                if highlight_row is not None and r == highlight_row:
                    fill = WASH
                    stroke = ACCENT
                    sw = 1.1
                if highlight_col is not None and k == highlight_col:
                    fill = WASH_2 if highlight_row is None or r != highlight_row else WASH_3
                    stroke = ACCENT
                    sw = 1.1
                part = _cell_part(parts, r, k)
                if not part:
                    part = _part_at(parts, "cols", k) or _part_at(parts, "rows", r)
                x = grid_x + k * cell
                y = grid_y + r * hcell
                c.add(c.rect(x, y, cell, hcell, fill=fill, stroke=stroke, sw=sw,
                             part=part))
                if val != "":
                    # a value cell: a proportional ink block plus its number
                    v = float(val) if isinstance(val, (int, float)) else None
                    if v is not None and scale:
                        bh = max(2, min(hcell - 10, (hcell - 10) * v * float(scale)))
                        c.add(c.rect(x + 5, y + hcell - 5 - bh, cell - 10, bh,
                                     fill=ACCENT, stroke="none", rx=0, part=part))
                        c.add(c.text(x + cell / 2, y + 12, f"{v:g}", size * 0.82,
                                     fill=INK, weight="600", part=part))
                    else:
                        c.add(c.text(x + cell / 2, y + hcell / 2 + size * 0.35,
                                     str(val), size * 0.9, part=part))
        # headers
        for k, name in enumerate(cols):
            c.add(c.text(grid_x + k * cell + cell / 2, grid_y - 8, str(name), size * 0.82,
                         fill=MUTED, part=_part_at(parts, "cols", k)))
        for r in range(nrow):
            c.add(c.text(grid_x - 8, grid_y + r * hcell + hcell / 2 + size * 0.3,
                         str(r), size * 0.82, anchor="end", fill=MUTED,
                         part=_part_at(parts, "rows", r)))
        if col_head:
            c.add(c.text(grid_x + ncol * cell / 2, grid_y - 8 - size * 1.5, col_head,
                         size * 0.82, fill=MUTED, part=parts.get("headers")))
        if row_head:
            c.add(c.text(grid_x - 8 - size * 1.6, grid_y + nrow * hcell / 2, row_head,
                         size * 0.82, anchor="middle", fill=MUTED, rotate=-90,
                         part=parts.get("headers")))
        if corner:
            c.add(c.text(grid_x - 8, grid_y - 8, corner, size * 0.82, anchor="end",
                         fill=MUTED, part=parts.get("corner")))
        c.h = grid_y + nrow * hcell + 20
        return c

    return _fit(spec, 900, build).render()


# ---------------------------------------------------------------------------
# timeline -- steps across x, lanes down y, one lane that persists
# ---------------------------------------------------------------------------

def render_timeline(spec):
    steps = spec.get("steps") or []
    if not steps:
        return None
    lanes = spec.get("lanes") or []        # [{name, cells:[step index or None]}]
    note = spec.get("note")
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        label_w = 104
        plot_x = pad + label_w
        plot_w = w - plot_x - pad
        cw = plot_w / max(1, len(steps))
        note_h = 0
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, 24, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            note_h = nl * size * 1.2 + 16
        top = 40 + note_h
        rh = max(38, min(58, 340 / max(1, len(lanes))))
        # step labels along the top
        for i, s in enumerate(steps):
            x = plot_x + i * cw + cw / 2
            lines = wrap_px(s, size * 0.8, cw - 6)
            c.add(c.block_centered(x, top - size * 0.2, lines, size * 0.8,
                                   fill=MUTED, part=_part_at(parts, "steps", i)))
        # lane rows
        for li, lane in enumerate(lanes):
            y = top + li * (rh + 12)
            lane_part = _part_at(parts, "lanes", li)
            c.add(c.text(pad, y + rh / 2 + size * 0.3, lane["name"], size * 0.86,
                         anchor="start", fill=INK, weight="600", part=lane_part))
            c.add(c.line(pad, y + rh + 6, w - pad, y + rh + 6, stroke=RULE, sw=1,
                         part=lane_part))
            for ci, cell in enumerate(lane.get("cells") or []):
                if not cell:
                    # a step with nothing happening in this lane: the baseline
                    # rule carries the lane, no empty box is drawn
                    continue
                x = plot_x + ci * cw
                kind = cell.get("kind", "solid")
                part = _cell_part(parts, li, ci) or lane_part
                # A cell is inked on its accent outline, never on a wash: the
                # washes are fixed alphas over the sheet, and on a dark sheet they
                # vanish. Outline plus label reads at any theme.
                fill = {"waste": "none"}.get(kind, "none")
                stroke = ACCENT if kind in ("solid", "cache", "new") else RULE
                dash = "3 3" if kind == "waste" else None
                c.add(c.rect(x + 1, y, cw - 2, rh, fill=fill, stroke=stroke, sw=1.1,
                             dash=dash, part=part))
                if cell.get("label"):
                    lines = wrap_px(cell["label"], size * 0.82, cw - 8)
                    c.add(c.block_centered(x + cw / 2, y + rh / 2, lines, size * 0.82,
                                           weight="600" if kind == "new" else "400",
                                           part=part))
        c.h = top + len(lanes) * (rh + 12) + 20
        return c

    return _fit(spec, 900, build).render()


# ---------------------------------------------------------------------------
# memory -- a pool drawn to scale, spans on it, a block table mapping into it
# ---------------------------------------------------------------------------

def render_memory(spec):
    total = spec.get("total")
    if not total:
        return None
    spans = spec.get("spans") or []        # [{from, to, label, kind}]
    table = spec.get("table") or {}        # {title, rows: [[logical, physical, ref]]}
    axis = spec.get("axis")                # [{at, label}]
    note = spec.get("note")
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        bar_x = pad
        bar_w = w - 2 * pad
        note_h = 0
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, 24, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            note_h = nl * size * 1.2 + 16
        bar_y = 40 + note_h
        bar_h = 46
        # the pool
        c.add(c.rect(bar_x, bar_y, bar_w, bar_h, fill="none", stroke=INK, sw=1.4))
        # spans: each drawn to scale, with its number inside or under
        for si, s in enumerate(spans):
            span_part = _part_at(parts, "spans", si)
            x1 = bar_x + bar_w * s["from"] / total
            x2 = bar_x + bar_w * s["to"] / total
            kind = s.get("kind", "used")
            fill = {"used": WASH_2, "reserved": WASH, "waste": "none",
                    "free": "none", "share": WASH_3}.get(kind, WASH)
            stroke = ACCENT if kind in ("used", "reserved", "share") else RULE
            dash = "4 3" if kind == "waste" else None
            c.add(c.rect(x1, bar_y, max(1, x2 - x1), bar_h, fill=fill, stroke=stroke,
                         sw=1.1, dash=dash, part=span_part))
            if s.get("label"):
                mid = (x1 + x2) / 2
                if x2 - x1 > text_width(s["label"], size * 0.84) + 8:
                    c.add(c.text(mid, bar_y + bar_h / 2 + size * 0.3, s["label"],
                                 size * 0.84, weight="600", part=span_part))
                elif s.get("label_anchor") == "start":
                    c.add(c.text(x1 + 2, bar_y + bar_h + size + 4, s["label"],
                                 size * 0.84, anchor="start", fill=ACCENT, weight="600",
                                 part=span_part))
                else:
                    c.add(c.text(mid, bar_y + bar_h + size + 4, s["label"], size * 0.84,
                                 fill=ACCENT, weight="600", part=span_part))
        # the axis under the bar
        bottom = bar_y + bar_h + (size * 1.8 if any(s.get("label") for s in spans
                                                    if s["to"] - s["from"] < 0.2 * total)
                                  else size * 1.2)
        c.add(c.line(bar_x, bottom, bar_x + bar_w, bottom, stroke=INK, sw=1))
        for t in (axis or [{"at": 0, "label": "0"}, {"at": total, "label": f"{total:,}"}]):
            x = bar_x + bar_w * t["at"] / total
            c.add(c.line(x, bottom - 4, x, bottom + 4, stroke=INK, sw=1))
            anchor = "start" if t["at"] == 0 else ("end" if t["at"] == total else "middle")
            c.add(c.text(x, bottom + size + 2, str(t["label"]), size * 0.8, anchor=anchor,
                         fill=MUTED))
        c.h = bottom + size * 2 + 10

        # the block table, if there is one: logical entries pointing into the pool
        if table.get("rows"):
            table_part = parts.get("table")
            ty = c.h + 16
            c.add(c.text(pad, ty, table.get("title", ""), size * 0.82, anchor="start",
                         fill=MUTED, part=table_part))
            ty += size + 8
            colw = [56, 56, 56]
            for row in table["rows"]:
                for k, cell in enumerate(row):
                    x = pad + sum(colw[:k])
                    c.add(c.rect(x, ty, colw[k], 24, fill=WASH if k == 2 else "none",
                                 stroke=RULE, sw=0.9, part=table_part))
                    c.add(c.text(x + colw[k] / 2, ty + 16, str(cell), size * 0.82,
                                 weight="600" if k == 2 else "400", part=table_part))
                ty += 28
            c.h = ty + 8
        return c

    return _fit(spec, 900, build).render()


# ---------------------------------------------------------------------------
# bits -- one bar split into fields, with a scale under it
# ---------------------------------------------------------------------------

def render_bits(spec):
    fields = spec.get("fields") or []      # [{name, bits, note}]
    if not fields:
        return None
    label = spec.get("label")
    caption = spec.get("caption")
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        total_bits = sum(int(f["bits"]) for f in fields)
        bar_x = pad + (64 if label else 0)
        bar_w = w - bar_x - pad
        y = 26
        h = 52
        if label:
            c.add(c.text(pad, y + h / 2 + size * 0.3, label, size * 0.86,
                         anchor="start", fill=INK, weight="600"))
        acc = 0
        for fi, f in enumerate(fields):
            n = int(f["bits"])
            field_part = _part_at(parts, "fields", fi)
            x1 = bar_x + bar_w * acc / total_bits
            x2 = bar_x + bar_w * (acc + n) / total_bits
            # one accent for the exponent, a neutral wash for sign and mantissa
            # The accent marks the exponent field in a wash; every field keeps an
            # ink outline so the bar reads as one bar split three ways, not as a
            # lone tinted block.
            fill = WASH_3 if f.get("accent") else "none"
            stroke = ACCENT if f.get("accent") else INK
            c.add(c.rect(x1, y, x2 - x1, h, fill=fill, stroke=stroke,
                         sw=1.6 if f.get("accent") else 1.2, part=field_part))
            mid = (x1 + x2) / 2
            field_w = x2 - x1
            # A one-bit field is too narrow for its name: wrapping "sign" would
            # split it into "si"/"gn". Rotate short field names instead, which
            # keeps the label intact inside the bar.
            if field_w < text_width(f["name"], size * 0.84) + 6:
                c.add(c.text(mid, y + h / 2, f["name"], size * 0.78,
                             weight="600", rotate=-90, part=field_part))
            else:
                lines = wrap_px(f["name"], size * 0.84, field_w - 6)
                c.add(c.block_centered(mid, y + h / 2 - (size * 0.5 if f.get("note") else 0),
                                       lines, size * 0.84, weight="600", part=field_part))
            if f.get("note"):
                c.add(c.text(mid, y + h / 2 + size * 0.9, f["note"], size * 0.78,
                             fill=MUTED, part=field_part))
            c.add(c.text(mid, y + h + size + 2, str(n), size * 0.8, fill=ACCENT,
                         weight="600", part=field_part))
            acc += n
        c.h = y + h + size * 2.2
        # a scale of bit indices under the bar
        c.add(c.line(bar_x, c.h - size * 0.8, bar_x + bar_w, c.h - size * 0.8,
                     stroke=RULE, sw=1))
        c.add(c.text(bar_x, c.h + 2, "most significant", size * 0.76, anchor="start",
                     fill=MUTED))
        c.add(c.text(bar_x + bar_w, c.h + 2, "least significant", size * 0.76,
                     anchor="end", fill=MUTED))
        if caption:
            c.h += size * 1.4
            nl = c.note_lines(caption, size * 0.82, w - 2 * pad)
            c.add(c.note(pad, c.h, caption, size * 0.82, w - 2 * pad,
                         part=parts.get("caption")))
            c.h += nl * size * 1.2
        c.h = max(c.h + size * 1.2, 150)
        return c

    return _fit(spec, 760, build).render()


# ---------------------------------------------------------------------------
# bars -- aligned horizontal bars with their numbers
# ---------------------------------------------------------------------------

def render_bars(spec):
    """Aligned horizontal bars with their numbers, optionally in labelled groups.

    Groups matter when the figure is a before-and-after: the point of the softmax example
    is that raising one score sharpens the same three weights, so the two triples have to
    read as two blocks on one scale rather than six unrelated bars.
    """
    groups = spec.get("groups")
    bars = spec.get("bars") or []
    if groups:
        bars = [b for g in groups for b in g.get("bars") or []]
    if not bars:
        return None
    note = spec.get("note")
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        label_w = 172
        plot_x = pad + label_w
        plot_w = w - plot_x - pad - 190
        note_h = 0
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, 14, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            note_h = nl * size * 1.2 + (12 if groups else 10)
        top = 26 + note_h
        vmax = max(float(b["value"]) for b in bars) or 1
        rh = 26
        y = top
        if not groups:
            # Ungrouped specs predate groups; keep their geometry byte-identical.
            for bi, b in enumerate(bars):
                bar_part = _part_at(parts, "bars", bi)
                ll = wrap_px(b["label"], size * 0.86, label_w - 8)
                c.add(c.block(pad, y + rh / 2 - (len(ll) - 1) * size * 0.6 + size * 0.3, ll,
                              size * 0.86, anchor="start", fill=INK, part=bar_part))
                bw = plot_w * float(b["value"]) / vmax
                c.add(c.rect(plot_x, y + 3, max(2, bw), rh - 6,
                             fill=WASH_3 if b.get("accent") else WASH_2,
                             stroke=ACCENT if b.get("accent") else RULE, sw=1,
                             part=bar_part))
                disp = b.get("display", f"{b['value']:g}")
                dl = wrap_px(disp, size * 0.84, w - (plot_x + max(2, bw) + 6) - pad)
                c.add(c.block(plot_x + max(2, bw) + 6,
                              y + rh / 2 - (len(dl) - 1) * size * 0.6 + size * 0.3, dl,
                              size * 0.84, anchor="start", fill=INK, weight="600",
                              part=bar_part))
                y += rh + 8
            c.h = y + 10
            return c
        small = size * 0.86
        tiny = size * 0.74
        lh = round(small * 1.22)
        tlh = round(tiny * 1.22)
        bi = 0
        for gi, g in enumerate(groups):
            if g.get("label"):
                gp = _part_at(parts, "groups", gi)
                c.add(c.line(pad, y, w - pad, y, stroke=RULE, sw=1, part=gp))
                c.add(c.text(pad, y + tlh + 2, g["label"], tiny, anchor="start",
                             fill=ACCENT, weight="600", part=gp))
                y += tlh + 12
            for b in g.get("bars") or []:
                bar_part = _part_at(parts, "bars", bi) or _part_at(parts, "groups", gi)
                bi += 1
                ll = wrap_px(b["label"], small, label_w - 10)
                c.add(c.block(pad, y + rh / 2 - (len(ll) - 1) * lh / 2 + small * 0.34,
                              ll, small, anchor="start", fill=INK, lh=lh,
                              part=bar_part))
                bw = plot_w * float(b["value"]) / vmax
                c.add(c.rect(plot_x, y + 3, max(2, bw), rh - 6,
                             fill=WASH_3 if b.get("accent") else WASH_2,
                             stroke=ACCENT if b.get("accent") else RULE, sw=1,
                             part=bar_part))
                disp = b.get("display", f"{b['value']:g}")
                c.add(c.text(plot_x + max(2, bw) + 8, y + rh / 2 + small * 0.34, disp,
                             size * 0.84, anchor="start", fill=INK, weight="600",
                             part=bar_part))
                y += rh + 8
            y += 10
        c.h = y + 6
        return c

    return _fit(spec, 760, build).render()


# ---------------------------------------------------------------------------
# logaxes -- a log-log plot with a roof, a limit line, or labelled points
# ---------------------------------------------------------------------------

def render_logaxes(spec):
    series = spec.get("series") or []
    if not series:
        return None
    x_label = spec.get("x_label", "")
    y_label = spec.get("y_label", "")
    note = spec.get("note")
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        note_h = 0
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, 14, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            note_h = nl * size * 1.2 + 12
        x0 = pad + 76
        y0 = 26 + note_h + size * 2.2
        x1 = w - pad - 12
        # plot area height: fixed proportion, so every log figure is the same shape
        plot_h = 230
        y1 = y0 + plot_h
        c.add(c.line(x0, y1, x1, y1, stroke=INK, sw=1))
        c.add(c.line(x0, y0, x0, y1, stroke=INK, sw=1))
        # decade gridlines, log10 x from 1 to 1e5, y from 1 to 1e3
        for d in range(0, 5):
            x = x0 + (x1 - x0) * d / 4
            c.add(c.line(x, y0, x, y1, stroke=RULE, sw=0.8, dash="2 3"))
            c.add(c.text(x, y1 + size * 1.5, f"10^{d}", size * 0.78, fill=MUTED))
        for d in range(0, 4):
            y = y1 - (y1 - y0) * d / 3
            c.add(c.line(x0, y, x1, y, stroke=RULE, sw=0.8, dash="2 3"))
            c.add(c.text(x0 - 6, y + size * 0.3, f"10^{d}", size * 0.78, anchor="end",
                         fill=MUTED))
        c.add(c.text((x0 + x1) / 2, y1 + size * 3.6, x_label, size * 0.84, fill=INK))
        c.add(c.text(pad + size * 0.9, (y0 + y1) / 2, y_label, size * 0.84, fill=INK,
                     rotate=-90))

        def sx(v):     # log10 x from 0..4 -> pixel
            return x0 + (x1 - x0) * max(0, min(4, math.log10(max(v, 1e-9)))) / 4

        def sy(v):     # log10 y from 0..3 -> pixel
            return y1 - (y1 - y0) * max(0, min(3, math.log10(max(v, 1e-9)))) / 3

        for si, s in enumerate(series):
            series_part = _part_at(parts, "series", si)
            kind = s.get("kind", "line")
            if kind == "line" and s.get("points"):
                pts = " ".join(f"{sx(px):.1f},{sy(py):.1f}" for px, py in s["points"])
                line = (f'<polyline points="{pts}" fill="none" stroke="{ACCENT}" '
                        f'stroke-width="2.2"/>')
                c.add(c.group(series_part, line) if series_part else line)
            elif kind == "hline" and s.get("y"):
                c.add(c.line(x0, sy(s["y"]), x1, sy(s["y"]), stroke=ACCENT, sw=2.2,
                             part=series_part))
            elif kind == "point" and s.get("x"):
                px, py = sx(s["x"]), sy(s["y"])
                c.add(c.circle(px, py, 4.5, part=series_part))
                label = s.get("label", "")
                lines = wrap_px(label, size * 0.82, 190)
                # the label sits above the point, anchored so it stays inside the
                # plot: a point near the right edge gets a right-aligned label
                lw = widest(lines, size * 0.82)
                if px - lw / 2 < x0 + 4:
                    lx, anchor = px + 10, "start"
                elif px + lw / 2 > x1 - 4:
                    lx, anchor = px - 10, "end"
                else:
                    lx, anchor = px, "middle"
                c.add(c.block(lx, py - size * 1.6, lines, size * 0.82, anchor=anchor,
                              part=series_part))
        # labels for the roofs
        for si, s in enumerate(series):
            series_part = _part_at(parts, "series", si)
            if s.get("label") and s.get("kind") in ("line", "hline"):
                if s["kind"] == "hline":
                    c.add(c.text(x0 + 6, sy(s["y"]) - 6, s["label"], size * 0.82,
                                 anchor="start", fill=ACCENT, part=series_part))
                elif s.get("points"):
                    (ex, ey) = s["points"][-1]
                    c.add(c.text(sx(ex) - 6, sy(ey) - 6, s["label"], size * 0.82,
                                 anchor="end", fill=ACCENT, part=series_part))
        c.h = y1 + size * 4.6
        return c

    return _fit(spec, 760, build).render()


# ---------------------------------------------------------------------------
# panels -- two aligned panels of the same structure
# ---------------------------------------------------------------------------

def render_panels(spec):
    panels = spec.get("panels") or []
    if not panels:
        return None
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        gap = 28
        pw = (w - 2 * pad - gap * (len(panels) - 1)) / len(panels)
        top = 26
        tallest = 0
        item_parts = parts.get("items") or []
        for i, p in enumerate(panels):
            px = pad + i * (pw + gap)
            panel_part = _part_at(parts, "panels", i)
            c.add(c.text(px, top, p.get("title", ""), size * 0.9, anchor="start",
                         fill=ACCENT, weight="600", part=panel_part))
            y = top + size * 1.4
            c.add(c.line(px, y, px + pw, y, stroke=INK, sw=1, part=panel_part))
            y += 10
            for j, item in enumerate(p.get("items") or []):
                item_part = None
                if i < len(item_parts) and j < len(item_parts[i]):
                    item_part = item_parts[i][j]
                if not item_part:
                    item_part = panel_part
                lines = wrap_px(item, size * 0.86, pw - 12)
                hh = max(26, len(lines) * size * 1.2 + 10)
                c.add(c.rect(px, y, pw, hh, fill="none", stroke=RULE, sw=1,
                             part=item_part))
                c.add(c.block_centered(px + pw / 2, y + hh / 2, lines, size * 0.86,
                                       part=item_part))
                y += hh + 8
            if p.get("note"):
                nl = c.note_lines(p["note"], size * 0.82, pw)
                c.add(c.note(px, y + size, p["note"], size * 0.82, pw,
                             part=panel_part))
                y += nl * size * 1.2 + size * 0.5
            tallest = max(tallest, y)
        c.h = max(tallest + 22, 210)
        return c

    return _fit(spec, 900, build).render()


# ---------------------------------------------------------------------------
# lane -- a block diagram with a bypass lane that runs past every stage
# ---------------------------------------------------------------------------

def render_lane(spec):
    stages = spec.get("stages") or []
    if not stages:
        return None
    bypass = spec.get("bypass")           # label of the identity lane
    note = spec.get("note")
    sizes = spec.get("sizes") or []       # structural shape labels under each stage
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        note_h = 0
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, 24, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            note_h = nl * size * 1.2 + 16
        top = 40 + note_h
        gap = 26
        bw = (w - 2 * pad - (len(stages) - 1) * gap) / len(stages)
        bh = 54
        # the bypass lane above the stages: one line, two arrows, no boxes
        bypass_part = parts.get("bypass")
        if bypass:
            by = top + 14
            c.add(c.text(pad, by - 8, bypass, size * 0.84, anchor="start",
                         fill=ACCENT, part=bypass_part))
            c.add(c.path(f"M{pad},{by} L{w - pad},{by}", stroke=ACCENT, sw=1.6,
                         arrow=True, accent=True, part=bypass_part))
        stage_y = top + (46 if bypass else 10)
        for i, s in enumerate(stages):
            x = pad + i * (bw + gap)
            stage_part = _part_at(parts, "stages", i)
            c.add(c.rect(x, stage_y, bw, bh, fill="none", stroke=INK, sw=1.2,
                         part=stage_part))
            lines = wrap_px(s, size, bw - 12)
            c.add(c.block_centered(x + bw / 2, stage_y + bh / 2, lines, size,
                                   weight="600", part=stage_part))
            if i < len(sizes):
                sl = wrap_px(sizes[i], size * 0.8, bw - 4)
                c.add(c.block_centered(x + bw / 2, stage_y + bh + size * 0.8 + 8,
                                       sl, size * 0.8, fill=MUTED, part=stage_part))
            if i < len(stages) - 1:
                arrow_between(c, x + bw, stage_y + bh / 2, x + bw + gap, stage_y + bh / 2)
        c.h = max(stage_y + bh + size * 3.4, 200)
        if bypass:
            # the bypass rejoins after the last stage: a short down stub that
            # stops above the size labels rather than running into them
            c.add(c.path(f"M{w - pad},{top + 14} L{w - pad},{stage_y - 6}",
                         stroke=ACCENT, sw=1.6, arrow=True, accent=True,
                         part=bypass_part))
        return c

    return _fit(spec, 900, build).render()


# ---------------------------------------------------------------------------
# flow -- the old fallback, kept for chapters a box sequence genuinely suits
# ---------------------------------------------------------------------------

def render_flow(spec):
    nodes = spec.get("nodes") or []
    if not nodes:
        return None
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        per_row = min(4, max(2, -(-len(nodes) // 2))) if len(nodes) > 3 else len(nodes)
        gap = 34
        bw = (w - 2 * pad - (per_row - 1) * gap) / per_row
        lines_per = [wrap_px(n, size, bw - 16) for n in nodes]
        bh = max(46, max(len(l) for l in lines_per) * size * 1.2 + 18)
        rows = -(-len(nodes) // per_row)
        y = 20
        for i, lines in enumerate(lines_per):
            r, k = divmod(i, per_row)
            x = pad + k * (bw + gap)
            yy = y + r * (bh + 34)
            node_part = _part_at(parts, "nodes", i)
            c.add(c.rect(x, yy, bw, bh, fill="none", stroke=INK, sw=1.2,
                         part=node_part))
            c.add(c.block_centered(x + bw / 2, yy + bh / 2, lines, size,
                                   part=node_part))
            if k < per_row - 1 and i + 1 < len(nodes):
                arrow_between(c, x + bw, yy + bh / 2, x + bw + gap, yy + bh / 2)
            elif i + 1 < len(nodes):
                c.add(c.path(f"M{x + bw / 2},{yy + bh} L{x + bw / 2},{yy + bh + 17} "
                             f"L{pad + bw / 2},{yy + bh + 17} L{pad + bw / 2},{yy + bh + 34}",
                             stroke=MUTED, sw=1.2, arrow=True))
        c.h = y + rows * (bh + 34) + 10
        return c

    return _fit(spec, 900, build).render()


# ---------------------------------------------------------------------------
# grid -- an n-by-n causal score matrix with an axis
# ---------------------------------------------------------------------------

def render_grid(spec):
    n = int(spec.get("n") or 7)
    note = spec.get("note")
    highlight_row = spec.get("highlight_row")
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        gutter = 54
        cell = min(46, max(24, (w - 2 * pad - gutter) / n))
        grid_x = pad + gutter
        note_h = 0
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, 14, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            note_h = nl * size * 1.2 + 10
        top = 26 + note_h
        for r in range(n):
            for k in range(n):
                causal = k <= r
                fill = "none"
                stroke = RULE
                if causal:
                    fill = WASH
                    stroke = ACCENT
                if highlight_row is not None and r == highlight_row and causal:
                    fill = WASH_3
                c.add(c.rect(grid_x + k * cell, top + r * cell, cell, cell, fill=fill,
                             stroke=stroke, sw=0.9, part=_cell_part(parts, r, k)))
        c.add(c.text(grid_x + n * cell / 2, top - 8, "keys j  (causal: j <= i)",
                     size * 0.82, fill=MUTED, part=parts.get("axis")))
        c.add(c.text(pad + size * 0.9, top + n * cell / 2, "queries i", size * 0.82,
                     anchor="middle", fill=MUTED, rotate=-90,
                     part=parts.get("axis")))
        c.add(c.text(grid_x + n * cell / 2, top + n * cell + size * 1.6,
                     "n x n scores; the upper triangle is masked", size * 0.8,
                     fill=MUTED, part=parts.get("axis")))
        c.h = top + n * cell + size * 2.8
        return c

    return _fit(spec, 760, build).render()


def render_vocab_stack(spec):
    data = spec.get("data") or {}
    rows = data.get("rows") or []
    total = data.get("total")
    if not rows or total is None:
        return None
    parts = data.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("alt") or spec.get("caption") or "")
        pad = 24
        label_w = 210
        bar_x = pad + label_w
        bar_w = w - bar_x - pad - 180
        row_h = 42
        gap = 8
        y = 18
        total_h = len(rows) * row_h + (len(rows) - 1) * gap
        for i, (label, count) in enumerate(rows):
            row_part = _part_at(parts, "rows", i)
            yy = y + i * (row_h + gap)
            c.add(c.rect(bar_x, yy, bar_w, row_h,
                         fill=WASH_2 if i == 1 else WASH, stroke=RULE, rx=2,
                         part=row_part))
            c.add(c.text(pad, yy + row_h / 2 + size * 0.35, label, size,
                         anchor="start", fill=INK, weight="500", part=row_part))
            c.add(c.text(bar_x + bar_w + 10, yy + row_h / 2 + size * 0.35,
                         f"{count:,}", size, anchor="start", fill=ACCENT,
                         family=FONT_MONO, weight="600", part=row_part))
        total_part = parts.get("total")
        bx = bar_x + bar_w + 82
        c.add(c.line(bx, y, bx, y + total_h, stroke=MUTED, sw=1, part=total_part))
        c.add(c.line(bx - 5, y, bx + 5, y, stroke=MUTED, sw=1, part=total_part))
        c.add(c.line(bx - 5, y + total_h, bx + 5, y + total_h, stroke=MUTED, sw=1,
                     part=total_part))
        c.add(c.text(bx + 10, y + total_h / 2, f"{total:,} total", size,
                     anchor="start", fill=INK, weight="600", part=total_part))
        arith = " + ".join(f"{count:,}" for _, count in rows) + f" = {total:,}"
        arith_y = y + total_h + 24
        c.add(c.note(pad, arith_y, arith, size * 0.9, w - 2 * pad,
                     part=parts.get("arith")))
        note = ("Rows are schematic: 256 and 1 would be invisible beside 50,000. "
                "Counts are exact.")
        note_y = arith_y + size * 1.5
        c.add(c.note(pad, note_y, note, size * 0.82, w - 2 * pad))
        c.h = note_y + c.note_lines(note, size * 0.82, w - 2 * pad) * size * 1.2 + 14
        return c

    return _fit(spec, 760, build).render()


MONO_EM = 0.62


def _mono_w(s, size):
    """Advance width of a mono label, in user units. Wider than the sans estimate."""
    return len(str(s)) * size * MONO_EM


def render_merge_forest(spec):
    """The merge genealogy: one graph, leaves at the bottom, each merge a node.

    A token is a composition, not a cell. Two children feed every node, so the same
    subtree (`lo`, then `low`) is visibly reused by three words, and the words part
    company at the branch that builds `lowe`.

    Layout is computed, not authored: leaves sit left to right in spec order with room
    for their labels, every merge sits above the midpoint of its children, and the
    viewBox grows to whatever the widest label needs.
    """
    data = spec.get("data") or {}
    nodes = data.get("nodes") or []
    if not nodes:
        return None
    note = data.get("note") or ""

    by_id = {n["id"]: n for n in nodes}
    leaves = [n for n in nodes if not n.get("from")]
    depth = {}

    def depth_of(nid, seen=()):
        if nid in depth:
            return depth[nid]
        n = by_id[nid]
        if not n.get("from"):
            depth[nid] = 0
        elif nid in seen:
            depth[nid] = 0
        else:
            depth[nid] = 1 + max(depth_of(c, seen + (nid,)) for c in n["from"])
        return depth[nid]

    for n in nodes:
        depth_of(n["id"])
    max_depth = max(depth.values()) or 1

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("alt") or spec.get("caption") or "")
        pad = 28
        gap = 16
        level_gap = max(46, size * 4.0)
        r_leaf, r_merge = 3.6, 6.4

        # leaves left to right, each slot as wide as its label
        xs = {}
        cursor = pad
        for n in leaves:
            half = _mono_w(n["label"], size) / 2 + 4
            xs[n["id"]] = cursor + half
            cursor += 2 * half + gap
        # every other node sits over the midpoint of the children that feed it
        for d in range(1, max_depth + 1):
            for n in nodes:
                if depth[n["id"]] == d and n.get("from"):
                    xs[n["id"]] = sum(xs[c] for c in n["from"]) / len(n["from"])
        # the top merge carries a label above it; leave room for that ascender
        top = r_merge + 5 + size * 1.2
        ys = {n["id"]: top + (max_depth - depth[n["id"]]) * level_gap for n in nodes}

        # shift right if a rank badge would run off the left edge
        left = pad
        for n in nodes:
            if n.get("rank") is not None:
                badge = _mono_w(f"r{n['rank']}", size * 0.78)
                left = min(left, xs[n["id"]] - r_merge - 6 - badge)
        shift = max(0.0, pad - left)
        for nid in xs:
            xs[nid] += shift

        # edges first, so every node sits on top of the lines that feed it
        for n in nodes:
            part = n.get("part")
            for child in n.get("from") or []:
                c.add(c.line(xs[child], ys[child], xs[n["id"]], ys[n["id"]],
                             stroke=RULE, sw=1.4, part=part))
        for n in nodes:
            nid = n["id"]
            part = n.get("part")
            x, y = xs[nid], ys[nid]
            leaf = depth[nid] == 0
            r = r_leaf if leaf else r_merge
            c.add(c.circle(x, y, r, fill=MUTED if leaf else ACCENT,
                           stroke=SHEET, sw=1.6, part=part))
            if leaf:
                c.add(c.text(x, y + r + size * 1.25, n["label"], size,
                             fill=MUTED, family=FONT_MONO, cls="mono", part=part))
            else:
                c.add(c.text(x, y - r - 5, n["label"], size, fill=INK,
                             family=FONT_MONO, weight="500", cls="mono",
                             part=part))
                if n.get("rank") is not None:
                    c.add(c.text(x, y + r + size * 1.05, f"r{n['rank']}",
                                 size * 0.78, fill=MUTED, family=FONT_MONO,
                                 cls="mono", part=part))

        # widen for the widest label rather than clipping it
        right = 0.0
        for n in nodes:
            nid = n["id"]
            half = _mono_w(n["label"], size) / 2
            right = max(right, xs[nid] + half)
            if n.get("rank") is not None:
                half = _mono_w(f"r{n['rank']}", size * 0.78) / 2
                right = max(right, xs[nid] + half)
        c.w = max(w, right + pad)

        bottom = max(ys.values()) + r_leaf + size * 1.25
        note_y = bottom + size * 1.7
        if note:
            note_size = size * 0.82
            lines = wrap_px(note, note_size, c.w - 2 * pad)
            lh = round(note_size * 1.5)
            c.add(c.block(pad, note_y, lines, note_size, anchor="start",
                          fill=MUTED, lh=lh))
            c.h = note_y + (len(lines) - 1) * lh + note_size * 1.6 + 12
        else:
            c.h = note_y + 14
        return c

    return _fit(spec, 480, build, min_w=400).render()


# ---------------------------------------------------------------------------
# vectors -- two plots of rays from a shared origin, with the angle between them
# ---------------------------------------------------------------------------

def render_vectors(spec):
    """Rows drawn as rays from a shared origin, before and after centering.

    Both plots use one scale, so a shorter ray really is a shorter vector: subtracting
    the mean shrinks the rows as well as separating them. The arc between the rays is the
    angle cue; its cosine is printed under the plot rather than inside the wedge, because
    two rays that are close together leave no room for text between them.
    """
    plots = spec.get("plots") or []
    if len(plots) < 2:
        return None
    mean = spec.get("mean") or None
    note = spec.get("note") or ""
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        gap = 54
        pw = (w - 2 * pad - gap) / 2
        side = min(pw - 34, 300)
        coords = [v for p in plots for v in p.get("vectors") or []]
        top = max([max(abs(v["x"]), abs(v["y"])) for v in coords] +
                  ([max(abs(mean["x"]), abs(mean["y"]))] if mean else []))
        k = side / (top * 1.18)
        title_size = size * 0.95
        label_size = size * 0.82
        small = size * 0.78
        lh = round(small * 1.45)

        def arc(cx, cy, r, a0, a1):
            n = max(10, int(abs(a1 - a0) / 0.03))
            pts = [(cx + r * math.cos(a0 + (a1 - a0) * i / n),
                    cy - r * math.sin(a0 + (a1 - a0) * i / n)) for i in range(n + 1)]
            return c.path("M" + " L".join(f"{x:.2f},{y:.2f}" for x, y in pts),
                          stroke=ACCENT, sw=1.4)

        y = pad
        bottoms = []
        for pi, plot in enumerate(plots):
            key = plot.get("key") or str(pi)
            x0 = pad + pi * (pw + gap)
            ox = x0 + 30
            oy = y + title_size * 1.3 + side
            c.add(c.text(x0 + pw / 2, y + title_size * 1.05, plot.get("label", ""),
                         title_size, weight="600"))
            c.add(c.line(ox, oy, ox + side + 10, oy, stroke=RULE, sw=1))
            c.add(c.line(ox, oy, ox, oy - side - 10, stroke=RULE, sw=1))

            rays = [c.circle(ox, oy, 2.5, fill=INK)]
            angles = []
            lengths = []
            for v in plot.get("vectors") or []:
                tx, ty = ox + k * v["x"], oy - k * v["y"]
                rays.append(c.line(ox, oy, tx, ty, stroke=ACCENT, sw=2,
                                   arrow=True, accent=True))
                rays.append(c.circle(tx, ty, 3, fill=ACCENT))
                rays.append(c.text(tx, ty - 9, v["label"], label_size,
                                   fill=INK, weight="600"))
                angles.append(math.atan2(v["y"], v["x"]))
                lengths.append(math.hypot(v["x"], v["y"]))
            c.add(c.group(_part_at(parts, "rays", pi) or "rays-" + key,
                          "".join(rays)))

            extras = []
            if pi == 0 and mean:
                tx, ty = ox + k * mean["x"], oy - k * mean["y"]
                mp = _part_at(parts, "mean", 0) or "mean"
                c.add(c.group(mp,
                              c.line(ox, oy, tx, ty, stroke=MUTED, sw=1.4, dash="5 4") +
                              c.circle(tx, ty, 2.5, fill=MUTED)))
                extras.append(mean.get("label", ""))
            if plot.get("cos_label"):
                a0, a1 = min(angles), max(angles)
                r = min(0.62 * min(lengths) * k, side * 0.55)
                c.add(c.group(_part_at(parts, "arcs", pi) or "arc-" + key,
                              arc(ox, oy, r, a0, a1)))
                extras.append(plot["cos_label"])

            lines = ["    ".join(f'{v["label"]} = ({v["x"]}, {v["y"]})'
                                 for v in plot.get("vectors") or [])]
            if extras:
                lines.append("    ".join(e for e in extras if e))
            cy = oy + label_size * 1.7
            c.add(c.block(x0 + pw / 2, cy, lines, small, fill=MUTED, lh=lh))
            bottom = cy + (len(lines) - 1) * lh + small * 1.5
            if pi == len(plots) - 1 and note:
                wrapped = wrap_px(note, small, pw - 10)
                ny = bottom + small * 1.2
                c.add(c.block(x0 + pw / 2, ny, wrapped, small, fill=MUTED, lh=lh))
                bottom = ny + (len(wrapped) - 1) * lh + small * 1.5
            bottoms.append(bottom)
        c.h = max(bottoms) + 12
        return c

    return _fit(spec, 900, build).render()


def render_bus(spec):
    """One persistent lane with sublayers tapping it, instead of a pipeline.

    The chapter rejects the stack-of-blocks picture: one vector per token survives from
    the embedding lookup to the unembedding, and each sublayer reads it and adds to it
    rather than handing a replacement to the next block. So the drawing is a bus: a
    horizontal lane with a row of sublayer boxes above it and a row below, every box
    carrying a read arrow out of the lane and a write arrow back into it. Each row's
    label states how many times per layer that stack writes.
    """
    rows = spec.get("rows") or []
    if not rows:
        return None
    note = spec.get("note")
    lane_text = spec.get("lane") or ""
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        label_w = 132
        x0 = pad + label_w
        cw = w - x0 - pad
        small = size * 0.82
        tiny = size * 0.74
        lh = round(small * 1.22)
        tlh = round(tiny * 1.2)

        y = 24
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, y, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            y += nl * size * 1.2 + 24

        gap = 22
        arrow_gap = 28
        band_h = max(24.0, tiny * 1.9)
        maxn = max(len(r.get("boxes") or []) for r in rows)
        bw = (cw - (maxn - 1) * gap) / maxn

        def box_height(row):
            tallest = 0
            for b in row.get("boxes") or []:
                lines = wrap_px(b.get("name", ""), small, bw - 14)
                sub = wrap_px(b.get("sub", ""), tiny, bw - 14) if b.get("sub") else []
                tallest = max(tallest, len(lines) + len(sub))
            return 14 + tallest * lh

        heights = [box_height(r) for r in rows]
        enc_h = heights[0]
        enc_top = y
        band_top = enc_top + enc_h + arrow_gap
        dec_top = band_top + band_h + arrow_gap

        def row_at(ri):
            return enc_top if ri == 0 else dec_top

        # `parts.boxes` may be flat (in row order) or one list per row; both are read
        # through the same offset so a box's name never depends on the row count.
        box_parts = parts.get("boxes") or []
        nested = bool(box_parts) and isinstance(box_parts[0], list)
        offsets = [sum(len(r.get("boxes") or []) for r in rows[:ri])
                   for ri in range(len(rows))]

        def box_part(ri, bi):
            if nested:
                if ri < len(box_parts) and bi < len(box_parts[ri]):
                    return box_parts[ri][bi] or None
                return None
            return _part_at(parts, "boxes", offsets[ri] + bi)

        # the lane, with its own label inside it
        lane_part = parts.get("lane") or "lane"
        inner = [c.rect(x0 - 16, band_top, cw + 16 + 0, band_h, fill="none",
                        stroke=ACCENT, sw=1.4, rx=band_h / 2)]
        if lane_text:
            inner.append(c.text(x0, band_top + band_h / 2 + tiny * 0.36, lane_text,
                                tiny, anchor="start", fill=INK, weight="600"))
        c.add(c.group(lane_part, "".join(inner)))

        for ri, row in enumerate(rows):
            # Row 0 always sits above the lane; any further row sits below it.
            above = ri == 0
            by = row_at(ri)
            bh = heights[ri]
            row_part = _part_at(parts, "rows", ri)
            boxes = row.get("boxes") or []
            rlines = wrap_px(row.get("label", ""), small, label_w - 8)
            extra = row.get("writes")
            block = list(rlines) + ([extra] if extra else [])
            c.add(c.block_centered(pad + (label_w - 12) / 2, by + bh / 2, block,
                                   small, fill=INK, weight="600", lh=lh,
                                   part=row_part))
            row_w = len(boxes) * bw + (len(boxes) - 1) * gap
            start = x0 + (cw - row_w) / 2
            for bi, b in enumerate(boxes):
                bx = start + bi * (bw + gap)
                bpart = box_part(ri, bi) or row_part
                inner = [c.rect(bx, by, bw, bh, fill="none",
                                stroke=ACCENT if b.get("accent") else RULE,
                                sw=1.2, rx=4)]
                lines = (wrap_px(b.get("name", ""), small, bw - 14) +
                         (wrap_px(b.get("sub", ""), tiny, bw - 14) if b.get("sub") else []))
                inner.append(c.block_centered(bx + bw / 2, by + bh / 2, lines, small,
                                              fill=INK, weight="600", lh=lh))
                c.add(c.group(bpart, "".join(inner)))
                rx = bx + bw * 0.32
                wx = bx + bw * 0.68
                if above:
                    c.add(c.line(rx, band_top, rx, by + bh, stroke=MUTED, sw=1.1,
                                 arrow=True, part=bpart))
                    c.add(c.line(wx, by + bh, wx, band_top, stroke=ACCENT, sw=1.1,
                                 arrow=True, accent=True, part=bpart))
                else:
                    c.add(c.line(rx, band_top + band_h, rx, by, stroke=MUTED, sw=1.1,
                                 arrow=True, part=bpart))
                    c.add(c.line(wx, by, wx, band_top + band_h, stroke=ACCENT, sw=1.1,
                                 arrow=True, accent=True, part=bpart))
        bottom = dec_top + heights[-1] if len(rows) > 1 else band_top + band_h
        c.h = bottom + 24
        return c

    return _fit(spec, 900, build).render()


def render_wiring(spec):
    """Two chains drawn on one shared column grid, so a moved step is visible.

    The point of pre-norm versus post-norm is not two equations but one step changing
    place. Both chains therefore use the same columns and the same box size: where the
    norm box sits is the whole figure, and an empty slot is as informative as a filled
    one. A skip arc leaves the input and rejoins at the add, so the identity path is a
    drawn object rather than a claim in a caption.
    """
    chains = spec.get("chains") or []
    columns = spec.get("columns") or []
    if not chains or not columns:
        return None
    note = spec.get("note")
    parts = spec.get("parts") or {}
    cell_parts = parts.get("cells") or []

    def cell_part(ri, ci):
        if ri < len(cell_parts) and ci < len(cell_parts[ri]):
            return cell_parts[ri][ci] or None
        return None

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        label_w = 120
        x0 = pad + label_w
        n = len(columns)
        gap = 14
        cw = (w - x0 - pad) / n
        bw = cw - gap
        small = size * 0.82
        tiny = size * 0.74
        lh = round(small * 1.2)
        tlh = round(tiny * 1.22)
        skip_h = 26

        cells = [cell for ch in chains for cell in ch.get("cells") or []]
        tallest = max([len(wrap_px(cell.get("text", ""), small, bw - 12)) for cell in cells]
                      or [1])
        box_h = 12 + tallest * lh

        y = 24
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, y, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            y += nl * size * 1.2 + 22

        head_y = y
        for ci, col in enumerate(columns):
            cx = x0 + ci * cw + cw / 2
            c.add(c.text(cx, head_y, col, tiny, fill=MUTED, weight="600"))
        y = head_y + tlh + 14

        for ri, ch in enumerate(chains):
            chain_part = _part_at(parts, "chains", ri)
            top = y + skip_h
            label_lines = wrap_px(ch.get("label", ""), small, label_w - 12)
            c.add(c.block(pad, top + (box_h - len(label_lines) * lh) / 2 + small,
                          label_lines, small, anchor="start", fill=INK, weight="600",
                          lh=lh, part=chain_part))
            boxes = {}
            for cell in ch.get("cells") or []:
                ci = cell.get("col", 0)
                bx = x0 + ci * cw + gap / 2
                bpart = cell_part(ri, ci) or chain_part
                ghost = cell.get("ghost")
                accent = cell.get("accent")
                c.add(c.rect(bx, top, bw, box_h, fill="none",
                             stroke=ACCENT if accent else RULE,
                             sw=1.2 if accent else 1, rx=4,
                             dash="3 3" if ghost else None, part=bpart))
                lines = wrap_px(cell.get("text", ""), small, bw - 12)
                c.add(c.block_centered(bx + bw / 2, top + box_h / 2, lines, small,
                                       fill=INK if accent else MUTED,
                                       weight="600" if accent else "400",
                                       lh=lh, part=bpart))
                boxes[ci] = bx
            for k in range(n - 1):
                if k in boxes and (k + 1) in boxes:
                    c.add(c.line(boxes[k] + bw, top + box_h / 2, boxes[k + 1],
                                 top + box_h / 2, stroke=MUTED, sw=1.1, arrow=True,
                                 part=chain_part))
            skip = ch.get("skip")
            if skip:
                a, b = skip.get("from", 0), skip.get("to", 1)
                ax, bx2 = boxes[a] + bw / 2, boxes[b] + bw / 2
                sy = top - skip_h
                d = (f"M{ax:.2f},{top:.2f} L{ax:.2f},{sy:.2f} "
                     f"L{bx2:.2f},{sy:.2f} L{bx2:.2f},{top:.2f}")
                c.add(c.path(d, stroke=ACCENT, sw=1.3, arrow=True, accent=True,
                             part=chain_part))
                if skip.get("label"):
                    c.add(c.text((ax + bx2) / 2, sy - 5, skip["label"], tiny,
                                 fill=ACCENT, part=chain_part))
            y = top + box_h + tlh * 1.4
            if ch.get("note"):
                nl = c.note_lines(ch["note"], tiny, w - 2 * pad)
                c.add(c.note(pad, y, ch["note"], tiny, w - 2 * pad, part=chain_part))
                y += nl * tlh + 6
            y += 16
        c.h = y + 4
        return c

    return _fit(spec, 900, build).render()


def render_slab(spec):
    """Two tensors side by side, drawn by how many sheets they occupy.

    The cost comparison between additive and dot-product scoring is not about the
    multiply-adds alone; it is that one produces a single n-by-m sheet and the other a
    k-deep stack that has to be materialised and then reduced. So each panel is a sheet
    with a depth: one sheet is one GEMM's output, several offset sheets are the stack.
    """
    panels = spec.get("panels") or []
    if not panels:
        return None
    note = spec.get("note")
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        gap = 40
        pw = (w - 2 * pad - gap * (len(panels) - 1)) / len(panels)
        small = size * 0.82
        tiny = size * 0.74
        lh = round(small * 1.22)
        tlh = round(tiny * 1.22)

        y = 24
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, y, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            y += nl * size * 1.2 + 24

        head = y
        for pi, p in enumerate(panels):
            c.add(c.text(pad + pi * (pw + gap), head, p.get("title", ""), size * 0.9,
                         anchor="start", fill=ACCENT, weight="600",
                         part=_part_at(parts, "panels", pi)))
        y = head + size * 1.6

        sw = min(pw - 78, 250)
        sh = sw * 0.5
        step = 7.0
        # Every panel's front sheet shares a baseline, so the stack's height is set by
        # the deepest panel and the shallower ones sit at the bottom of that band. A
        # depth of 128 is drawn as eight sheets; the bracket carries the real count.
        stacks = [sh + (min(max(1, int(p.get("depth") or 1)), 8) - 1) * step
                  for p in panels]
        stack_h = max(stacks)
        bottoms = []
        for pi, p in enumerate(panels):
            x0 = pad + pi * (pw + gap)
            panel_part = _part_at(parts, "panels", pi)
            fx = x0 + 40
            sheets = min(max(1, int(p.get("depth") or 1)), 8)
            top = y + stack_h - sh
            # Back sheets first so the front sheet's outline and grid sit on top.
            for si in range(sheets - 1, 0, -1):
                off = si * step
                c.add(c.group(panel_part,
                              c.rect(fx + off, top - off, sw, sh, fill="none",
                                     stroke=RULE, sw=1, rx=3)))
            c.add(c.group(panel_part,
                          c.rect(fx, top, sw, sh, fill="none", stroke=ACCENT, sw=1.2,
                                 rx=3)))
            grid = []
            for gi in range(1, 5):
                gy = top + sh * gi / 5
                grid.append(c.line(fx, gy, fx + sw, gy, stroke=RULE, sw=0.6))
            for gj in range(1, 8):
                gx = fx + sw * gj / 8
                grid.append(c.line(gx, top, gx, top + sh, stroke=RULE, sw=0.6))
            c.add(c.group(panel_part, "".join(grid)))
            if p.get("cells"):
                c.add(c.block_centered(fx + sw / 2, top + sh / 2,
                                       wrap_px(p["cells"], small, sw - 12), small,
                                       fill=INK, weight="600", lh=lh,
                                       part=panel_part))
            if sheets > 1 and p.get("zlab"):
                zx = fx + sw + (sheets - 1) * step + 12
                zy0 = top - (sheets - 1) * step
                c.add(c.group(panel_part,
                              c.line(zx, zy0, zx, top + sh, stroke=MUTED, sw=1) +
                              c.line(zx - 4, zy0, zx + 4, zy0, stroke=MUTED, sw=1) +
                              c.line(zx - 4, top + sh, zx + 4, top + sh, stroke=MUTED,
                                     sw=1)))
                zl = wrap_px(p["zlab"], tiny, 66)
                zy = top + sh / 2 - (len(zl) - 1) * tlh / 2 + tiny * 0.34
                c.add(c.block(zx + 8, zy, zl, tiny, anchor="start", fill=ACCENT,
                              weight="600", lh=tlh, part=panel_part))
            ly = top + sh + tlh + 8
            if p.get("xlab"):
                c.add(c.text(fx + sw / 2, ly, p["xlab"], tiny, fill=MUTED,
                             part=panel_part))
            if p.get("ylab"):
                # Above the whole stack, not above the front sheet: a label inside the
                # band would be crossed by the back sheets' outlines.
                c.add(c.text(fx, top - (sheets - 1) * step - 10, p["ylab"], tiny,
                             anchor="start", fill=MUTED, part=panel_part))
            y2 = ly + tlh * 1.4
            for key in ("cost", "note"):
                if p.get(key):
                    nl = c.note_lines(p[key], small if key == "cost" else tiny,
                                      pw - 12)
                    c.add(c.note(x0, y2, p[key], small if key == "cost" else tiny,
                                 pw - 12, part=panel_part))
                    y2 += nl * (lh if key == "cost" else tlh) + 6
            bottoms.append(y2)
        c.h = max(bottoms) + 6
        return c

    return _fit(spec, 900, build).render()


def render_keep(spec):
    """To-scale strips of what the decoder actually receives.

    The bottleneck is a capacity claim, so the drawing has to be to scale: a strip's
    length is its float count, the solid head is the part that survives, and the dashed
    remainder is what the decoder never sees. Rows share one scale, so the fifty-token
    sentence really is ten times the five-token one and the same 256-slot head is a
    sliver of both. A Bahdanau row keeps everything, which is why its strip is solid end
    to end.
    """
    rows = spec.get("rows") or []
    if not rows:
        return None
    note = spec.get("note")
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        label_w = 158
        x0 = pad + label_w
        plot_w = w - x0 - pad - 236
        small = size * 0.82
        tiny = size * 0.74
        lh = round(small * 1.22)
        tlh = round(tiny * 1.22)
        rh = 30

        y = 24
        if note:
            nl = c.note_lines(note, size * 0.86, w - 2 * pad)
            c.add(c.note(pad, y, note, size * 0.86, w - 2 * pad,
                         part=parts.get("note")))
            y += nl * size * 1.2 + 24

        scale = max(float(r.get("total") or 1) for r in rows)
        for ri, r in enumerate(rows):
            rp = _part_at(parts, "rows", ri)
            total = float(r.get("total") or 1)
            kept = float(r.get("kept") or 0)
            strip_w = plot_w * total / scale
            kw = strip_w * kept / total
            lines = wrap_px(r.get("label", ""), small, label_w - 10)
            c.add(c.block(pad, y + rh / 2 - (len(lines) - 1) * lh / 2 + small * 0.34,
                          lines, small, anchor="start", fill=INK, weight="600", lh=lh,
                          part=rp))
            c.add(c.rect(x0, y, max(1.0, kw), rh, fill=WASH_2,
                         stroke=ACCENT if r.get("accent", True) else RULE, sw=1.1,
                         part=rp))
            if kept < total:
                c.add(c.rect(x0 + kw, y, strip_w - kw, rh, fill="none", stroke=RULE,
                             sw=1, dash="3 3", part=rp))
            # Labels are placed left to right after the strip's right edge unless the
            # kept head is wide enough to hold its own label; a short strip leaves the
            # head only a sliver, so its label moves out rather than colliding with the
            # discarded count.
            ty2 = y + rh / 2 + small * 0.34
            after = x0 + strip_w + 8
            if r.get("kept_label"):
                if kw > text_width(r["kept_label"], tiny) + 10:
                    c.add(c.text(x0 + kw / 2, ty2, r["kept_label"], tiny,
                                 weight="600", part=rp))
                else:
                    c.add(c.text(after, ty2, r["kept_label"], tiny, anchor="start",
                                 fill=ACCENT, weight="600", part=rp))
                    after += text_width(r["kept_label"], tiny) + 16
            if r.get("total_label"):
                c.add(c.text(after, ty2, r["total_label"], tiny, anchor="start",
                             fill=MUTED, part=rp))
            y += rh + tlh + 10
        c.h = y + 6
        return c

    return _fit(spec, 900, build).render()


# ---------------------------------------------------------------------------
# mixture -- value vectors scaled by their shares, added head to tail
# ---------------------------------------------------------------------------

def render_mixture(spec):
    """A softmax row returns a mixture, not a choice.

    Each value vector is scaled by its share, and the scaled vectors are laid end to
    end, so the head-to-tail path ends at the vector sum the prose prints. Both axes
    carry one scale, which is what makes a segment's length mean its share times its
    vector's length. The per-axis arithmetic sits beside the plot: three short segments
    leave no room for it inside, and the two rows are the only place the x and y sums
    are separated.
    """
    segments = spec.get("segments") or []
    if not segments:
        return None
    result = spec.get("result") or {}
    note = spec.get("note")
    parts = spec.get("parts") or {}

    def build(w, size):
        c = Canvas(w, 0, spec.get("title", "Figure"),
                   spec.get("why") or spec.get("caption") or spec.get("title", ""))
        pad = 16
        label_size = size * 0.84
        small = size * 0.82
        lh = round(label_size * 1.2)
        # pixels per unit coordinate, the same on both axes; the x axis runs the full
        # unit so the reader can see how far short of it the partial sums stop
        k = min(430.0, w - 2 * pad - 380)
        ox = 56.0
        oy = 26.0 + k * 0.5
        c.add(c.line(ox, oy, ox + k, oy, stroke=RULE, sw=1))
        c.add(c.line(ox, oy, ox, oy - k * 0.5, stroke=RULE, sw=1))
        c.add(c.text(ox - 6, oy - k * 0.5 + small * 0.34, "y", small, anchor="end",
                     fill=MUTED))
        c.add(c.text(ox - 6, oy + small * 0.34, "0", small, anchor="end", fill=MUTED))
        c.add(c.text(ox + k + 6, oy + small * 0.34, "x", small, anchor="start",
                     fill=MUTED))

        acc_x = acc_y = 0.0
        pts = [(ox, oy)]
        for seg in segments:
            acc_x += seg["share"] * seg["vector"][0]
            acc_y += seg["share"] * seg["vector"][1]
            pts.append((ox + k * acc_x, oy - k * acc_y))

        # one arrow per scaled vector, each carrying its own label so the animation can
        # light a segment and its text together
        for si, seg in enumerate(segments):
            x1, y1 = pts[si]
            x2, y2 = pts[si + 1]
            marks = c.line(x1, y1, x2, y2, stroke=ACCENT, sw=2.4, arrow=True,
                           accent=True)
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            # push each label off its segment along a normal, always to the right of
            # the segment's direction, so text never lands inside the path it names
            dx, dy = x2 - x1, y2 - y1
            span = math.hypot(dx, dy) or 1.0
            nx, ny = dy / span, -dx / span
            if nx < 0:
                nx, ny = -nx, -ny
            lx, ly = mx + nx * 10, my + ny * 10 + label_size * 0.34
            anchor = "middle" if abs(nx) < 0.3 else "start"
            marks += c.text(lx, ly, seg["label"], label_size, anchor=anchor,
                            weight="600")
            c.add(_grp(_part_at(parts, "segments", si), marks))

        # the sum itself: a dashed chord from the origin to the end of the path
        end_x, end_y = pts[-1]
        res_part = _part_at(parts, "result", 0)
        marks = c.line(ox, oy, end_x, end_y, stroke=MUTED, sw=1.4, dash="5 4")
        marks += c.circle(end_x, end_y, 3.5)
        if result.get("label"):
            marks += c.text(end_x + 6, end_y + label_size * 0.34, result["label"],
                            label_size, anchor="start", weight="600")
        c.add(_grp(res_part, marks))

        # the two coordinate sums, beside the plot where they have room
        col_x = ox + k + 34
        col_w = w - pad - col_x
        rows = []
        for axis, name, total in ((0, "x", acc_x), (1, "y", acc_y)):
            terms = " + ".join(f"{s['share']:.3f}·{s['vector'][axis]:g}"
                               for s in segments)
            rows.append(f"{name}:  {terms} = {total:.3f}")
        ty = oy - k * 0.34
        c.add(c.block(col_x, ty, rows, small, anchor="start", weight="600",
                      part=res_part))
        if spec.get("scale"):
            cap = wrap_px(spec["scale"], small, col_w)
            c.add(c.block(col_x, ty + len(rows) * lh + small * 0.9, cap, small,
                          anchor="start", fill=MUTED))

        note_y = oy + 40
        if note:
            nl = c.note_lines(note, small, w - 2 * pad)
            c.add(c.note(pad, note_y, note, small, w - 2 * pad))
            c.h = note_y + (nl - 1) * round(small * 1.2) + small * 1.6 + 12
        else:
            c.h = note_y + 14
        return c

    return _fit(spec, 900, build).render()


RENDER = {
    "tokens": render_tokens,
    "matrix": render_matrix,
    "timeline": render_timeline,
    "memory": render_memory,
    "bits": render_bits,
    "bars": render_bars,
    "logaxes": render_logaxes,
    "panels": render_panels,
    "lane": render_lane,
    "flow": render_flow,
    "grid": render_grid,
    "vocab_stack": render_vocab_stack,
    "merge_forest": render_merge_forest,
    "vectors": render_vectors,
    "bus": render_bus,
    "wiring": render_wiring,
    "slab": render_slab,
    "keep": render_keep,
    "mixture": render_mixture,
}


def _render_spec(spec):
    kind = spec.get("kind") or "flow"
    fn = RENDER.get(kind)
    if fn is None:
        print(f"unknown kind {kind!r}, falling back to flow")
        fn = render_flow
    data = spec.get("data")
    if isinstance(data, dict):
        merged = dict(spec)
        merged.update(data)
        spec = merged
    return fn(spec)


def build(cid):
    spec = review.load_diagram(cid)
    if not spec or not spec.get("needed"):
        return []
    os.makedirs(OUT, exist_ok=True)

    # Drop the chapter's previous figures so a renamed or removed figure does
    # not linger in the site directory.
    for name in os.listdir(OUT):
        if name == cid + ".svg" or (
                name.startswith(cid + "-") and name.endswith(".svg")):
            os.remove(os.path.join(OUT, name))

    if spec.get("figures"):
        paths = []
        for fig in spec["figures"]:
            svg = _render_spec(fig)
            if not svg:
                continue
            p = os.path.join(OUT, f"{cid}-{fig['id']}.svg")
            open(p, "w", encoding="utf-8").write(svg)
            paths.append(p)
        return paths

    svg = _render_spec(spec)
    if not svg:
        return []
    p = os.path.join(OUT, cid + ".svg")
    open(p, "w", encoding="utf-8").write(svg)
    return [p]


def main():
    ids = sys.argv[1:] or review.published_ids()
    n = 0
    for cid in ids:
        try:
            paths = build(cid)
        except Exception as e:
            print(f"{cid}: ERROR {type(e).__name__}: {e}")
            continue
        if paths:
            n += len(paths)
            for p in paths:
                print(f"{cid}: {os.path.basename(p)} {os.path.getsize(p)} bytes")
        else:
            print(f"{cid}: no figure")
    print(f"{n} figures written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
