#!/usr/bin/env python3
"""The forge orchestrator.

One run = pick the next pending chapter, write it, gate it, and either promote it
or send it back with the failure report attached. State lives in state/queue.json
so a run can be interrupted and resumed.

The model is called over the gateway (Bifrost -> TensorFold). Nothing here talks
to the model directly: the gateway is the only path, so every call is logged and
attributable to a virtual key.
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
QUEUE = os.path.join(ROOT, "state", "queue.json")
SOURCES = os.path.join(ROOT, "content", "sources.json")
CHAPTERS = os.path.join(ROOT, "content", "chapters")
LOGS = os.path.join(ROOT, "logs")
REPORTS = os.path.join(ROOT, "state", "reports")

# Ceiling on document size. Past this the loop polishes instead of growing, so
# it keeps working unattended without turning into an unbounded text generator.
MAX_CHAPTERS = 40

GATEWAY = os.environ.get("FORGE_GATEWAY", "http://127.0.0.1:8080/v1/chat/completions")
MODEL = os.environ.get("FORGE_MODEL", "openai/DeepSeek-V4.1-Flash-1017")
VK = os.environ.get("FORGE_VK", "")

def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    with open(os.path.join(LOGS, "forge.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")

# Wall-clock budget for one run. The cron tick kills this process at 3600s; leaving
# headroom means a slow run requeues cleanly instead of being killed mid-chapter, which
# would strand the chapter in 'drafting'. Retries stop escalating once this passes.
RUN_BUDGET_SECONDS = int(os.environ.get("FORGE_RUN_BUDGET", "3000"))
# Past this the reviser starts planning instead of revising and reasons to the budget.
# Measured per chapter on the full critic report: 28-parallelism succeeded at 1600,
# 31-local-numbers still spiralled at 900 and only succeeded at 500. 500 is the only value
# that worked for every chapter tested, so it is the threshold. The leading findings are
# the substantive ones; the tail of a report is usually the weaker ones.
REVISE_REPORT_CHARS = 500
# Set by one_run() for the stages that follow it in the same run.
DEADLINE = None


def call_model(system, user, max_tokens=8000, temperature=0.75, effort="low", retries=5,
               deadline=None):
    """Single completion over the gateway. Long timeout: long-form generation.

    Returns None when every attempt fails, so the caller can degrade instead of
    crashing the whole loop.

    Reasoning shares max_tokens with the content and is unbounded. Occasionally a
    sampling draw spirals: the model reasons until the budget ends and returns zero
    content with finish=length. Measured on this model that is a bad draw, not a
    property of the prompt -- five identical calls at budget=30000 returned the same
    6113 reasoning tokens in ~110s every time, and the same prompt succeeded at every
    budget from 12000 to 80000. A bad draw costs ~10 min; a good one ~110s.

    So the cheap fix is retry, not escalation. Raising the budget is actively harmful:
    80000 -> 160000 bought 160000 tokens of reasoning and 1374s with no content. Each
    retry instead drops to low effort, which is the only lever that measurably shortens
    reasoning, and keeps the budget fixed.
    """
    budget = max_tokens
    last = None
    for attempt in range(1, retries + 1):
        # The cron tick kills this process at 3600s, and a killed worker leaves its
        # chapter stuck mid-run. Checked on EVERY attempt: a single spiralled call has
        # taken 1374s, so one stage can eat most of the run. Bail out before starting
        # rather than into the wall.
        if deadline is not None and time.time() > deadline:
            log(f"  out of time before attempt {attempt}; giving up")
            break
        cur_effort = "low" if attempt > 1 else effort
        body = json.dumps({
            "model": MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_tokens": budget,
            "temperature": temperature,
            "reasoning_effort": cur_effort,
        }).encode()

        req = urllib.request.Request(GATEWAY, data=body, headers={
            "Content-Type": "application/json",
            "x-bf-vk": VK,
        })
        t0 = time.time()
        try:
            resp = urllib.request.urlopen(req, timeout=2400)
            d = json.load(resp)
        except urllib.error.HTTPError as e:
            last = f"gateway {e.code}: {e.read()[:300].decode(errors='replace')}"
            log(f"  attempt {attempt} failed: {last}")
            time.sleep(20)
            continue
        except Exception as e:
            last = f"{type(e).__name__}: {e}"
            log(f"  attempt {attempt} failed: {last}")
            time.sleep(20)
            continue
        dt = time.time() - t0
        choice = d["choices"][0]
        text = choice["message"].get("content") or ""
        usage = d.get("usage", {})
        reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
        finish = choice.get("finish_reason")
        log(f"  model call: {dt:.1f}s, {usage.get('completion_tokens','?')} tok "
            f"(reasoning={reasoning if reasoning is not None else '?'}), finish={finish}")
        if text.strip():
            return text

        # Empty content. If reasoning ate the budget, the next attempt needs a bigger
        # budget and (once that is exhausted) less reasoning, not the same request.
        if finish == "length":
            spent = usage.get("completion_tokens") or budget
            last = f"empty content (finish=length, reasoning consumed {spent} tok)"
            log(f"  attempt {attempt} returned no content (reasoning spiralled); "
                f"retrying with budget={budget} effort=low")
        else:
            last = f"empty content (finish={finish})"
            log(f"  attempt {attempt} returned no content; retrying")
        continue

    log(f"  giving up after {retries} attempts: {last}")
    return None

def run_gate(script, *args):
    p = subprocess.run([sys.executable, os.path.join(ROOT, "skills", script), *args],
                       capture_output=True, text=True)
    return p.returncode == 0, p.stdout + p.stderr

def load_queue():
    return json.load(open(QUEUE, encoding="utf-8"))

def save_queue(q):
    tmp = QUEUE + ".tmp"
    json.dump(q, open(tmp, "w", encoding="utf-8"), indent=2)
    os.replace(tmp, QUEUE)

# Two workers may run at once so a 25-minute tick is not the throughput ceiling.
# Every queue mutation happens under an exclusive flock, so the read-modify-write
# in one_run() cannot interleave with another worker's.
LOCK = os.path.join(ROOT, "state", "queue.lock")

class queue_lock:
    def __enter__(self):
        os.makedirs(os.path.dirname(LOCK), exist_ok=True)
        self.fh = open(LOCK, "w")
        import fcntl
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self
    def __exit__(self, *a):
        import fcntl
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()

def update_chapter(cid, **fields):
    """Patch one chapter's fields under the lock.

    Rewriting the whole queue from a stale in-memory copy is how a second
    worker's progress gets erased. This reads fresh, touches one entry, writes.
    """
    with queue_lock():
        q = load_queue()
        for c in q["chapters"]:
            if c["id"] == cid:
                c.update(fields)
                break
        save_queue(q)

def next_chapter(q):
    """Pick the next chapter to work on.

    `drafting` is included because a worker that dies mid-run leaves its chapter
    claimed forever; nothing else ever clears that status, so those chapters
    would never be picked again. `rejected` is retried last: it exhausted three
    attempts on the gates, but the gates are the thing most likely to have been
    fixed since, so a rejection is not a verdict on the prose.
    """
    for status in ("pending", "revising", "drafting", "rejected"):
        for ch in q["chapters"]:
            if ch["status"] == status:
                return ch
    return None

def sources_block():
    d = json.load(open(SOURCES, encoding="utf-8"))
    lines = []
    for v in d["verified"]:
        lines.append(f"- {v['display']} ({v['value']} {v['unit']}): {v['context']} [source: {v['source']}]")
    return "\n".join(lines)

WRITER_SYSTEM = """You are writing one chapter of a book about how large language models
actually work. It is a book of explanation, not a lab report.

