#!/usr/bin/env python3
"""Insert section subheadings into the 31 published chapters.

The writer prompt now asks for H3 subheads, but the chapters were written before
that rule existed: every chapter has exactly one `##` (its title) and no subheads
at all, so a reader has no resumption points.

This is a structure-only pass. It sends each chapter to the model and asks for the
same prose back with `### ` headings inserted at argument boundaries -- it may not
rewrite, add, or cut sentences. The result is then checked mechanically:

  - the word count must match within 2% (no prose added or lost)
  - every sentence of the original must still be present (no rewriting)
  - at least 3 subheads must appear

If any check fails the chapter is left untouched and reported, so a bad pass cannot
damage a published chapter. Resumable: already-processed chapters are skipped.
"""
import json
import os
import re
import sys
import time

import forge

ROOT = os.path.dirname(os.path.abspath(__file__))
CHAPTERS = os.path.join(ROOT, "content", "chapters")
STATE = os.path.join(ROOT, "state", "subheads.json")

SYSTEM = """You are inserting section headings into an already-written chapter of an
explanatory book about how language models work.

Your ONLY job is to add `### ` subheadings. You must not rewrite, reword, reorder, add,
or delete a single sentence. Return the chapter text exactly as given, with `### `
headings inserted at the boundaries between arguments.

Rules:
- Insert 3 to 6 subheadings.
- A subheading names the idea the following paragraphs establish: the phrase a reader
  would search for when re-reading. Examples of the right shape: "Why the cache is
  the wall", "What the allocator actually stores", "The arithmetic behind 34 GB".
- Do not number them. Do not phrase them as questions. Do not repeat the chapter title.
- Place a heading only where the argument genuinely turns; do not chop a derivation
  into confetti.
- Keep the opening `## ` chapter title line exactly as it is.
- Output the chapter text only. No commentary, no preamble, no code fences."""


def words(s):
    return len(re.findall(r"\S+", s))


def sentences(s):
    s = re.sub(r"^#.*$", "", s, flags=re.M)
    s = re.sub(r"\s+", " ", s)
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+", s) if len(x.strip().split()) > 3]


def check(original, revised):
    """Mechanical proof that the pass only added headings."""
    problems = []
    wo, wr = words(original), words(revised)
    # Heading words are legitimate additions; allow them plus a small margin.
    added_heads = len(re.findall(r"^###\s+", revised, re.M))
    budget = wo + added_heads * 8 + max(3, wo // 50)
    if wr > budget:
        problems.append(f"grew {wo} -> {wr} words")
    if wr < wo - max(3, wo // 50):
        problems.append(f"shrank {wo} -> {wr} words")
    heads = re.findall(r"^###\s+(\S.*)$", revised, re.M)
    if len(heads) < 3:
        problems.append(f"only {len(heads)} subheads")
    # Every original sentence must survive verbatim.
    rs = " ".join(sentences(revised))
    missing = [s for s in sentences(original) if s not in rs]
    if missing:
        problems.append(f"{len(missing)} original sentences missing/changed, e.g. "
                        f"{missing[0][:80]!r}")
    return problems, heads


def process(cid):
    p = os.path.join(CHAPTERS, cid + ".md")
    text = open(p, encoding="utf-8").read()
    if len(re.findall(r"^###\s+", text, re.M)) >= 3:
        return "already has subheads", [], None
    out = forge.call_model(SYSTEM, text, max_tokens=12000, temperature=0.3,
                           effort="low", retries=4)
    if not out:
        return "model returned nothing", [], None
    out = out.strip()
    out = re.sub(r"^```\w*\n|\n```$", "", out).strip()
    problems, heads = check(text, out)
    if problems:
        return "REJECTED: " + "; ".join(problems), [], None
    return "ok", heads, out


def main():
    ids = sys.argv[1:] or [f[:-3] for f in sorted(os.listdir(CHAPTERS)) if f.endswith(".md")]
    done = {}
    if os.path.exists(STATE):
        done = json.load(open(STATE, encoding="utf-8"))
    for cid in ids:
        if done.get(cid, {}).get("status") == "ok":
            print(f"{cid}: already done, skipping")
            continue
        t0 = time.time()
        status, heads, revised = process(cid)
        print(f"{cid}: {status} ({time.time()-t0:.0f}s)")
        for h in heads:
            print(f"    ### {h}")
        if status == "ok" and revised is not None:
            # Only written back after passing the mechanical check.
            p = os.path.join(CHAPTERS, cid + ".md")
            open(p, "w", encoding="utf-8").write(revised + "\n")
            done[cid] = {"status": "ok", "heads": heads}
            json.dump(done, open(STATE, "w"), indent=2)


if __name__ == "__main__":
    main()


if __name__ == "__main__":
    main()
