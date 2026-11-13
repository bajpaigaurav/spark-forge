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
        for f in fields:
            n = int(f["bits"])
            x1 = bar_x + bar_w * acc / total_bits
            x2 = bar_x + bar_w * (acc + n) / total_bits
            # one accent for the exponent, a neutral wash for sign and mantissa
            # The accent marks the exponent field in a wash; every field keeps an
            # ink outline so the bar reads as one bar split three ways, not as a
            # lone tinted block.
            fill = WASH_3 if f.get("accent") else "none"
            stroke = ACCENT if f.get("accent") else INK
            c.add(c.rect(x1, y, x2 - x1, h, fill=fill, stroke=stroke,
                         sw=1.6 if f.get("accent") else 1.2))
            mid = (x1 + x2) / 2
            field_w = x2 - x1
            # A one-bit field is too narrow for its name: wrapping "sign" would
            # split it into "si"/"gn". Rotate short field names instead, which
            # keeps the label intact inside the bar.
            if field_w < text_width(f["name"], size * 0.84) + 6:
                c.add(c.text(mid, y + h / 2, f["name"], size * 0.78,
                             weight="600", rotate=-90))
            else:
                lines = wrap_px(f["name"], size * 0.84, field_w - 6)
                c.add(c.block_centered(mid, y + h / 2 - (size * 0.5 if f.get("note") else 0),
                                       lines, size * 0.84, weight="600"))
            if f.get("note"):
                c.add(c.text(mid, y + h / 2 + size * 0.9, f["note"], size * 0.78,
                             fill=MUTED))
            c.add(c.text(mid, y + h + size + 2, str(n), size * 0.8, fill=ACCENT,
                         weight="600"))
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
            c.add(c.note(pad, c.h, caption, size * 0.82, w - 2 * pad))
            c.h += nl * size * 1.2
        c.h = max(c.h + size * 1.2, 150)
        return c

    return _fit(spec, 760, build).render()


# ---------------------------------------------------------------------------
# bars -- aligned horizontal bars with their numbers
# ---------------------------------------------------------------------------

def render_bars(spec):
    bars = spec.get("bars") or []
    if not bars:
        return None
    group = spec.get("group")             # optional: {name: [...]} for small multiples
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
            note_h = nl * size * 1.2 + 10
        top = 26 + note_h
        vmax = max(float(b["value"]) for b in bars) or 1
        rh = 26
        y = top
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
        pw = (w - 2 * pad - gap) / len(panels)
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
    parts = data.get("parts") or []
    total = data.get("total")
    if not parts or total is None:
        return None

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
        total_h = len(parts) * row_h + (len(parts) - 1) * gap
        for i, (label, count) in enumerate(parts):
            yy = y + i * (row_h + gap)
            c.add(c.rect(bar_x, yy, bar_w, row_h,
                         fill=WASH_2 if i == 1 else WASH, stroke=RULE, rx=2))
            c.add(c.text(pad, yy + row_h / 2 + size * 0.35, label, size,
                         anchor="start", fill=INK, weight="500"))
            c.add(c.text(bar_x + bar_w + 10, yy + row_h / 2 + size * 0.35,
                         f"{count:,}", size, anchor="start", fill=ACCENT,
                         family=FONT_MONO, weight="600"))
        bx = bar_x + bar_w + 82
        c.add(c.line(bx, y, bx, y + total_h, stroke=MUTED, sw=1))
        c.add(c.line(bx - 5, y, bx + 5, y, stroke=MUTED, sw=1))
        c.add(c.line(bx - 5, y + total_h, bx + 5, y + total_h, stroke=MUTED, sw=1))
        c.add(c.text(bx + 10, y + total_h / 2, f"{total:,} total", size,
                     anchor="start", fill=INK, weight="600"))
        arith = " + ".join(f"{count:,}" for _, count in parts) + f" = {total:,}"
        arith_y = y + total_h + 24
        c.add(c.note(pad, arith_y, arith, size * 0.9, w - 2 * pad))
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
