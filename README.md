# The Shape of a Token

A book about how a language model actually works, from the tokenizer to the sampler, written
and gated by an unattended loop and published as a hand-built site.

Read it at **https://bajpaigaurav.github.io/spark-forge/** (GitHub Pages, served from
`docs/`).

## What it is

31 chapters in 8 parts:

| Part | Chapters |
|---|---|
| I. The raw material | tokenizer, embeddings, residual stream |
| II. Attention | pre-attention, scaled dot-product, multi-head, softmax, positions, the quadratic wall |
| III. The cache | KV cache, MQA/GQA/MLA, PagedAttention, prefix caching, Flash Attention, sparsity |
| IV. The rest of the block | FFN, activations, normalization, mixture of experts |
| V. Precision | fp32 to fp8, quantization, why four bits works |
| VI. Producing a token | logits, sampling, speculative decoding |
| VII. Serving | prefill/decode, batching, parallelism, roofline |
| VIII. Grounding it | measurement, and the same book measured on two small machines |

Each chapter carries a `cover` list of exactly what it must explain by mechanism, and the
writer prompt names the sources and dates it should cite. Chapter 1 explains BPE as Gage's
1994 compression scheme before it explains it as a tokenizer. Chapter 4 explains what
Bahdanau was trying to fix before attention is introduced.

## The pipeline

`forge.py run` does one pass on the next chapter:

1. **write** — drafts from the chapter's thesis, its cover list, and neighbouring chapters
2. **critique** — a hostile editor returns four sections: HAND-WAVING / UNSUPPORTED /
   NO EXAMPLE / MISSING
3. **revise** — rewrites from that report; must not shrink
4. **gate** — two mechanical checks, both must pass
5. publish, or requeue (3 failures → rejected)

The critic earns its keep. On the tokenizer chapter it caught that "twelve years" between
1994 and 2016 is actually twenty-two, and that the coauthor is Barry Haddow, not "Barry
Hieber".

## The two gates

**`skills/slop_gate.py`** — banned words, empty phrases, and sentence shapes that give away
a machine: binary contrast, colon reveal, participle analysis, summary recap, rhetorical
setup, weasel attribution, importance puffery. Plus an em-dash density ceiling.

**`skills/fact_gate.py`** — separates two kinds of number, deliberately:

- *Measurement claims* — anything with a thousands separator, or a unit (GB, tok/s, layers,
  dimensions, bytes, percent). These must trace to `skills/textbook.json` (published constants
  with their source) or be derived in the paragraph that uses them from inputs the chapter
  already prints. A fabricated "111.5 GB" or "59.1 tok/s" cannot survive.
- *Illustrative integers* — token ids, ranges like "30 or 40", counts in a worked example,
  bare decimals that are cosine similarities or probabilities. These are allowed, because
  the reader can check them from the numbers printed beside them.

The split matters. A book about LLMs has to mention 4,096 dimensions and 128k vocabularies;
a claim about one machine has to mention a bandwidth and a weight size. Confusing the two
makes a fact checker useless in one direction or the other.

`skills/textbook.json` holds 149 published constants with provenance: paper years, model
dimensions, vocabulary sizes, A100 and H100 and GB10 bandwidths, quantization group sizes,
and the derived arithmetic each chapter uses. `content/sources.json` holds no measurements:
the book cites published figures only.

## The site

Hand-written. One stylesheet, one markup generator, one JS file, no frameworks, no build
step, no dependencies.

- `index.html` — frontispiece, live figures strip read from Prometheus, table of contents
  grouped by part
- `chapters/*.html` — one page per chapter, with an auto-generated provenance table listing
  every number the chapter cites and where it came from
- `about.html` — how the loop works, including what it got wrong

Three interactives, each tied to a specific chapter's argument:

- **`01-tokens`** — type a word, watch a real greedy BPE merge it using a merge table. The
  splits are arbitrary and corpus-dependent, which is the chapter's whole point.
- **`05-scaled-dot-product`** — one query scoring against its context, with a temperature
  slider. Shows the raw scores, the softmax shares, and the entropy as it sharpens or
  flattens. This is the exact reason attention stops learning when scores get large.
- **`10-kv-cache`** — the cache size formula with every factor exposed as a slider. Two
  tensors × layers × KV heads × head dim × positions × bytes.

## Running it

```bash
cd ~/spark-forge && set -a; . ./.env; set +a
python3 forge.py run        # one pass
python3 forge.py status     # queue state
python3 forge.py loop 40    # continuous
```

