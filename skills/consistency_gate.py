#!/usr/bin/env python3
"""Consistency gate for an explanatory book.

The slop gate bans cliche wording. The fact gate makes every number trace to a source.
Neither asks whether the book agrees with itself. Three defects shipped through both:

  1. A revise-loop merge pasted a clause twice inside one sentence (ch 09).
  2. A revise-loop merge pasted two fragments twice in one paragraph (ch 12).
  3. One paragraph computed bytes with an extra factor d and still called the result
     "one head of one layer", two paragraphs after computing the same quantity without
     the factor and calling it the same thing (ch 14). The arithmetic was right; the
     label was wrong.

So this gate checks self-consistency in four ways:

  1. Duplicate sentences. A sentence longer than eight words that appears twice is
     almost always a merge artifact, not rhetoric.
  2. Duplicate fragments. The ch 12 defect was a clause, not a sentence. A repeated
     span of twelve or more words inside one paragraph is the merge signature: the
     tail of the old paragraph was never removed before the new text was appended.
  3. Derivation self-consistency. Entries in content/sources.json whose source begins
     with "derived:" state their arithmetic. Evaluate it and compare to the value.
  4. Unit/label consistency. An expression A x A x B x 2 = C counts L^2 entries times
     d times two bytes: that is the score matrix for d heads, not for one. Flag when
     prose calls it "one head" (or the reverse).

Exit code is 1 on any finding, matching fact_gate.py.

Usage:
  python3 skills/consistency_gate.py [chapter.md ...]
  python3 skills/consistency_gate.py            # every chapter + sources.json
"""
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

MIN_SENTENCE_WORDS = 9   # strictly more than 8
MIN_FRAGMENT_WORDS = 12  # ch 12's defects are 13 and 27 words
TOLERANCE = 0.005        # relative, for rounding in printed figures

# Rounding to the stated precision is legitimate; a 0.9% gap (3.27 shown as 3.3) is
# not. Half a percent admits 1.7969 -> 1.80 and 130,658.97 -> 130,659 while rejecting
# 3.27 -> 3.3.


# --- text preparation --------------------------------------------------------

def strip_markdown(text):
    """Remove fenced code, inline code, headings, and link syntax.

    Kept deliberately narrow: list markers and emphasis are stripped but the prose
    inside a list item stays, because a duplicated clause can land in a bullet too.
    """
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"^\s*#.*$", "", text, flags=re.M)
    text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return text


