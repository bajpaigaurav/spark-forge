#!/usr/bin/env bash
# probe.sh -- the two hand-run probes behind the throughput and clock numbers
# in chapter 31, plus the /metrics scrape the derived figures came from.
#
# WHAT THIS IS
#   A transcription of the commands, in the order they were run, with the
#   constants the book reports substituted in. It is meant to be read first and
#   run second.
#
# WHAT THIS IS NOT
#   Untested. Every command here was run on the author's pair, an NVIDIA DGX
#   Spark (GB10), against a specific engine build. Nothing below has been tried
#   on other hardware or other engines. Endpoint names, flag spellings and the
#   metric names in particular are engine-specific: `tensorfold:` metrics are
#   this engine's, not a standard. Expect to edit the URL and the metric names
#   before anything returns a number.
#
# SAFETY
#   Read-only with respect to the engine: it issues HTTP GETs and one
#   nvidia-smi query. It does start up to $PARALLEL concurrent generation
#   requests, so it does load the machine. Do not run it on a box that is
#   serving someone else.
#
# CONSTANTS
#   Every number below is from content/sources.json. The source string of the
#   entry it came from is quoted beside it. Values the book does not record are
#   left as <angle-bracket placeholders> and are never guessed.

set -u

# source: "CONTEXT=262144 in scripts/local.sh, rank1 --pool 262144"
POOL=262144
# source: "PARALLEL=4, TF_DS_STREAMS=4 in the live container env"
PARALLEL=4
# source: "MAX_TOKENS=32768, --max-tokens 32768 in the live serve argv"
MAX_TOKENS=32768
# source: "ROUND_ROWS=16, the pinned kit's maximum row kernel"
ROUND_ROWS=16

# Not recorded in sources.json. Set these yourself.
METRICS_URL="${METRICS_URL:-http://<engine-host>:<metrics-port>/metrics}"
GENERATE_URL="${GENERATE_URL:-http://<engine-host>:<metrics-port>/v1/completions}"

# The benchmark's own constants, from the "measured:" entries.
# source: "measured: 4 requests x 400 completion tokens"
BENCH_TOKENS=1600
# source: "measured: max_tokens=400 in the concurrency benchmark requests"
REPLY_BUDGET=400
# source: "measured: total time for the same 4 prompts run sequentially"
BENCH_C1_WALL=27.1
# source: "measured: wall clock for 4 concurrent 400-token requests"
BENCH_C4_WALL=15.1

# Wall-clock subtraction. `bc` is not installed everywhere, so use awk, which
# is on every POSIX box.
elapsed() { awk -v a="$1" -v b="$2" 'BEGIN { printf "%.2f", b - a }'; }

say() { printf '\n== %s\n' "$*"; }

# ---------------------------------------------------------------------------
# 1. The clock. This is the one probe with no ambiguity.
#    source: "nvidia-smi clocks.sm, 2026-10-31 01:0x"
#    The book reports the SM clock under load. Query it while the engine is
#    busy, not at idle; the number only means something under load.
# ---------------------------------------------------------------------------
say "SM clock under load"
nvidia-smi --query-gpu=clocks.sm --format=csv,noheader || {
  echo "nvidia-smi not found or no GPU visible; the 2,197 MHz figure cannot be reproduced here" >&2
}

# ---------------------------------------------------------------------------
# 2. The counter dump. Everything the book calls "derived" was computed from
#    these counters. The book scraped them on 2026-10-31; the dump itself is
#    not shipped (see README.md), so the only honest way to get the numbers is
#    to scrape again and recompute with the arithmetic printed at the end.
# ---------------------------------------------------------------------------
say "counter dump from $METRICS_URL"
curl -sS --max-time 30 "$METRICS_URL" > metrics-$(date +%Y%m%d).txt || {
  echo "scrape failed; check METRICS_URL" >&2
  exit 1
}
echo "wrote metrics-$(date +%Y%m%d).txt"
# The counters the derived figures rest on. These names are engine-specific.
grep -E '^(tensorfold:)?(request_latency_seconds_(count|sum)|prompt_tokens_total|generation_tokens_total|prefix_cache_(hits|queries)_total|mtp_(accepted|drafted)_total|request_(prefill|decode)_seconds_(sum|count)|time_to_first_token_seconds_(sum|count)|pair_stall_ms|device_memory_bytes)\b' \
  metrics-$(date +%Y%m%d).txt || echo "none of the expected counters matched; the metric names differ on your engine"