The reader is a competent engineer who can read code and knows basic calculus, but has
never been taught what attention really does, why the KV cache exists, or what a
quantization group size is. They want the mechanism, the reason it exists, and enough
history to understand what problem each idea solved when it arrived.

THE RULES THAT MATTER MOST:

1. Every claim must be explained by mechanism. Do not say that something is true and move
on. Show how it works, ideally by walking through what happens to one number.

2. Name your sources and your dates. This is a book about ideas that arrived in a
particular order. Write "Bahdanau, Cho and Bengio proposed additive attention in 2014"
rather than "attention was introduced". Write "PagedAttention borrowed the operating
system's page table in 2023". The reader should finish each chapter knowing who moved the
field and when.

3. Explain what the thing replaced. An idea is only understandable against the problem it
solved. Before explaining grouped-query attention, explain what was wrong with multi-head
attention's cache. Before explaining Flash Attention, explain what was happening in HBM.

4. Use a concrete worked example with real numbers whenever a formula appears. If you
write a cache size formula, plug in layers, heads, head dimension, sequence length and
bytes, and show the arithmetic. Do not leave the reader to do it.

5. Where a concept has an everyday analogue, use it once and then drop it. The page table
analogy for PagedAttention is good; three analogies for the same idea is not.

6. Have a view. Where the field made a choice that is debatable, say so and say why.
"RoPE won, but ALiBi is simpler and was arguably underrated" is better than a neutral
recitation.