def normalize(s):
    """Collapse whitespace and strip markdown emphasis. Case is folded separately."""
    s = re.sub(r"[*_]{1,3}", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def split_sentences(para):
    return re.split(r"(?<=[.!?])\s+", para)


def paragraphs(text):
    """Split into paragraphs on blank lines, dropping empties."""
    out = []
    for block in re.split(r"\n\s*\n", strip_markdown(text)):
        block = normalize(block)
        if block:
            out.append(block)
    return out


# --- 1. duplicate sentences --------------------------------------------------

def duplicate_sentences(paragraphs_list):
    """Return findings for sentences (>8 words) repeated verbatim.

    Severity is scoped: a repeat inside one paragraph is a merge artifact and fails.
    A repeat across paragraphs in one chapter is reported as a warning, because a
    short rhetorical restatement ("It is a separate term you have to measure.") can
    be deliberate. Across chapters is a warning too -- the same figure may be worth
    restating -- but a verbatim long sentence is worth a human look.
    """
    findings = []
    # within a paragraph: FAIL
    for pi, para in enumerate(paragraphs_list):
        seen = {}
        for si, sent in enumerate(split_sentences(para)):
            key = sent.lower().strip(" .,;:!?")
            if len(key.split()) <= MIN_SENTENCE_WORDS - 1:
                continue
            if key in seen:
                findings.append(("FAIL", "duplicate-sentence",
                                 f"paragraph {pi + 1}, sentences {seen[key] + 1} and "
                                 f"{si + 1}", sent))
            else:
                seen[key] = si
    return findings


def duplicate_sentences_across(chapter_id, paragraphs_list, index):
    """Cross-paragraph and cross-chapter verbatim sentence repeats, as warnings."""
    findings = []
    for pi, para in enumerate(paragraphs_list):
        for sent in split_sentences(para):
            key = sent.lower().strip(" .,;:!?")
            if len(key.split()) <= MIN_SENTENCE_WORDS - 1:
                continue
            index.setdefault(key, []).append((chapter_id, pi + 1, sent))
    return findings


def report_cross_sentence(index):
    findings = []
    for key, locs in index.items():
        if len(locs) < 2:
            continue
        chapters = {c for c, _, _ in locs}
        where = ", ".join(f"{c}:para{p}" for c, p, _ in locs)
        kind = "cross-chapter" if len(chapters) > 1 else "cross-paragraph"
        findings.append(("WARN", "duplicate-sentence-" + kind, where, locs[0][2]))
    return findings


# --- 2. duplicate fragments --------------------------------------------------

def duplicate_fragments(paragraphs_list):
    """Return findings for a span of >=12 words repeated inside one paragraph.

    The merge signature is contiguous: old text followed by new text that restates
    it. Twelve words is long enough that formula fragments ("= 65536 - 32768 - 16
    - 2") and ordinary connective phrases ("the mean is 1 and the standard deviation
    is") do not trip it, while the ch 12 clause at 13 words does.
    """
    findings = []
    for pi, para in enumerate(paragraphs_list):
        words = para.split()
        best_len, best_gram, best_pos = 0, "", (0, 0)
        # Search every span length from the threshold up; record the longest repeat.
        for n in range(MIN_FRAGMENT_WORDS, len(words) + 1):
            seen = {}
            for i in range(len(words) - n + 1):
                gram = " ".join(words[i:i + n]).lower()
                if gram in seen:
                    if n > best_len:
                        best_len, best_gram = n, gram
                        best_pos = (seen[gram], i)
                else:
                    seen[gram] = i
        if best_len:
            findings.append(("FAIL", "duplicate-fragment",
                             f"paragraph {pi + 1}, {best_len} words repeated at word "
                             f"positions {best_pos[0] + 1} and {best_pos[1] + 1}",
                             best_gram))
    return findings


# --- 3. derivation self-consistency ------------------------------------------

_NUM = r"\d[\d,]*(?:\.\d+)?"


def _to_num(tok):
    return float(tok.replace(",", ""))


def evaluate_derivation(source):
    """Evaluate the arithmetic in a `derived:` source string, if it is arithmetic.

    Two shapes appear in sources.json:
      - a trailing equation: "... = 65536 - 32768 - 16 - 2" or "= 12,285,952 / 12,804,579"
      - a bare quotient:     "106.2 / 59.1"
    Returns (value, expression) or None when there is no evaluable arithmetic.
    """
    body = source[len("derived:"):].strip()
    # Prefer the right-hand side of the last "=" sign; it holds the arithmetic.
    if "=" in body:
        expr = body.rsplit("=", 1)[1].strip()
    else:
        expr = body
    # A pure arithmetic expression: numbers joined by + - * / and parentheses.
    if not re.fullmatch(r"[\d,.\s+\-*/()]+", expr):
        return None
    if not re.search(r"[+\-*/]", expr):
        return None
    # Thousands separators are punctuation, not tuple syntax: strip them before
    # evaluating, or "12,285,952 / 12,804,579" becomes a 2-tuple.
    clean = expr.replace(",", "")
    try:
        # Standard library only: guard the eval surface to digits and operators.
        val = eval(clean, {"__builtins__": {}}, {})  # noqa: S307 -- input is regex-filtered
    except Exception:
        return None
    return float(val), expr


def check_sources(sources_path):
    """Return findings where a derived source's arithmetic disagrees with its value."""
    findings = []
    data = json.load(open(sources_path, encoding="utf-8"))
    for entry in data["verified"]:
        src = str(entry.get("source", ""))
        if not src.startswith("derived:"):
            continue
        got = evaluate_derivation(src)
        if got is None:
            continue
        computed, expr = got
        stated = float(entry["value"])
        # A ratio is sometimes stored as a percentage: 0.9595 vs 95.9. Accept the
        # value if it matches either the raw quotient or the quotient times 100.
        candidates = (computed, computed * 100.0)
        if not any(abs(c - stated) <= max(abs(stated) * TOLERANCE, 1e-9)
                   for c in candidates):
            findings.append(("FAIL", "derivation-mismatch",
                             f"{entry.get('id')}: {expr}",
                             f"evaluates to {computed:g}, value is {stated:g}"))
    return findings


# --- 4. unit/label consistency for L^2 expressions ---------------------------

# "130,659 × 130,659 × 128 × 2 = 4.37 TB": two L factors, one extra factor, times two
# bytes. That is L^2 * d * 2 -- d heads -- not one head.
SCORE_EXPR = re.compile(
    r"(?P<a>" + _NUM + r")\s*(?:×|x|\*)\s*(?P<b>" + _NUM + r")\s*(?:×|x|\*)\s*"
    r"(?P<d>" + _NUM + r")\s*(?:×|x|\*)\s*2\s*=\s*(?P<c>" + _NUM + r")\s*"
    r"(?P<unit>TB|GB|MB|bytes?|B)")

# Same expression without the extra factor: L x L x 2 = C.
PLAIN_EXPR = re.compile(
    r"(?P<a>" + _NUM + r")\s*(?:×|x|\*)\s*(?P<b>" + _NUM + r")\s*(?:×|x|\*)\s*"
    r"2\s*=\s*(?P<c>" + _NUM + r")\s*(?P<unit>TB|GB|MB|bytes?|B)")

SCALE = {"TB": 1e12, "GB": 1e9, "MB": 1e6, "B": 1.0, "bytes": 1.0, "byte": 1.0}

ONE_HEAD = re.compile(r"\b(?:one|single|a single|per)\s+head\b|\bone head of one layer\b",
                      re.I)
ALL_HEADS = re.compile(r"\ball\b[^.]{0,40}\bheads\b|\b\d+\s+heads\b|\bevery head\b",
                       re.I)


def _window(text, start, end, radius=160):
    """Prose around an expression, which is where its label lives."""
    return text[max(0, start - radius):min(len(text), end + radius)]


def check_units(text):
    """Return findings where an L^2-style byte count is mislabelled by scope.

    The rule is scoped to bytes (unit present) and to scope words. If the expression
    carries an extra factor (d heads' worth of entries) and the surrounding prose says
    "one head" / "single head", the label contradicts the arithmetic.
    """
    findings = []
    for m in SCORE_EXPR.finditer(text):
        a, b, d = (_to_num(m.group(g)) for g in ("a", "b", "d"))
        c = _to_num(m.group("c")) * SCALE[m.group("unit")]
        expected_one = a * b * 2            # one head
        expected_all = a * b * d * 2        # d heads
        ctx = _window(text, m.start(), m.end())
        says_one = ONE_HEAD.search(ctx) is not None and ALL_HEADS.search(ctx) is None
        if says_one:
            findings.append((
                "FAIL", "unit-label",
                f"{m.group(0).strip()}",
                f"computes {expected_all:.3g} bytes = {d:g} heads, but the prose "
                f"calls it one head ({expected_one:.3g} bytes)"))
    for m in PLAIN_EXPR.finditer(text):
        a, b = _to_num(m.group("a")), _to_num(m.group("b"))
        ctx = _window(text, m.start(), m.end())
        if ALL_HEADS.search(ctx) and ONE_HEAD.search(ctx) is None:
            findings.append((
                "FAIL", "unit-label",
                f"{m.group(0).strip()}",
                "computes L^2 x 2 bytes (one head) but the prose calls it all heads"))
    return findings


# --- report ------------------------------------------------------------------

def check_chapter(path):
    text = open(path, encoding="utf-8").read()
    paras = paragraphs(text)
    findings = []
    findings += duplicate_sentences(paras)
    findings += duplicate_fragments(paras)
    findings += check_units(text)
    return findings, paras


def main(argv):
    if len(argv) > 1:
        chapters = argv[1:]
        sources_path = os.path.join(ROOT, "content", "sources.json")
    else:
        chapters = sorted(glob.glob(os.path.join(ROOT, "content", "chapters", "*.md")))
        sources_path = os.path.join(ROOT, "content", "sources.json")

    sentence_index = {}
    total_fail = 0
    total_warn = 0

    for path in chapters:
        cid = os.path.basename(path)[:-3]
        findings, paras = check_chapter(path)
        duplicate_sentences_across(cid, paras, sentence_index)
        if findings:
            print(f"\n{cid}.md")
            for level, kind, where, detail in findings:
                print(f"  {level} {kind}: {where}")
                print(f"    {detail[:160]}")
                if level == "FAIL":
                    total_fail += 1
                else:
                    total_warn += 1

    cross = report_cross_sentence(sentence_index)
    if cross:
        print("\nrepeated sentences across paragraphs or chapters:")
        for level, kind, where, detail in cross:
            print(f"  {level} {kind}: {where}")
            print(f"    {detail[:160]}")
            total_warn += 1

    if os.path.exists(sources_path):
        der = check_sources(sources_path)
        if der:
            print("\ncontent/sources.json")
            for level, kind, where, detail in der:
                print(f"  {level} {kind}: {where}")
                print(f"    {detail}")
                total_fail += 1

    print(f"\nfindings: {total_fail} failing, {total_warn} warning")
    print("CONSISTENCY: " + ("FAIL" if total_fail else "PASS"))
    print("GATE: " + ("FAIL" if total_fail else "PASS"))
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
