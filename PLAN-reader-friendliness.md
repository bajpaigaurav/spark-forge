# Reader-friendliness plan

Derived from four independent reviews (technical writer, curious learner, senior engineer,
tech-writer/UX). Each item is: **validate absent → implement → validate locally → validate
live → commit → next**.

Live URL: https://bajpaigaurav.github.io/spark-forge/
Deploy: `./build_site.sh` → commit `docs/` → push → Pages rebuilds.

## Baseline (measured, 2026-11-05)

| Thing | State |
|---|---|
| `<meta description>` / OG tags / favicon | absent |
| cross-links between chapters in prose | 0 |
| glossary page / `content/glossary.json` | absent |
| paths page / `content/paths.json` | absent |
| in-chapter mini-TOC | absent |
| `<h3>` with `id` anchor | 0 of 30 |
| paragraphs >150 words | 162 of 580 |
| prerequisite strip | absent |
| consistency gate (gate 3) | absent |
| rig artifact page | absent |

## Known defects to fix along the way (verified by reading)

1. **ch 09** — sentence duplicated mid-paragraph ("divided elementwise by the normalizer…").
2. **ch 12** — two duplicated fragments ("Paging cuts the waste per sequence…" and
   "so that shared prefixes are found by tree walk rather than by hash." appear twice).
3. **ch 14** — `34.1 GB` is `L²×2 bytes` (one head, one layer) but `4.37 TB` is
   `L²×d×2 bytes`, i.e. **d heads**, contradicting the "one head of one layer" framing.
   Also "111.5/34.1 gives 3.3" — the quotient is **3.27**.

All three shipped because the fact gate checks traceability, not self-consistency.

## Order

Cheap and non-destructive first; the trust-raising work after; the prose-rewriting ideas
either corrected or deliberately dropped.

---

### 1. Metadata + favicon  *(30 min)*

**Why:** every shared link is blank; 31 hand-written theses are thrown away.
**Absent check:** no `name="description"`, no `og:` in `docs/chapters/*.html`.
**Change:** in `build.py` `page()`, emit `description` from `c["thesis"]`, plus
`og:title`, `og:description`, `og:type=article`, `og:url`, and a small inline SVG favicon.
Index gets a book-level description.
**Validate:** grep the built HTML for the tags; every chapter has a non-empty description;
no duplicate/empty values; `verify_site.sh` clean.

### 2. Cross-links + prerequisite strip  *(~5h)*

**Why:** 31 chapters, zero cross-references. "31 essays, not a book."
**Absent check:** 0 `href="NN-*.html"` inside `<article class="prose">`.
**Change:**
- `[[10-kv-cache]]` / `[[10]]` wiki-link syntax parsed in `build.py`'s `inline()` →
  `<a href="10-kv-cache.html">` with the target chapter's title as link text unless an
  alias is given (`[[10|the KV cache]]`).
- `prereqs: ["03","10"]` per chapter in `content/plan.json` → a header strip
  "Assumes: 03, 10" linking to them.
- Add links where the reviewer named them (ch 29 → 10/21, ch 16 → 20–22) — a *judgement*
  pass, not a regex sweep, so no wrong links.
**Validate:** no self-links; every `[[…]]` resolves to a real chapter id; strip renders on
chapters that have prereqs; `verify_site.sh` clean; live: click 3 links, confirm 200 + right
target.

### 3. Paragraph splitter + heading anchors + mini-TOC  *(~1 day)*

**Why:** highest-leverage fix per two reviewers. 162 paragraphs >150 words, 5 chapters with
zero subheads.
**Absent check:** `mini-toc` absent, 0 `<h3 id=`.
**Change:**
- `split_long_paragraphs()`: split any `<p>` over 150 words at sentence boundaries into 2–3
  paragraphs. Deterministic, no prose rewriting. Respect an opt-out marker for paragraphs
  meant as one breath.
- Slugify `<h3>` → `id`, and emit `<nav class="mini-toc">` when ≥3 subheads exist (gate it,
  otherwise it's clutter).
**Do NOT** generate subheads blind — that relocates the slop problem to headings. Subheads
come from the writer via a **fact-gate rule** (one `##` per ~250 words) instead.
**Validate:** paragraph count >150 words drops to ~0; no paragraph split mid-sentence
(assert each split lands after `.!?`); anchors unique; mini-TOC only where ≥3 headings;
`verify_site.sh` clean; live: TOC links jump to the right heading.

### 4. Glossary  *(~6h build + writing)*

**Why:** "significand, amax, roofline, attention sink arrive cold."
**Absent check:** no `docs/glossary.html`, no `content/glossary.json`.
**Change:** `content/glossary.json` (`{term, one_line, chapter, match}`), `docs/glossary.html`,
and a "Terms in this chapter" chip line in the header built by word-boundary matching.
**Validate:** every term's `chapter` is a real id; matching does not over-hit (`cache` must
not match `caching` unless the term says so); chips ≤8 per chapter; `verify_site.sh` clean;
live: glossary page 200, chips link to it.

### 5. Reading paths  *(~3h build + curation)*

**Why:** "no reader arrives wanting all 31 in order."
**Absent check:** no `docs/paths.html`, no `content/paths.json`.
**Change:** `content/paths.json` with 4 opinionated routes (one must be *skip-the-basics*),
minutes computed from real word counts, `docs/paths.html`, and a strip on the index.
**Validate:** every chapter id in every path exists and is published; minutes match
`words/220`; paths differ materially (not 5 reorderings); `verify_site.sh` clean; live: page
200, strip on index, links resolve.

### 6. Consistency gate (gate 3)  *(~1–2 days)*

**Why:** the single highest-impact trust fix. It catches the three real defects above.
**Absent check:** no `skills/consistency_gate.py`.
**Change:**
- Evaluate each `derived:` formula in `sources.json` and assert the printed value.
- Duplicate-sentence detector (shingle hash) across paragraphs, within and across chapters.
- Unit-consistency check for `L²×2` vs `L²×d×2` style expressions.
- Fix ch 09, ch 12, ch 14 prose so the gate passes.
**Validate:** the gate FAILS on the current chapters (proving it catches the known defects),
then PASSES after the fixes; add a test that pins each defect; `verify_site.sh` clean.

### 7. Rig artifact ("reproduce this")  *(near zero)*

**Why:** "I cannot verify any of it" — the trust story rests on an unauditable scrape.
**Absent check:** no `docs/rig.html`, no `content/rig/`.
**Change:** ship the raw metrics dump, the serve argv, and the probe commands as
downloadable files + a `docs/rig.html` page with a one-page "reproduce this" appendix.
**Validate:** files are downloadable from the live site; the page's numbers match
`sources.json`; `verify_site.sh` clean.

### 8. Deliberately NOT done as designed

- **Clickable-number popovers** — 80% already exists as the provenance table; a popover
  hides the thing a skeptical reader wants open and invites clicking 40 numbers a page.
  Replaced by item 6 (render the arithmetic) + the existing table.
- **Visible cover-list checklists** — the raw `cover` strings are author-voice keyword soup.
  Only worth doing after rewriting them into questions; deferred.
- **Running 7B worked example** — a book rewrite, and the rig is a 111 GB pair, so a 7B
  thread would mislead single-GPU readers. Deferred.

## Definition of done

Each item: absent-check recorded, change made, `verify_site.sh` clean, live URL returns 200
with the feature visibly present, committed and pushed, then move on.