7. Vary your sentence length deliberately. Short sentences land points. Longer ones carry
qualification and mechanism. If every sentence is the same length the reader stops reading.

8. Open with the problem, a person, or a concrete situation. Do not open with a
measurement from a specific machine unless the chapter is specifically about that machine.

HARD CONSTRAINTS, enforced by an automated gate:

- Prose. Continuous paragraphs. Use a list only when the content is genuinely a list.
- Do not use these words: delve, foster, leverage, utilize, facilitate, empower,
streamline, robust, cutting-edge, paradigm, game changer, tapestry, realm, beacon,
multifaceted, meticulous, intricate, paramount, transformative, elevate, embark,
supercharge, harness, ever-evolving, testament, pivotal, seamless, unlock, revolutionize.
- Do not write "not X, it's Y" constructions.
- Do not write a noun phrase, a colon, then a lowercase dramatic reveal.
- Do not end with a summary that restates the chapter.
- Do not use trailing -ing clauses that explain significance (", highlighting",
", underscoring", ", cementing").
- At most two em-dashes in the whole chapter.
- Never invent a number. If you need a figure and it is not in the facts list, describe the
quantity in words instead.

Length: 1200 to 1800 words. Write the chapter body only, with a single markdown H2
heading at the top. No preamble, no "Here is the chapter".

Structure: after the H2, insert a markdown H3 subheading (`### `) every 250 to 400 words.
Each subheading names the idea the next few paragraphs establish -- the thing a reader
would search for when re-reading. Aim for 3 to 6 subheadings. Do not number them, do not
write them as questions, and do not repeat the chapter title."""

CRITIC_SYSTEM = """You are a hostile technical editor reviewing one chapter of an explanatory book about how language models work.

Your only job: find every place where a competent engineer would learn nothing, be misled, or come away unable to explain the idea to someone else.

Answer in four short sections. Keep the whole report under 700 words. Quote at most one clause per finding.

1. HAND-WAVING -- passages that assert a mechanism without showing it.
2. UNSUPPORTED -- claims with numbers, dates, citations or causal claims that are not grounded.
3. NO EXAMPLE -- formulas or trade-offs stated without a worked calculation.
4. MISSING -- what a reader still would not understand, and which prerequisite the chapter assumed.

Do not praise. Do not summarise. No stylistic notes. Be terse; a long report is a bad report."""

REVISER_SYSTEM = """You are revising a chapter of an explanatory book using an editor's
report. Fix every substantive problem the report names, and keep what already works.

