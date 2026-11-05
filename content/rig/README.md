# The rig artifact

This directory ships what can honestly be shipped about the machine behind the
last part of *The Shape of a Token*. It is not the raw scrape.

## What is here

- `serve-argv.txt` — the serve command line and container environment the
  numbers were taken under. The four constants (`POOL`, `PARALLEL`,
  `MAX_TOKENS`, `ROUND_ROWS`) are transcribed from `content/sources.json`, with
  the `source` string of the entry each came from quoted above it.
- `probe.sh` — the commands a reader would run to reproduce the measured
  values: the `nvidia-smi` clock query, the `/metrics` scrape, the
  sequential-vs-concurrent throughput probe, and the arithmetic that turns the
  wall clocks into the throughput figures in chapter 31.

## What is not here, and why

**The raw metrics dump is not shipped.** The 98-request counter dump was
scraped from `/metrics` on 2026-10-31 on a machine that is not this repository.
It is not in the repo, and it has not been reconstructed. A dump rebuilt from
memory would be a fabricated artifact, which is worse than no artifact at all:
it would look checkable while proving nothing. If you want the counters, scrape
your own with `probe.sh` and run the same arithmetic.

**`scripts/local.sh` is not shipped.** The book cites one line of it
(`CONTEXT=262144`). The script's body lives on the author's machine, not here.
Transcribing only the cited line is the honest move; inventing the rest is not.

**The benchmark prompts are not shipped.** They are not in `sources.json`, so
they appear as `<prompt-N>` placeholders in `probe.sh`. They were four distinct
prompts, which matters: the c=1 and c=4 numbers are only comparable when both
runs see the same prompts.

## What a reader can and cannot reproduce

**Can:** the commands. Every step in `probe.sh` is a plain HTTP GET, an
`nvidia-smi` query, or a `curl` POST. Run them against your own engine and you
get numbers of the same shape.

**Can:** the arithmetic. The pool split (`262144/4 = 65,536`), the admission
ceiling (`65,536 - 32,768 - 16 - 2 = 32,750`) and the 1M-pool ceiling
(`1,048,576/4 = 262,144`, then `- 32,768 - 16 - 2 = 229,358`) are pure integer
arithmetic on constants recorded in `sources.json`. They need no hardware and
reproduce exactly. The two decode figures (59.1 and 106.2) are arithmetic too,
but they came from the engine's own token counts, not from 1,600 divided by the
wall clock, so your own division will land a few tenths away.

**Cannot:** the hardware. The 273 GB/s of LPDDR5X bandwidth, the 3,003 MHz
silicon maximum and the 2,197 MHz observed clock are properties of an NVIDIA
DGX Spark (GB10) on a particular day. A different box will differ, and that is
the point of the book's own caveat.

**Cannot:** the date. The scrape is one 98-request window on 2026-10-31. The
workload was whatever that machine was serving then. Your traffic will not
match it, so your counters will not match the derived averages.

## A note on placeholders

Anything not recorded in `content/sources.json` is left as an
`<angle-bracket-placeholder>` rather than filled in. That includes the engine
binary, the model path, the HTTP port, the benchmark prompts, and the host in
the metrics URL. If a value is not in `sources.json`, this artifact does not
claim to know it.

The full table of measured values, with their sources and contexts, is on
`rig.html` at the site root.
