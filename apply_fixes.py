#!/usr/bin/env python3
"""Apply confirmed review fixes to the chapter prose.

Usage:
    python3 apply_fixes.py <chapter>            # dry run: show what would change
    python3 apply_fixes.py <chapter> --write    # apply and save
    python3 apply_fixes.py --all --write        # every chapter with confirmed fixes

The verifier returns fixes as "Replace <quote> with <replacement>". This parses that
shape, finds the quote in the chapter, and swaps it. A fix whose quote does not appear
verbatim is reported and skipped rather than guessed at: a wrong edit to a technical
book is worse than a missing one.

Where both reviewers confirm the same clause, only the first fix is applied. The two
reviewers overlap by design and often land on the same sentence.
"""
import os
import re
import sys

import review
import apply_review

HERE = os.path.dirname(os.path.abspath(__file__))
CHAPTERS = os.path.join(HERE, "content", "chapters")


def parse_fix(fix):
    """Return (quote, replacement) from a verifier fix, or (None, None).

    Handles the phrasings the verifier actually produces:
        Replace "X" with "Y".
        Replace "X" with: "Y".
        Replace "X" with something like: "Y".
    """
    if not fix:
        return None, None
    m = re.search(
        r"Replace\s+[\u201c\"'](.+?)[\u201d\"']\s+with(?:\s+something\s+like)?:?\s*[\u201c\"'](.+?)[\u201d\"']",
        fix, re.S,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # "Change "X" to "Y""
    m = re.search(
        r"Change\s+[\u201c\"'](.+?)[\u201d\"']\s+to\s+[\u201c\"'](.+?)[\u201d\"']",
        fix, re.S,
    )
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # "Revise to: "Y"" with the offending clause named earlier in the fix.
    m = re.search(r"Revise\s+to:?\s*[\u201c\"'](.+?)[\u201d\"']", fix, re.S)
    if m:
        quoted = re.findall(r"[\u201c\"'](.+?)[\u201d\"']", fix, re.S)
        if len(quoted) >= 2:
            return quoted[0].strip(), m.group(1).strip()
    return None, None


def normalise_quotes(text):
    return text.replace("\u201c", '"').replace("\u201d", '"').replace("\u2019", "'")


def clean_repl(quote, repl):
    """Drop duplicated terminal punctuation the replacement inherits from the quote.

    The verifier writes full sentences ending in a period, but the quote it replaces is a
    mid-sentence clause that already has one in the chapter. Swapping them naively gives
    ".." or ",.".
    """
    r = repl.rstrip()
    q = quote.rstrip()
    if r and q:
        if q[-1] in ".;,!?" and r[-1] == q[-1]:
            r = r[:-1]
        elif q[-1] in ".;,!?" and r[-1] in ".;,!?":
            r = r[:-1] + q[-1]
    return r


def repair_punctuation(text):
    """Collapse the doubled punctuation a swap can leave behind.

    A replacement ending in a period, dropped into a sentence that already had one, reads
    as "..". Only a period doubled immediately before a capital or at end of sentence is
    touched: the chapters legitimately contain ".." in ranges, series, and a CLI path, and
    an earlier blanket replace damaged them.
    """
    text = re.sub(r"\.\.(?=\s+[A-Z\"“]|\s*$)", ".", text)
    text = text.replace(".,", ",").replace(",.", ".")
    return text


def apply_chapter(cid, write=False):
    path = os.path.join(CHAPTERS, cid + ".md")
    if not os.path.exists(path):
        print(f"{cid}: no chapter file")
        return 0
    text = open(path, encoding="utf-8").read()
    orig = text

    rows = []
    for reviewer in ("ml", "ops"):
        rows += apply_review.load_verdicts(cid, reviewer)
    confirmed = [r for r in rows if r.get("verdict") == "confirmed"]

    applied, skipped, seen = 0, [], set()
    for r in confirmed:
        quote, repl = parse_fix(r.get("fix", ""))
        if not quote:
            skipped.append(("no-quote", r.get("fix", "")[:100]))
            continue
        key = normalise_quotes(quote)
        if key in seen:
            skipped.append(("dup", quote[:80]))
            continue
        # The chapter uses LaTeX and curly quotes; match on the literal text first.
        if quote in text:
            text = text.replace(quote, clean_repl(quote, repl), 1)
            seen.add(key)
            applied += 1
            continue
        # Try a quote-insensitive match, which catches curly-vs-straight differences.
        pat = re.escape(normalise_quotes(quote))
        flat = normalise_quotes(text)
        m = re.search(pat, flat)
        if m:
            # Map the match back onto the original by offset (same length, quotes are 1:1)
            text = text[:m.start()] + clean_repl(quote, repl) + text[m.end():]
            seen.add(key)
            applied += 1
            continue
        skipped.append(("not-found", quote[:100]))

    print(f"{cid}: {len(confirmed)} confirmed, {applied} applied, {len(skipped)} skipped")
    for why, s in skipped:
        print(f"   [{why}] {s}")

    text = repair_punctuation(text)
    if write and text != orig:
        open(path, "w", encoding="utf-8").write(text)
        print(f"   wrote {path}")
    return applied


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    write = "--write" in sys.argv
    if "--all" in sys.argv:
        ids = review.published_ids()
    elif args:
        ids = args
    else:
        print(__doc__)
        return 1
    total = 0
    for cid in ids:
        if not apply_review.load_verdicts(cid, "ml") and not apply_review.load_verdicts(cid, "ops"):
            continue
        total += apply_chapter(cid, write)
    print(f"total applied: {total}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