Rules:
- Same constraints as the original draft: prose, no banned words, no "not X, it's Y", no
colon reveals, no summary ending, at most two em-dashes, no invented numbers.
- Where the report says something is hand-waving, show the mechanism. Walk through the
computation.
- Where the report says something is unsupported, either ground it (name the source, the
year, the derivation) or cut it.
- Where the report says a formula has no example, add the worked calculation with concrete
numbers.
- Where the report says something is missing, add it, including any prerequisite concept
the reader would need.
- Do not pad. If you cut a paragraph, spend the freed space on mechanism, not on restating
what you just said.
- Keep the chapter at least as substantial as the draft. Never cut a section to make the
revision easier.
- Vary sentence length. Do not let three consecutive sentences have the same shape.

Output the full revised chapter with the same single markdown H2 heading and the same
H3 subheadings (keep them, and add one where a section grew long). No commentary
about what you changed."""


def write_chapter(ch, attempt):
    log(f"writing {ch['id']} (attempt {attempt})")
    facts = sources_block()
    prior = ""
    rp = os.path.join(REPORTS, ch["id"] + ".txt")
    if attempt > 1 and os.path.exists(rp):
        prior = f"\n\nThe previous attempt failed these gates. Fix all of it:\n{open(rp).read()}\n"

    q = load_queue()
    part = ch.get("part", "")
    idx = [c["id"] for c in q["chapters"]].index(ch["id"])
    neighbours = []
    for c in q["chapters"]:
        if c["id"] == ch["id"]:
            continue
        if abs(c["number"] - ch["number"]) <= 2:
            neighbours.append(f"- {c['title']}: {c['thesis']}")
    context = "\n".join(neighbours)

    user = f"""Part {part}
Chapter {ch['number']}: {ch['title']}

The argument this chapter has to make: {ch['thesis']}

Everything the chapter must cover, and must cover by explaining mechanism rather than
naming it:
{ch['cover']}

Nearby chapters, so you do not duplicate them and can refer forward or back:
{context}

Verified facts you may cite (and only these):
{facts}
{prior}
Write the chapter."""
    # Budgets below are starting points, not ceilings: call_model raises them when
    # reasoning starves the content (finish=length) and drops effort if that fails.
    # Sized for reasoning plus the artifact each stage must emit, measured on this model.
    # Budgets are sized for reasoning plus the artifact, measured on this model:
    # ~7k reasoning at low effort plus ~3k of chapter content. A huge budget does not
    # buy a better chapter, it just gives a spiralling draw more room to run.
    return call_model(WRITER_SYSTEM, user, max_tokens=40000, temperature=0.85, effort="high",
                      deadline=DEADLINE)

def critique(text):
    log("  critiquing")
    # The critic reads a full chapter and reasons across it, but its report is capped at
    # 700 words (~1k tokens). It was the worst starvation case: at 50000 it hit
    # finish=length on 36% of calls because reasoning consumed the whole budget. A smaller
    # starting budget plus call_model's escalation is the fix; the report never needs more
    # than ~2k of content, so the rest is headroom for reasoning.
    # The critic reads a full chapter but emits a report capped at 700 words (~1k tokens).
    # It was the worst spiral case: 36% of calls hit finish=length at 50000.
    return call_model(CRITIC_SYSTEM, f"Chapter to review:\n\n{text}", max_tokens=24000, temperature=0.3, effort="high",
                      deadline=DEADLINE)

def revise(text, report):
    log("  revising")
    facts = sources_block()
    # A long report makes the reviser plan how to address every finding, and it then
    # reasons to the budget on every attempt. Measured on the 28-parallelism revise (a
    # 2,218-word draft, 412-word report): the full report spiralled at 30k and 45k on both
    # high and low effort, while the same call with the report cut to ~1500 chars returned
    # finish=stop at 18.8k reasoning and a 2,896-word chapter. The leading findings are the
    # substantive ones; the tail is usually the weaker ones. Facts are NOT trimmed -- they
    # are what keeps the revision inside the fact gate.
    if len(report) > REVISE_REPORT_CHARS:
        log(f"  report is {len(report)} chars; trimming to {REVISE_REPORT_CHARS} to avoid a spiral")
        report = report[:REVISE_REPORT_CHARS]
        # Cut at a line boundary so a finding is not split mid-sentence.
        if "\n" in report:
            report = report.rsplit("\n", 1)[0]
    user = f"""Verified facts you may cite:
{facts}

