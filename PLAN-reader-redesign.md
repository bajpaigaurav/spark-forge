# Reader-first redesign of *The Shape of a Token*

Status: **done**, published. Site: https://bajpaigaurav.github.io/spark-forge/ (GitHub Pages, served from `docs/`).

## The complaint, restated

1. Information is hidden. The table of contents sat **below** the frontispiece, the live
   figures and the reading-path strip — at y≈1300 on a 1440 screen. Navigation existed
   only as a prev/next pair at the foot of a chapter.
2. Diagrams are misaligned and their labels overflow.
3. Diagrams sit at the **end** of the chapter, after the prose that discusses them.
4. No light/dark toggle, no search.
5. The page felt plain and template-like.

## What was actually wrong (measured, not guessed)

| Symptom | Cause |
|---|---|
| TOC below the fold | `build.py` emitted `{paths_strip}` → `{figures_panel}` → `{toc_html}`; the contents section rendered last |
| No navigation while reading | no persistent chrome; only `.chapter-nav` at the end |
| SVG labels overflow | no renderer measured text. `render_shapes` reserved 150px for a label column but printed labels unwrapped; `render_curve` centred the last label past the edge. Fixed with `text_width()` / `wrap_px()` and a clamped anchor |
| Figures at chapter end | `figure_for(cid)` was called **after** `<article class="prose">`, ignoring the spec's `section` / `sections` |
| `site.js` edits lost | the source is `site.js` at repo root; `site/` is gitignored build output. `build.py` now copies it |
| Contents rail hidden on the front page | `.shell--wide .rail { display: none }` — the one page a newcomer needs it |
| Contents index was a build log | `toc_items` emitted `published · 2,546 words` per row; a newer title+minutes version was defined but never called (the old one shadowed it) |
| Chapter head 864px wide, prose 544px | `.chapter-head` had no measure of its own |
| Topbar 32px wide at ≤68rem | `.topbar` spanned `grid-column: 1 / -1` in a grid that collapses to one column |
| Theme toggle label was a lie | `aria-label` never updated from the stored theme |
| Progress bar had no number | `.progress` printed "Read" plus a 2px bar |

## The design: a reader shell

Chosen theme: **Almanac** (reference-book register — slate paper, blue-black ink, one deep
magenta under 5%, Hanken Grotesk heads, Newsreader prose, IBM Plex Mono tabular figures,
three rule weights, square corners, no cards).

```
┌──────────────────────────────────────────────────────────────┐
│ The Shape of a Token · 10 · Why generation is slow…  10/31  Search / Theme │
├───────────────┬──────────────────────────────┬───────────────┤
│ Contents      │  Chapter head                │ In this       │
│ I. Raw mat.   │  ─────────────────────────   │ chapter       │
│ 01 Tokens  ●  │  h1 · thesis · meta line     │ • heading     │
│ …             │  prose + inline figures      │ Read 29%      │
└───────────────┴──────────────────────────────┴───────────────┘
```

Front page: a **cover** that owns the fold (title, standfirst, one sentence, actions, facts
row), then the contents index immediately below, then reading paths, then the live numbers,
then the colophon. Nothing is hidden behind a preface.

- **Figures**: on the sheet (`--color-sheet`), ink rule at the head, caption in the display
  face, placed **inside** the prose after the first paragraph of the matching `h3`.
- **Contents index**: title + minutes, thesis as a tooltip, 31 rows of ~0.5rem padding.
- **Folio**: `10 / 31` in the topbar, so the book reads as a book.
- **Provenance**: first 8 rows visible, the rest behind `<details>`.

## Steps

1. ✅ Reader shell in `build.py` (`page()`, `rail_html()`, `topbar_html()`, `rail_slot()`).
2. ✅ Cover + contents index at the top of the front page; rail visible on it.
3. ✅ Light/dark tokens + pre-paint boot; toggle persists and labels itself correctly.
4. ✅ Search index builder (`search_chunks`, `write_search_index`) + `mountShell()` in `site.js`
   (719 passages → `search-index.json`, lazily fetched).
5. ✅ `site.js` copied from the repo root by `build.py`.
6. ✅ Almanac stylesheet replacing the old `CSS` block.
7. ✅ Diagram overflow fixed at the root in `diagrams.py` (0 labels past their viewBox).
8. ✅ Figures placed inline from the spec's `section`.
9. ✅ Editorial review applied (cover order, rail on front page, meta line split, progress
   number, provenance collapse, about-page voice, shared footer).
10. ✅ Visual/accessibility review applied: contrast (all text ≥4.5 in both themes),
    topbar grid, theme label, search focus trap + focus restore, rail Escape, tap targets
    44px on mobile, `.active` scrollspy styled with a bullet (not colour alone).
11. ✅ Final `sloplint --render`, `verify_site.sh`, `docs/` rebuilt, committed, pushed.

## Known deliberate waivers

- **sloplint 58** ("about 80 words on one screen") fires on chapter prose and on the
  contents index. A chapter is a long-form reading page, not a landing page. Recorded here
  rather than "fixed" by cutting a book to eighty words.
- **sloplint 44c / 79** (hero ends early, empty space to the fold) read a chapter head as a
  marketing hero. The rail and the first paragraph fill the screen for a reader.
- **sloplint 77** (six to nine sections) counts `<section>`; a chapter is one article.
- **sloplint 49a/49b** (nav labels wrap to two lines): the labels are chapter headings. Two
  lines at 320px is the correct behaviour; shortening them would rename the book's sections.

## Verification

```
python3 diagrams.py && python3 build.py && ./verify_site.sh   # must print OK: 36 pages, gates clean
node /home/gbajpai/.agents/skills/hallmark/scripts/sloplint.mjs build.py --genre editorial --render \
  --url http://localhost:8123/index.html --url http://localhost:8123/chapters/10-kv-cache.html
```

Every number in `verify_site.sh`'s rig check still matches `content/sources.json`.
