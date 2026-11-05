#!/usr/bin/env python3
"""Run the expert reviewers over published chapters.

Usage:
    python3 review_run.py ml 01-tokens       # one chapter, ML reviewer
    python3 review_run.py ops 01-tokens
    python3 review_run.py diagram 01-tokens
    python3 review_run.py all                # every published chapter, all three

Writes state/reviews/<id>.<reviewer>.txt and state/diagrams/<id>.json.
Findings are NOT applied automatically; a person reads them and edits the chapter.

Why the review is chunked
-------------------------
Reviewing a whole chapter in one prompt does not converge. The model reasons until
max_tokens runs out and returns zero content with finish=length: measured on
02-embeddings (2,271 words, 13,307-char prompt) at both 16k and 20k budgets. Raising
the budget only buys more reasoning -- 80k -> 160k bought 160k reasoning tokens and
1,374s with no content -- so budget size is not the lever.

A chapter reviewed in sections fits comfortably. Each section is reviewed on its own
and the findings are merged, so no single call has to hold the whole chapter while it
thinks. The section size below is deliberately small.
"""
import json
import os
import re
import sys
import time

import forge
import review

# Words per review section. Measured on 06-multi-head with the ML reviewer at 16k budget:
# 650 words -> finish=length (16000 reasoning, 0 content, 234s), 450 words -> finish=stop
# (4140 reasoning, 130 words, 78s), 300 words -> finish=stop (3146 reasoning, 64s).
# The cliff is between 450 and 650, so 450 is the ceiling.
SECTION_WORDS = 450


def ask(system, user, max_tokens=16000):
    # retries=2, not the default 5: a review section either answers or spirals, and the
    # retries are near-deterministic (5 identical attempts at 16k all consumed the budget
    # on 02-embeddings section 2). Spending 13 minutes on 5 identical failures is worse
    # than dropping one section, since the findings from the other sections still merge.
    return forge.call_model(system, user, max_tokens=max_tokens,
                            temperature=0.3, effort="low", retries=2)


def sections(text, words=SECTION_WORDS):
    """Split a chapter into paragraph-aligned chunks of roughly `words` words."""
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    out, cur, n = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and n + w > words:
            out.append("\n\n".join(cur))
            cur, n = [], 0
        cur.append(p)
        n += w
    if cur:
        out.append("\n\n".join(cur))
    return out