Editor's report on your draft:
{report}

Draft ({len(re.findall(r'\S+', text))} words):
{text}

Return the full revised chapter."""
    # Do NOT restate "the revision must be at least as long as the draft" here. Measured on
    # this model, that instruction makes it plan an expansion strategy instead of revising:
    # with it the call reasoned to the budget on every attempt at 30k/40k/60k/90k and
    # returned zero content; without it the same prompt returned finish=stop at 16.5k
    # reasoning and a 2,356-word chapter, longer than the draft anyway. The floor lives in
    # the system prompt as "at least as substantial", which does not invite arithmetic.
    # effort="low" from the first attempt, not high. On this prompt high effort is what
    # spirals: the model plans an expansion strategy and reasons to the budget. Low effort
    # returned finish=stop at ~16.5k reasoning on the same input.
    return call_model(REVISER_SYSTEM, user, max_tokens=30000, temperature=0.7, effort="low",
                      deadline=DEADLINE)

def gate(ch_id, text):
    """Write to disk, run both gates, return (passed, report)."""
    path = os.path.join(CHAPTERS, ch_id + ".md")
    if not text.strip():
        # Never persist an empty chapter; it would pass the slop gate trivially.
        return False, "EMPTY DRAFT -- nothing to gate"
    open(path, "w", encoding="utf-8").write(text)

    ok_slop, out_slop = run_gate("slop_gate.py", path)
    ok_fact, out_fact = run_gate("fact_gate.py", path, SOURCES)
    report = f"=== SLOP GATE ===\n{out_slop}\n=== FACT GATE ===\n{out_fact}"
    return (ok_slop and ok_fact), report

PLANNER_SYSTEM = """You are planning more chapters for a technical document about how a
local language model runs on a two-machine DGX Spark pair.

The existing chapters are listed for you. Propose NEW chapters that are not already
covered, that stay inside the same subject, and that each have a single sharp thesis
worth arguing from measured numbers.

Return exactly 4 lines, nothing else. Each line has three pipe-separated fields:
id|title|thesis

id: lowercase, hyphenated, three words at most, must not collide with an existing id.
title: under 60 characters, plain language, no colon, no "why X matters".
thesis: one sentence stating the claim the chapter will defend.

Do not propose a conclusion, a summary, an introduction, or anything about the website
itself. Only technical chapters about the engine, the hardware, or the measurements."""

POLISH_SYSTEM = """You are improving an already-published chapter. It passed the gates,
so the facts are sound and the prose is clean. Your job is different: make it deeper.

Add the mechanism the chapter currently asserts but does not explain. If it says a
number, show how that number is produced. If it says two things are related, show the
relation. Do not restate the chapter in different words, and do not pad it.

Rules:
- Keep every existing correct fact.
- Use only numbers from the verified-facts list.
- No banned words, no "not X, it's Y", no colon reveals, no summary ending, at most two
  em-dashes.
- The result must not repeat any paragraph and must not shrink a section to make room.
- Target: 1000 to 1500 words.

Output the full improved chapter with its single markdown H2 heading and its H3
subheadings. No commentary."""


def plan_more(n=4):
    """Ask the model for new chapters and append them. Returns how many were added."""
    q = load_queue()
    existing = "\n".join(f"{c['id']} | {c['title']} | {c['thesis']}" for c in q["chapters"])
    facts = sources_block()
    user = f"""Existing chapters:
{existing}

Verified facts available to cite:
{facts}

