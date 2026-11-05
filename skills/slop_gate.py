#!/usr/bin/env python3
"""Mechanical slop detection. No vibes, no model call -- just patterns that
reliably mark machine-written prose. Exits 1 if the draft fails the gate."""
import json
import re
import sys

BANNED_WORDS = [
    "delve", "foster", "leverage", "utilize", "facilitate", "empower",
    "streamline", "robust", "cutting-edge", "paradigm", "game changer",
    "tapestry", "realm", "beacon", "multifaceted", "meticulous", "intricate",
    "paramount", "transformative", "elevate", "embark", "supercharge",
    "harness", "ever-evolving", "testament", "pivotal", "seamless",
    "unlock", "revolutionize", "dive into", "dive deep",
]

EMPTY_PHRASES = [
    "it's worth noting", "it is worth noting", "it's important to note",
    "at the end of the day", "when it comes to", "at its core",
    "in today's world", "in the age of", "the reality is", "the truth is",
    "in terms of", "with regard to", "in order to", "going forward",
    "in this article", "let's dive in", "let us dive in",
    "here's the thing", "here is the thing", "let me be clear",
    "the uncomfortable truth", "what most people", "what nobody tells you",
    "the part everyone misses", "this is huge", "this changes everything",
    "as you can see", "that last part matters", "the key point is",
    "this distinction matters", "in other words",
]

# Sentence-level patterns. Each is (name, regex, why it reads as machine prose).
PATTERNS = [
    ("binary-contrast",
     re.compile(r"\b(?:is|was|are|were)\s+not\s+(?:just\s+)?[^.;]{3,60}[.;]\s*(?:It|it|That|that|They|they)\s+(?:is|was|are|were)\b", re.I),
     "Not-X-but-Y construction states Y by negating X first."),
    ("colon-reveal",
     re.compile(r"^[A-Z][^.!?:]{10,70}:\s+[a-z]", re.M),
     "Noun phrase, colon, lowercase dramatic reveal."),
    ("ing-analysis",
     re.compile(r",\s+(?:highlighting|underscoring|reflecting|showcasing|demonstrating|illustrating|emphasizing|signaling)\b", re.I),
     "Trailing -ing clause that pretends to explain meaning."),
    ("summary-recap",
     re.compile(r"\b(?:In conclusion|To sum up|Ultimately|In summary|All in all|To conclude)\b", re.I),
     "Recap ending restates what the reader just read."),
    ("rhetorical-setup",
     re.compile(r"\b(?:What if I told you|Think about it|Plot twist|Here's what I mean)\b", re.I),
     "Self-answered rhetorical setup."),
    ("weasel-attribution",
     re.compile(r"\b(?:Experts agree|industry reports suggest|many argue|widely regarded|studies show|researchers believe)\b", re.I),
     "Unnamed source doing the arguing."),
    ("importance-puffery",
     re.compile(r"\b(?:stands as a testament|marks a pivotal moment|plays a vital role|solidifies its position|underscores its significance)\b", re.I),
     "Tells the reader a fact is important instead of showing why."),
]

def scan(text):
    findings = []
    low = text.lower()

    for w in BANNED_WORDS:
        for m in re.finditer(r"\b" + re.escape(w), low):
            findings.append(("banned-word", w, m.start()))

    for p in EMPTY_PHRASES:
        for m in re.finditer(re.escape(p), low):
            findings.append(("empty-phrase", p, m.start()))

    for name, rx, why in PATTERNS:
        for m in rx.finditer(text):
            findings.append((name, m.group(0)[:70].replace("\n", " "), m.start()))

    # Em-dash density: more than 2 per 1000 words is a rhythm crutch.
    words = len(re.findall(r"\S+", text))
    dashes = text.count("\u2014")
    if words > 200 and dashes / words * 1000 > 2:
        findings.append(("em-dash-density", f"{dashes} per {words} words", 0))

    return findings

def main():
    path = sys.argv[1]
    text = open(path, encoding="utf-8").read()
    findings = scan(text)

    words = len(re.findall(r"\S+", text))
    print(f"file: {path}")
    print(f"words: {words}")
    print(f"findings: {len(findings)}")

    if findings:
        counts = {}
        for kind, sample, _ in findings:
            counts[kind] = counts.get(kind, 0) + 1
        print("\nby kind:")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v}")
        print("\nsamples:")
        for kind, sample, pos in findings[:15]:
            print(f"  [{kind}] {sample!r}")
        # Threshold: a long chapter may carry one or two. More is slop.
        limit = max(2, words // 900)
        print(f"\nlimit for {words} words: {limit}")
        if len(findings) > limit:
            print("GATE: FAIL")
            return 1
        print("GATE: PASS (within tolerance)")
        return 0

    print("GATE: PASS (clean)")
    return 0

if __name__ == "__main__":
    sys.exit(main())
