#!/usr/bin/env python3
"""Adjudicate the reviewers' findings, then apply the ones that survive.

Usage:
    python3 apply_review.py verify <chapter>     # adjudicate every finding on one chapter
    python3 apply_review.py verify-all           # every published chapter, resumable
    python3 apply_review.py apply <chapter>      # rewrite the chapter from confirmed fixes
    python3 apply_review.py report               # verdict tally

Findings are adjudicated by VERIFY_REVIEWER, which is told to refute. A finding that is
refuted, or that merely asks for hedging, is dropped: the review asked for factual errors
and material nuance, not a hedge on every sentence.

Why the verdicts are chunked too
--------------------------------
run_verify sends the whole chapter plus the finding, which is the same prompt shape that
spirals for the reviewers. It gets the chapter section the finding actually quotes from,
found by matching the quoted clause, so the verifier sees the sentence in its paragraph.
"""
import json
import os
import re
import sys
import time

import forge
import review
import review_run

HERE = os.path.dirname(os.path.abspath(__file__))
VERDICTS = os.path.join(HERE, "state", "verdicts")


def verdict_path(cid, reviewer):
    return os.path.join(VERDICTS, f"{cid}.{reviewer}.json")


def load_verdicts(cid, reviewer):
    p = verdict_path(cid, reviewer)
    if not os.path.exists(p):
        return []
    return json.load(open(p, encoding="utf-8"))


def save_verdicts(cid, reviewer, rows):
    os.makedirs(VERDICTS, exist_ok=True)
    json.dump(rows, open(verdict_path(cid, reviewer), "w", encoding="utf-8"), indent=1)


def quoted_clause(finding):
    """The clause a finding quotes, used to locate the paragraph it is about."""
    m = re.search(r"[“\"']([^”\"']{12,200})[”\"']", finding)
    return m.group(1) if m else None


def locate_section(text, finding):
    """Return the section of the chapter a finding is about.

    Prefer the section containing the quoted clause; fall back to the section sharing the
    most words with the finding, which still beats sending the whole chapter.
    """
    chunks = review_run.sections(text)
    q = quoted_clause(finding)
    if q:
        for c in chunks:
            if q in c:
                return c
        # Quotes may be lightly reworded or LaTeX-escaped; try the longest fragment.
        frag = re.sub(r"\s+", " ", q)[:60]
        for c in chunks:
            if frag and frag in re.sub(r"\s+", " ", c):
                return c
    words = set(re.findall(r"[a-z]{4,}", finding.lower()))
    best, score = chunks[0], -1
    for c in chunks:
        s = len(words & set(re.findall(r"[a-z]{4,}", c.lower())))
        if s > score:
            best, score = c, s
    return best


def verify_finding(cid, finding, reviewer):
    text = review.chapter_text(cid)
    section = locate_section(text, finding)
    user = f"""A section of a chapter about how language models work:

{section}

A {reviewer} reviewer made this finding about it:

{finding}

Check the finding against the section. Does it hold?"""
    out = review_run.ask(review.VERIFY_REVIEWER, user, max_tokens=12000)
    if not out:
        return {"verdict": "uncertain", "reason": "verifier returned nothing", "fix": ""}
    raw = out.strip()
    if "```" in raw:
        raw = raw.split("```")[1]
        raw = raw[4:] if raw.startswith("json") else raw
    s, e = raw.find("{"), raw.rfind("}")
    if s < 0 or e < 0:
        return {"verdict": "uncertain", "reason": raw[:300], "fix": ""}
    try:
        v = json.loads(raw[s:e + 1])
    except json.JSONDecodeError:
        return {"verdict": "uncertain", "reason": raw[:300], "fix": ""}
    v.setdefault("verdict", "uncertain")
    v.setdefault("reason", "")
    v.setdefault("fix", "")
    return v


def verify_chapter(cid):
    """Adjudicate every finding on one chapter, resuming where it left off."""
    budget = int(os.environ.get("REVIEW_BUDGET", "1500"))
    for reviewer in ("ml", "ops"):
        rep = review.load_review(cid, reviewer)
        if not rep:
            continue
        rows = load_verdicts(cid, reviewer)
        done = {r["finding"] for r in rows}
        for _, finding in review.findings(rep):
            if finding in done:
                continue
            forge.DEADLINE = time.time() + budget
            v = verify_finding(cid, finding, reviewer)
            rows.append({"reviewer": reviewer, "finding": finding, **v})
            save_verdicts(cid, reviewer, rows)
            print(f"  {reviewer} {v['verdict']:<10} {finding[:70]}", flush=True)
    return rows


def tally():
    counts = {}
    for f in os.listdir(VERDICTS) if os.path.isdir(VERDICTS) else []:
        for r in json.load(open(os.path.join(VERDICTS, f), encoding="utf-8")):
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    return counts


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]

    if cmd == "report":
        print(json.dumps(tally(), indent=1))
        return 0

    if cmd == "verify-all":
        for cid in review.published_ids():
            if all(os.path.exists(verdict_path(cid, r)) for r in ("ml", "ops")):
                continue
            print(cid, flush=True)
            verify_chapter(cid)
        print(json.dumps(tally(), indent=1))
        return 0

    if len(sys.argv) < 3:
        print("need a chapter id")
        return 1
    cid = sys.argv[2]
    if cmd == "verify":
        verify_chapter(cid)
        return 0
    print(f"unknown command {cmd}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