def review_in_sections(cid, reviewer_system, reviewer_name):
    """Review a chapter section by section and merge the findings."""
    text = review.chapter_text(cid)
    if not text:
        return None
    meta = review.chapter_meta(cid)
    chunks = sections(text)
    parts = []
    for i, chunk in enumerate(chunks, 1):
        out = ask(reviewer_system, _section_prompt(meta, i, len(chunks), chunk))
        if not out:
            # A section that spirals is usually too long. Split it once and retry the
            # halves rather than dropping the section's findings entirely.
            halves = sections(chunk, words=max(200, SECTION_WORDS // 2))
            if len(halves) > 1:
                print(f"    section {i}/{len(chunks)} spiralled; retrying as {len(halves)} parts",
                      flush=True)
                got = False
                for j, half in enumerate(halves, 1):
                    h = ask(reviewer_system, _section_prompt(meta, f"{i}.{j}", len(chunks), half))
                    if h and not h.strip().upper().startswith("NONE"):
                        parts.append(h.strip())
                        got = True
                if got:
                    continue
            print(f"    section {i}/{len(chunks)} failed", flush=True)
            continue
        if out.strip().upper().startswith("NONE"):
            continue
        parts.append(out.strip())
    merged = "\n".join(parts) if parts else "NONE"
    review.save_review(cid, reviewer_name, merged)
    return merged


def _section_prompt(meta, idx, total, chunk):
    return f"""Chapter {meta['number']}: {meta['title']}
Thesis: {meta['thesis']}

This is section {idx} of {total} of the chapter. Review only this section.

{chunk}"""


def run_ml(cid):
    return review_in_sections(cid, review.ML_REVIEWER, "ml")


def run_ops(cid):
    return review_in_sections(cid, review.OPS_REVIEWER, "ops")


def run_diagram(cid):
    """Decide the chapter's figure, planning per section and merging.

    A whole-chapter prompt spirals here too, so the planner sees one section at a time
    and the per-section proposals are merged into a single spec. The first section that
    says a figure is needed wins; the notes are concatenated so the drawing has context
    from the whole chapter.
    """
    text = review.chapter_text(cid)
    if not text:
        return None
    meta = review.chapter_meta(cid)
    chunks = sections(text)
    specs = []
    for i, chunk in enumerate(chunks, 1):
        user = f"""Chapter {meta['number']}: {meta['title']}
Thesis: {meta['thesis']}

This is section {i} of {len(chunks)}. Should a figure illustrate the argument in this
section? If yes, say what it shows.

{chunk}"""
        out = ask(review.DIAGRAM_PLANNER, user, max_tokens=12000)
        if not out:
            continue
        raw = out.strip()
        if "```" in raw:
            raw = raw.split("```")[1]
            raw = raw[4:] if raw.startswith("json") else raw
        s, e = raw.find("{"), raw.rfind("}")
        if s < 0 or e < 0:
            continue
        try:
            spec = json.loads(raw[s:e + 1])
        except json.JSONDecodeError:
            continue
        if spec.get("needed"):
            spec["section"] = i
            specs.append(spec)

    if not specs:
        spec = {"needed": False, "kind": "none", "title": "", "why": "",
                "nodes": [], "notes": ""}
        review.save_diagram(cid, spec)
        return spec

    # Merge: keep the first proposed figure, and collect every section's notes so the
    # drawing is informed by the whole chapter rather than one paragraph.
    merged = dict(specs[0])
    merged["notes"] = " | ".join(s["notes"] for s in specs if s.get("notes"))
    merged["sections"] = [s["section"] for s in specs]
    review.save_diagram(cid, merged)
    return merged


def run_verify(cid, finding, reviewer="ml"):
    """Adjudicate one finding. Returns the verdict dict."""
    text = review.chapter_text(cid)
    user = f"""Chapter text:

{text}

A {reviewer} reviewer made this finding:

{finding}

Check it against the chapter. Does the finding hold?"""
    out = ask(review.VERIFY_REVIEWER, user, max_tokens=12000)
    if not out:
        return {"verdict": "uncertain", "reason": "verifier returned nothing", "fix": ""}
    raw = out.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.startswith("json") else raw
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e < 0:
        return {"verdict": "uncertain", "reason": raw[:200], "fix": ""}
    try:
        return json.loads(raw[s:e + 1])
    except json.JSONDecodeError:
        return {"verdict": "uncertain", "reason": raw[:200], "fix": ""}


def done(cid, name):
    if name == "diagram":
        return os.path.exists(os.path.join(review.DIAGRAMS, cid + ".json"))
    return os.path.exists(os.path.join(review.REVIEWS, f"{cid}.{name}.txt"))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    ids = review.published_ids()
    budget = int(os.environ.get("REVIEW_BUDGET", "1200"))

    if cmd == "all":
        for cid in ids:
            for name, fn in (("ml", run_ml), ("ops", run_ops), ("diagram", run_diagram)):
                if done(cid, name):
                    continue
                # A fresh deadline per job. One deadline for the whole pass silently
                # stopped it partway through, leaving most chapters unreviewed.
                forge.DEADLINE = time.time() + budget
                print(f"{cid} {name}...", flush=True)
                try:
                    r = fn(cid)
                except Exception as e:
                    print(f"  ERROR {type(e).__name__}: {e}", flush=True)
                    continue
                print(f"  {'ok' if r else 'FAILED'}", flush=True)
        return 0

    if cmd == "verify":
        if len(sys.argv) < 4:
            print("usage: review_run.py verify <chapter> <reviewer>")
            return 1
        cid, rev = sys.argv[2], sys.argv[3]
        rep = review.load_review(cid, rev)
        if not rep:
            print("no review on disk")
            return 1
        forge.DEADLINE = time.time() + budget
        for _, finding in review.findings(rep):
            v = run_verify(cid, finding, rev)
            print(json.dumps({"finding": finding, **v}, indent=1))
        return 0

    if len(sys.argv) < 3:
        print("need a chapter id")
        return 1
    cid = sys.argv[2]
    fn = {"ml": run_ml, "ops": run_ops, "diagram": run_diagram}.get(cmd)
    if not fn:
        print(f"unknown command {cmd}")
        return 1
    forge.DEADLINE = time.time() + budget
    r = fn(cid)
    print(json.dumps(r, indent=2) if isinstance(r, dict) else (r or "FAILED"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