Unattended: `~/.hermes/scripts/forge_tick.sh` runs **two workers in parallel**, rebuilds,
verifies, and sends a Telegram line only when something published or failed. Registered as
a Hermes cron job.

Two workers exist because a single chapter costs roughly 17 minutes of model time
(write, then critique, then revise). One worker per 25-minute tick capped throughput at
one chapter per tick, which needed about ten hours to clear the remaining 25 chapters.
Two workers overlap the model calls, which is where the wall clock goes.

`state/queue.json` is guarded by an exclusive `flock` (`forge.queue_lock`), and every
status change goes through `update_chapter()`, which re-reads the queue under the lock
before touching one entry. Without that, two workers would read the same queue, both pick
the same pending chapter, and the second writer would erase the first one's progress.

```bash
hermes cron list | grep Forge
hermes cron pause  eb8ff5b0656a     # pause
hermes cron resume eb8ff5b0656a     # resume
```

GitHub Pages serves `docs/` from `main`, at `https://bajpaigaurav.github.io/spark-forge/`.
`docs/` is a committed copy of the built site, refreshed by `./build_site.sh` (rebuild,
verify, then copy `site/` into `docs/`). Commit `docs/` whenever the chapters change.
`site/` is the working build directory and is gitignored.

## Verification

```bash
./verify_site.sh                                      # rebuild + structural + gates
./build_site.sh                                       # rebuild + verify + refresh docs/
python3 audit_design.py chapters/01-tokens.html       # computed-style audit via CDP
```

### The fact gate has two jobs

`skills/textbook.json` holds published constants (paper years, model dimensions,
vocabulary sizes, hardware specs). `content/sources.json` is reserved for a measurement
a chapter reports first-hand, and it is empty: every figure in the book is published or
derived. A book about language models must cite 4096 dimensions; a claim about one machine
must cite a bandwidth. Confusing the two makes the checker useless in one direction.

### Zero tolerance, and why it needed a derivation detector

The gate allows **no** unmatched measurement claims. An earlier version tolerated
up to four "incidentals", which meant an injected `47.3 GB at 812.6 MB/s` passed
untouched. That tolerance is gone.

Removing it exposed the opposite problem: a book about cost and memory does
arithmetic in the prose, and every result looked fabricated. So `derived_numbers()`
accepts a figure when the chapter prints the inputs it came from and those inputs are
themselves sourced. Three forms are recognised: an explicit equation
(`786,432 x 921.6 = 724.8 MB`), a bare product (`2 x 130,659 x 128`), and a stated
result whose factors appear in the same clause. Chains resolve by iterating, so
`724.8 -> 0.675` works once 724.8 is established.

The rule stays strict: a result counts only if **every** factor is already allowed.
Verified with negative tests — `47.3 GB`, `94.7 tok/s` and `138.2 GB` all fail.

One real bug this found: the number regex used `(?<![\w/])`, so in
`786,432/1,048,576` the scan resumed at the comma and captured `048,576` as a
phantom unsourced measurement. The lookbehind now excludes commas too.

### Known limits

The derivation detector matches phrasing, not semantics. A chapter that writes
"the total comes to 964 MB" without printing its factors needs the constant added
to `textbook.json` by hand. That is the intended escape hatch, and it keeps the
provenance list honest: every derived number in the book has a written
derivation.

`verify_site.sh` checks: page count matches published count, part headings match the plan,
no page repeats its own title, script paths resolve from both depths, every interactive is
wired to the id the JS queries, and every published chapter still passes both gates.

`audit_design.py` drives headless Chrome over the DevTools Protocol and asserts the serif
stack resolved, the prose measure is under 720px, the SVG has non-zero size, and nothing
overflows horizontally.

## Files

```
forge.py              orchestrator: write, critique, revise, gate, plan, polish
build.py              markdown -> HTML, hand-rolled; owns the CSS and page structure
site/site.js          four interactives, no dependencies
skills/slop_gate.py   style gate
skills/fact_gate.py   fact gate (measurement claims vs illustrative integers)
skills/textbook.json  149 published constants with provenance
content/plan.json     the 31-chapter plan: parts, theses, cover lists
content/sources.json  reserved for first-hand measurements; empty by design
content/chapters/     published markdown
state/queue.json      the queue and its state
docs/                 the committed site GitHub Pages serves
build_site.sh         rebuild, verify, and copy site/ into docs/
```

Generated, not committed: `site/` (the working build directory), `logs/` (machine-local
run output), and `.env` (the gateway key). `verify_site.sh` locates its own tree, so it
works in a clone as well.

## The revisit pass: expert review and figures