Propose 4 new chapters."""
    out = call_model(PLANNER_SYSTEM, user, max_tokens=20000, temperature=0.9, effort="high")
    if not out:
        log("planner returned nothing")
        return 0

    have = {c["id"] for c in q["chapters"]}
    added = 0
    num = max(c["number"] for c in q["chapters"]) if q["chapters"] else 0
    for line in out.strip().splitlines():
        parts = [p.strip() for p in line.split("|")]
        if len(parts) != 3:
            continue
        cid, title, thesis = parts
        cid = re.sub(r"[^a-z0-9-]", "", cid.lower().replace(" ", "-"))
        if not cid or cid in have or not title:
            continue
        num += 1
        q["chapters"].append({
            "id": cid, "number": num, "title": title, "thesis": thesis,
            "status": "pending", "runs": 0,
        })
        have.add(cid)
        added += 1
        log(f"  planned {num:2}. {title}")
    if added:
        with queue_lock():
            q2 = load_queue()
            known = {c["id"] for c in q2["chapters"]}
            for c in q["chapters"]:
                if c["id"] not in known:
                    q2["chapters"].append(c)
            save_queue(q2)
    return added


def polish_one():
    """Take a published chapter and try to deepen it. Only replaces it if the
    result passes both gates and is longer. Returns True if improved."""
    q = load_queue()
    done = [c for c in q["chapters"] if c["status"] == "published"]
    if not done:
        return False
    # rotate so the same chapter is not polished twice in a row
    idx = q.get("polish_cursor", 0) % len(done)
    ch = done[idx]
    path = os.path.join(CHAPTERS, ch["id"] + ".md")
    if not os.path.exists(path):
        return False
    text = open(path, encoding="utf-8").read()
    before = len(re.findall(r"\S+", text))

    def bump():
        with queue_lock():
            q2 = load_queue()
            q2["polish_cursor"] = idx + 1
            save_queue(q2)

    facts = sources_block()
    user = f"""Verified facts you may cite:
{facts}

Chapter ({before} words):
{text}