# ---------------------------------------------------------------------------
# 3. The concurrency probe. Four distinct prompts, REPLY_BUDGET completion
#    tokens each, run twice: once sequentially (c=1) and once all at once
#    (c=$PARALLEL). Time both with wall clock, as the book did.
#
#    The prompts are not in sources.json, so they are a placeholder. They must
#    be four DISTINCT prompts: the book's own caveat is that the c=4 number is
#    only comparable to c=1 if both runs see the same prompts.
# ---------------------------------------------------------------------------
say "concurrency probe (sequential, c=1)"
C1_START=$(date +%s.%N)
for i in 1 2 3 4; do
  curl -sS --max-time 600 -X POST "$GENERATE_URL" \
    -H 'Content-Type: application/json' \
    -d "{\"prompt\": \"<prompt-$i>\", \"max_tokens\": $REPLY_BUDGET}" \
    > /dev/null || { echo "request $i failed" >&2; exit 1; }
done
C1_END=$(date +%s.%N)
C1=$(elapsed "$C1_START" "$C1_END")
echo "sequential wall: ${C1}s  (book: ${BENCH_C1_WALL}s)"

say "concurrency probe (concurrent, c=$PARALLEL)"
C4_START=$(date +%s.%N)
for i in 1 2 3 4; do
  curl -sS --max-time 600 -X POST "$GENERATE_URL" \
    -H 'Content-Type: application/json' \
    -d "{\"prompt\": \"<prompt-$i>\", \"max_tokens\": $REPLY_BUDGET}" \
    > /dev/null &
done
wait
C4_END=$(date +%s.%N)
C4=$(elapsed "$C4_START" "$C4_END")
echo "concurrent wall: ${C4}s  (book: ${BENCH_C4_WALL}s)"

# ---------------------------------------------------------------------------
# 4. The arithmetic. This is the part a reader CAN reproduce exactly: it needs
#    no hardware, only the constants above. If your machine reproduces the
#    commands, these are the numbers to compare against chapter 31.
# ---------------------------------------------------------------------------
say "arithmetic, no hardware needed"
python3 - "$C1" "$C4" <<'PY'
import sys
c1 = float(sys.argv[1]); c4 = float(sys.argv[2])
tokens = 1600          # source: "measured: 4 requests x 400 completion tokens"
pool, parallel = 262144, 4   # sources: pool, parallel
max_tokens, rows = 32768, 16 # sources: max-tokens, rows
print(f"c=1 aggregate decode : {tokens/c1:8.1f} tok/s   (book reports 59.1)")
print(f"c=4 aggregate decode : {tokens/c4:8.1f} tok/s   (book reports 106.2)")
print(f"concurrency gain     : {(tokens/c4)/(tokens/c1):8.2f}x       (book reports 1.80x)")
print(f"pool split           : {pool//parallel:8d} positions (book: 65,536)")
print(f"admission ceiling    : {pool//parallel - max_tokens - rows - 2:8d} tokens    (book: 32,750)")
print(f"1M pool ceiling      : {1048576//parallel - max_tokens - rows - 2:8d} tokens    (book: 229,358)")
print()
print("The two throughput rows are computed here from 1600 tokens and the two")
print("wall clocks. The book reports 59.1 and 106.2, which differ by a few")
print("tenths: those were derived from the engine's own token counts, not from")
print("1600 divided by the wall clock. A small gap is rounding, not error.")
PY

say "done"
echo "Compare against docs/rig.html, which lists every measured value with its source."