After the 31 chapters were published, a supervised pass read every one of them as a senior
ML engineer and as an AI/MLOps engineer, adjudicated the findings, and drew a figure for
each chapter. The prose is the same book; what changed is that 489 confirmed corrections
landed in it and every chapter now carries two figures, or three where a distinct
quantitative argument needs its own drawing. The 31 chapters hold 70 figures in all.

```bash
python3 review_run.py all                 # both reviewers plus the figure planner, resumable
python3 apply_review.py verify-all        # adjudicate every finding, resumable
python3 apply_fixes.py --all --write      # apply the confirmed ones
python3 diagrams.py                       # render site/figures/<id>.svg from the specs
./verify_site.sh                          # rebuild and check
```

`review_run.py` and `apply_review.py` write to `state/reviews/`, `state/diagrams/` and
`state/verdicts/`, so every stage resumes where it stopped.

**Why the review is chunked.** Reviewing a whole chapter in one prompt does not converge.
The model reasons until `max_tokens` runs out and returns zero content with `finish=length`.
Measured on `06-multi-head` at a 16k budget: 650 words in the prompt spiralled (16,000
reasoning tokens, no output, 234s), 450 words answered (4,140 reasoning, 130 words, 78s),
300 words answered faster still. So a chapter is reviewed 450 words at a time and the
findings merge; a section that still spirals is split once and retried as halves. That took
the spiral rate from 23% to 4%.

**Why findings are adjudicated before they land.** The reviewers are told to report only
what is wrong or misleading, and they still over-report: of 1,160 findings, the verifier
refuted 654 (56%). A verifier that is told to refute is cheaper than a wrong edit. One
example: a reviewer claimed chapter 10's `98,092` was bad arithmetic, but
`229,358 - 131,266 = 98,092` is correct and the reviewer had double-counted the 32,768
reservation.

**Why the figures are hand-rendered.** `diagrams.py` draws from a fixed vocabulary of
thirteen kinds -- token strips, matrices, timelines, memory maps, bit fields, bars, log
axes, panels, lanes, flows, grids, BPE traces, and vocabulary stacks -- so the book's
figures look like one set. Each is inline SVG with no script of its own; the animation
layer in `figures.js` is an enhancement over the static drawing. Figures inherit the
page's CSS variables, print with the page, and remain complete with JavaScript off. Every
animated figure carries a static fallback, a `<desc>`, keyboard controls, a pause when it
scrolls out of view, and no transition under `prefers-reduced-motion`. Nothing in a figure
is invented: the planner was told to label only quantities that already appear in the
chapter.

## Known limits

- Reasoning is unbounded and shares `max_tokens` with the content. Measured on this model a
  2.2k-word chapter costs ~8k reasoning tokens at low effort, ~7k at medium, and 12k+ at
  high; at high effort it reasons until the budget ends and returns zero content with
  `finish=length`. A fixed budget cannot fix that, so `call_model` escalates on retry:
  drop effort to low first (the lever that actually shortens reasoning), then raise the
  budget past the ~12k reasoning plateau, which is where content starts flowing. Retrying
  the identical request, which is what stalled the loop for hours, never works.
- One run has a 3000s wall-clock budget (`FORGE_RUN_BUDGET`), under the cron tick's 3600s
  kill. Once it passes, `call_model` stops escalating and returns None so the chapter is
  requeued cleanly; otherwise a slow run is killed mid-chapter and left in `drafting`.
  A stale `drafting` chapter is reclaimable, so a killed worker does not strand it.
- Bifrost's request timeout is 1800s in `~/spark-gateway/data/config.json`; the default 300s
  is too short.
- `textbook.json` is hand-curated. A chapter that needs a figure nobody published will fail
  rather than guess. That is the intended behaviour and the main reason the prose stays
  trustworthy. Derived figures are added by hand with their derivation written out, which
  is why the provenance list stays honest rather than being a list of exemptions.
- The last part is the only part that describes this specific machine. Everything before it
  would be true on any hardware.

## Tests

```bash
python3 tests/test_call_model.py    # reasoning-starvation escalation + deadline
python3 tests/test_fact_gate.py     # derivation forms, and fabrications that must fail
python3 tests/test_review.py        # finding parsing and section splitting
python3 tests/test_apply_fixes.py   # punctuation repair, and the ranges it must not touch
```

Both stub the model and assert on the request bodies or the derived set, so they cost
nothing and run in a second. They exist because each pins a bug that silently stalled the
loop: an identical retry on a starved call, and `int(2.5**2) == 6` matching the `6` inside
`812.6`, which let a fabricated figure derive.