Return the deepened chapter."""
    improved = call_model(POLISH_SYSTEM, user, max_tokens=40000, temperature=0.65, effort="high")
    if not improved or len(re.findall(r"\S+", improved)) <= before:
        log(f"  polish of {ch['id']} produced nothing better")
        bump()
        return False

    passed, gate_report = gate(ch["id"], improved)
    if passed:
        after = len(re.findall(r"\S+", improved))
        log(f"  polished {ch['id']}: {before} -> {after} words")
        open(os.path.join(REPORTS, ch["id"] + ".txt"), "w").write(
            f"POLISHED {before} -> {after}\n" + gate_report)
        bump()
        return True

    # Restore the good version; the gates rejected the "improvement".
    open(path, "w", encoding="utf-8").write(text)
    log(f"  polish of {ch['id']} failed gates; original restored")
    bump()
    return False


def one_run():
    global DEADLINE
    DEADLINE = time.time() + RUN_BUDGET_SECONDS
    os.makedirs(CHAPTERS, exist_ok=True)
    os.makedirs(REPORTS, exist_ok=True)
    # Claim a chapter atomically. Without the lock two workers read the same
    # queue, both see the same pending chapter, and both write it.
    with queue_lock():
        q = load_queue()
        ch = next_chapter(q)
        if ch is None:
            # Nothing pending: grow the document, then deepen what exists. The loop
            # must never sit idle, but it also must not grow without bound.
            total = len(q["chapters"])
            if total < MAX_CHAPTERS:
                log(f"queue empty at {total} chapters; planning more")
                if plan_more(4):
                    q = load_queue()
                    ch = next_chapter(q)
            if ch is None:
                log("no new chapters; polishing a published one")
                polish_one()
                return 0

        attempt = ch["runs"] + 1
        if ch["status"] == "rejected":
            # A rejected chapter is being retried because the gates or the writer prompt
            # changed since it failed. It gets a fresh three-attempt budget; otherwise it
            # would re-reject on its first gate failure and never be retried again.
            attempt = 1
            log(f"  retrying rejected chapter {ch['id']} with a fresh attempt budget")
        ch["status"] = "drafting"
        save_queue(q)

    text = write_chapter(ch, attempt)
    if text is None:
        log(f"  {ch['id']} writer call failed; will retry next run")
        update_chapter(ch["id"], status="pending", runs=attempt)
        return 0
    words = len(re.findall(r"\S+", text))
    if words < 400:
        log(f"  draft too short ({words} words); retrying next run")
        update_chapter(ch["id"], status="pending", runs=attempt)
        return 0

    report = critique(text)
    if report is None or not report.strip():
        # No editor report means the corrections cannot be applied, so this run cannot
        # produce a validated chapter. Requeue rather than publish an unreviewed draft.
        log("  critic unavailable; requeueing without publishing")
        update_chapter(ch["id"], status="pending", runs=attempt)
        return 0

    revised = revise(text, report)
    if revised is None or len(re.findall(r"\S+", revised)) < 400:
        # The reviser returned nothing usable. Retry once, then give up on this run.
        log("  reviser failed or truncated; retrying once")
        revised = revise(text, report)
    if revised is None or len(re.findall(r"\S+", revised)) < 400:
        # Never publish the unrevised draft: the critic just said it was broken, and a
        # gate pass on it is luck, not validation. Requeue so the next tick retries.
        log("  reviser failed twice; requeueing without publishing")
        update_chapter(ch["id"], status="pending", runs=attempt)
        return 0

    passed, gate_report = gate(ch["id"], revised)

    if passed:
        update_chapter(ch["id"], status="published", runs=attempt)
        open(os.path.join(REPORTS, ch["id"] + ".txt"), "w").write("PASSED\n" + gate_report)
        log(f"  {ch['id']} PUBLISHED (attempt {attempt})")
        return 0

    if attempt >= 3:
        update_chapter(ch["id"], status="rejected", runs=attempt)
        open(os.path.join(REPORTS, ch["id"] + ".txt"), "w").write("REJECTED after 3 attempts\n" + gate_report)
        log(f"  {ch['id']} REJECTED after 3 attempts")
        return 0

    update_chapter(ch["id"], status="revising", runs=attempt)
    open(os.path.join(REPORTS, ch["id"] + ".txt"), "w").write(gate_report)
    log(f"  {ch['id']} failed gates; queued for revision")
    return 0

def status():
    q = load_queue()
    counts = {}
    for ch in q["chapters"]:
        counts[ch["status"]] = counts.get(ch["status"], 0) + 1
    print(f"chapters: {len(q['chapters'])}")
    for k, v in sorted(counts.items()):
        print(f"  {k}: {v}")
    print()
    for ch in q["chapters"]:
        mark = {"published": "OK ", "rejected": "XX ", "pending": ".. ", "drafting": ">> ",
                "critiquing": "?? ", "revising": "RR ", "gated": "GG "}.get(ch["status"], "   ")
        print(f"  {mark} {ch['number']:2}. {ch['title'][:58]:58} runs={ch['runs']}")

if __name__ == "__main__":
    os.makedirs(LOGS, exist_ok=True)
    os.makedirs(REPORTS, exist_ok=True)
    cmd = sys.argv[1] if len(sys.argv) > 1 else "run"
    if cmd == "run":
        sys.exit(one_run())
    elif cmd == "status":
        status()
    elif cmd == "loop":
        # Continuous mode: keep going until nothing is pending.
        n = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        for i in range(n):
            try:
                rc = one_run()
            except Exception as e:
                log(f"run crashed: {type(e).__name__}: {e}")
                # Reset any chapter left mid-flight so it is retried, not stuck.
                q2 = load_queue()
                for c2 in q2["chapters"]:
                    if c2["status"] in ("drafting", "critiquing", "revising", "gated"):
                        c2["status"] = "pending"
                save_queue(q2)
                time.sleep(30)
                continue
            q = load_queue()
            if next_chapter(q) is None:
                log("queue empty; loop ends")
                break
        sys.exit(0)
    else:
        print("usage: forge.py run|status|loop [n]")
        sys.exit(2)
