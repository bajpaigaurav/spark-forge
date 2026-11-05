#!/usr/bin/env python3
"""The revisit pass: expert review and diagrams for published chapters.

Two senior reviewers read each chapter and return findings; a diagram planner
decides what figure, if any, the chapter's argument needs. Kept separate from
forge.py because the write/critique/revise/gate loop is unattended and this pass
is supervised: findings are applied by a person, not published automatically.

Reviewers deliberately overlap on purpose. The ML engineer checks that the
mechanism is described correctly and that the arithmetic is right; the AI ops
engineer checks that the operational claim survives contact with a real
deployment. A chapter can be mechanically correct and still wrong about what
happens when you run it at concurrency 64 for a week.
"""
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = HERE
REVIEWS = os.path.join(ROOT, "state", "reviews")
DIAGRAMS = os.path.join(ROOT, "state", "diagrams")

ML_REVIEWER = """You are a senior ML engineer reviewing one chapter of a book about how a
language model works, from tokenizer to sampler. You have implemented attention, trained
models, and debugged quantization.

Report ONLY findings where the chapter is factually WRONG or MISLEADING. At most five
bullets. Each bullet: quote the offending clause, then state the correction in one sentence.
Look for: an incorrect mechanism, wrong arithmetic or units, two distinct concepts treated
as one, a misattributed paper or author.

If nothing is wrong, reply exactly: NONE

Do not discuss style, structure, or what could be added. Do not summarise the chapter.
Do not plan. Answer immediately, in under 250 words."""

OPS_REVIEWER = """You are a senior AI/MLOps engineer who runs inference fleets. You have been
paged because a KV pool filled up and debugged a scheduler that starved long requests.

Report ONLY findings where the chapter is WRONG OR MISLEADING IN PRACTICE. At most five
bullets. Each bullet: quote the offending clause, then state the correction in one sentence.
Look for: a figure presented as general when it holds only at one concurrency, a memory claim
that ignores the allocator or fragmentation, a "cheaper" claim that moves the cost elsewhere,
an operational cost the chapter omits, a conclusion true at the measured scale and false at
production scale.

Assume the mechanism is correct and ask whether the operational consequence follows.
If nothing is wrong, reply exactly: NONE

Do not discuss style or structure. Do not plan. Answer immediately, under 250 words."""

DIAGRAM_PLANNER = """You choose whether a chapter of a book about language models needs a
figure. The book has almost no figures, and several chapters argue from a structure the
reader has to hold in their head.

Add a figure only when it shows a STRUCTURE the prose describes in sequence: a dataflow, a
memory layout, a pipeline with stages, tensor shapes and their dimensions, a tradeoff curve,
or a comparison across configurations. A figure that restates one sentence is not worth
adding. Chapters that argue by arithmetic or history need none.

Return JSON only, no prose:
{"needed": true|false, "kind": "flow"|"layout"|"curve"|"comparison"|"shapes"|"none",
 "title": "short figure caption", "why": "one sentence on what it carries",
 "nodes": ["..."], "notes": "what is on each axis, what flows into what, which quantities
 are labelled and where they come from"}

Never invent a number. Any quantity the figure labels must already appear in the chapter or
be a structural constant. Decide immediately, do not deliberate."""

VERIFY_REVIEWER = """You are adjudicating another reviewer's finding about a technical book.
You are given the chapter, the finding, and the reviewer's claim. Your job is to REFUTE it
if you can. A finding survives only if it is clearly correct and materially improves the
chapter.

Return JSON only:
{"verdict": "confirmed"|"refuted"|"uncertain",
 "reason": "one or two sentences",
 "fix": "the concrete edit if confirmed, else empty string"}

Be strict. If the reviewer misread the chapter, misunderstood the mechanism, or the
"error" is actually a defensible simplification the chapter flags, refute it. If you are
not sure, say uncertain rather than confirmed."""


def chapter_path(cid):
    return os.path.join(ROOT, "content", "chapters", cid + ".md")


def chapter_text(cid):
    p = chapter_path(cid)
    if not os.path.exists(p):
        return None
    return open(p, encoding="utf-8").read()


def published_ids():
    q = json.load(open(os.path.join(ROOT, "state", "queue.json"), encoding="utf-8"))
    return [c["id"] for c in q["chapters"] if c["status"] == "published"]


def chapter_meta(cid):
    q = json.load(open(os.path.join(ROOT, "state", "queue.json"), encoding="utf-8"))
    for c in q["chapters"]:
        if c["id"] == cid:
            return c
    return None


def save_review(cid, reviewer, text):
    os.makedirs(REVIEWS, exist_ok=True)
    p = os.path.join(REVIEWS, f"{cid}.{reviewer}.txt")
    open(p, "w", encoding="utf-8").write(text)


def load_review(cid, reviewer):
    p = os.path.join(REVIEWS, f"{cid}.{reviewer}.txt")
    if not os.path.exists(p):
        return None
    return open(p, encoding="utf-8").read()


def save_diagram(cid, spec):
    os.makedirs(DIAGRAMS, exist_ok=True)
    p = os.path.join(DIAGRAMS, cid + ".json")
    json.dump(spec, open(p, "w", encoding="utf-8"), indent=2)


def load_diagram(cid):
    p = os.path.join(DIAGRAMS, cid + ".json")
    if not os.path.exists(p):
        return None
    return json.load(open(p, encoding="utf-8"))


def findings(report):
    """Split a reviewer report into individual findings.

    The reviewers now answer in terse bullets (a quoted clause plus the correction),
    so a finding is a bullet or a sentence, not a labelled section. A report that says
    NONE carries no findings.
    """
    if not report:
        return []
    if report.strip().upper().startswith("NONE"):
        return []
    out = []
    for line in report.splitlines():
        s = line.strip()
        if not s:
            continue
        s = re.sub(r"^[-*\u2022\d.\s]+\s*", "", s)
        if not s or s.upper() == "NONE":
            continue
        if len(s) < 15:
            continue
        out.append(("finding", s))
    return out


if __name__ == "__main__":
    print("published:", len(published_ids()))
    print("reviews:", len(os.listdir(REVIEWS)) if os.path.isdir(REVIEWS) else 0)
    print("diagrams:", len(os.listdir(DIAGRAMS)) if os.path.isdir(DIAGRAMS) else 0)
