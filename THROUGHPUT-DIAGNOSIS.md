# Why the model felt slow, and what was actually happening

Measured on this box, 2026-10-31. Every number here came from a request this
document's author made, not from a vendor datasheet.

## Short version

The model never degraded. The engine is serving `--parallel 4`. When more than one
long request is in flight, they share those four slots, and each stream gets slower.
I ran two forge workers plus subagents against a 4-slot engine and pushed your
interactive requests into multi-minute waits. That was my mistake, not the model's.

## The measurement

Idle engine, one small request: **0.19–0.27 s**. TTFT on a 64-token generation:
**0.88 s**. The engine is healthy.

Throughput under load, same prompt, 400 output tokens:

| concurrency | per-stream | aggregate |
|---|---|---|
| 1 stream | **31.2 tok/s** | 31.2 tok/s |
| 4 streams | **14.9 tok/s** | 59.4 tok/s |

So batching does raise total throughput (31 → 59 tok/s), but it halves what any one
caller sees. A 4-slot engine serving 4 streams is doing exactly what it was
configured to do. There is no fault.

## What the gateway log showed during the spike

Between 04:01 and 04:29 the log recorded requests at 383 s, 412 s and 493 s. Those
were forge's chapter calls: 16,753–17,351 completion tokens each, delivering
35–44 tok/s. They overlapped with each other and with pi's subagents.

Then 04:34–04:36 dropped to 9–15 s. Nothing changed except that the long calls
finished. Same engine, same model, 30× faster.

That is the whole story: the p95 spike tracked concurrency, not a regression.

## The specific things that caused it

1. **Two forge workers.** I made the tick script run two `forge.py run` processes in
   parallel to halve the time to finish the book. Each holds a slot for 5–8 minutes
   per chapter. That alone can consume half the engine.

2. **Subagents on the same 4 slots.** Two fact-checking agents plus two forge workers
   is four concurrent long requests against `--parallel 4`. Nothing is left over for
   you.

3. **Long generations.** Each chapter is a writer call (up to 26,000 max_tokens), then
   a critic call, then a reviser call. The model also spends reasoning tokens before
   the first content token. A single chapter is 15–20 minutes of wall clock across
   three calls.

## What I changed

`~/.hermes/scripts/forge_tick.sh` now runs **one** worker per tick, with a comment
explaining why it must stay that way and citing the 31.2 vs 14.9 measurement. The
loop still runs every 25 minutes; it just no longer competes with you.

The queue locking in `forge.py` stays. That was a correctness fix, not a throughput
one: without it, any two runs that ever overlapped would claim the same chapter and
erase each other's status. I verified it with six concurrent threads claiming six
distinct chapters and zero duplicates.

## What you can do if it happens again

```bash
# what is running
ps -eo pid,etime,cmd | grep forge.py | grep -v grep

# who is using the model, last hour
sqlite3 ~/spark-gateway/data/logs.db \
  "select virtual_key_name, count(*), round(avg(latency)/1000.0,1) avg_s
   from logs where datetime(timestamp)>=datetime('now','-1 hour') group by 1;"

# pause the book loop while you work
hermes cron pause eb8ff5b0656a
hermes cron resume eb8ff5b0656a
```

## The real fix, if you want one

Forge currently uses **GBMainKey — the same virtual key as pi**. That means the log
cannot tell the book's traffic apart from yours, and the per-key panels I just added
to Grafana lump them together.

A separate `ForgeKey` would make the split visible and let you rate-limit the loop
independently. I did not create it: `governance_virtual_keys.value` is encrypted with
a 64-hex-character key that Bifrost uses internally, and writing a row by hand means
reimplementing their encryption. Create it in the dashboard (`http://192.168.1.10:8080`,
Governance → Virtual Keys), then set `FORGE_VK` in `~/spark-forge/.env`.

## One lever that costs nothing

`reasoning_effort` barely moves this model. On a real reasoning prompt, low, medium
and high all produced 126 completion tokens and 46 reasoning tokens in ~2.5 s. So
there is no cheap setting that makes forge's calls much shorter — the cost is the
long-form generation itself. If you want the book to stop competing with you, the
answer is scheduling, not configuration.
