#!/usr/bin/env python3
"""Fact gate for an explanatory book.

Two different jobs, deliberately separated:

1. TEXTBOOK CONSTANTS. Dimensions, published model sizes, and hardware figures that
   appear in primary sources. These are allowed because the chapter is supposed to cite
   them. They are listed in skills/textbook.json with their provenance.

2. LOCAL MEASUREMENTS. Anything that looks like a reading off this specific machine must
   trace to content/sources.json, which was captured from the live engine. This is the
   part that catches a hallucinated "59.1 tok/s".

The split matters. A book about language models has to mention 4096 dimensions and 128k
vocabularies; a rig notebook has to mention 111.5 GB. Confusing the two is what makes a
fact checker useless in one direction or the other.

Also enforces a minimum length so a revision cannot shrink a chapter into a stub.
"""
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# Integers that are structural rather than measured: list indices, powers of two used as
# sizes, small counts, and the years and section numbers that appear in prose.
STRUCTURAL = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 16, 24, 32, 48, 64, 96, 128,
              256, 512, 1024, 2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144,
              20, 40, 60, 80, 100, 200, 400, 500, 600, 800, 1000}

MIN_WORDS = 1100


def load_allowed(sources_path):
    """Values from the measured-facts file, by numeric value."""
    d = json.load(open(sources_path, encoding="utf-8"))
    vals = []
    for v in d["verified"]:
        vals.append(float(v["value"]))
        for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", v["display"]):
            vals.append(float(m.group(0).replace(",", "")))
    return vals


def load_textbook():
    p = os.path.join(HERE, "textbook.json")
    if not os.path.exists(p):
        return []
    d = json.load(open(p, encoding="utf-8"))
    vals = []
    for v in d["constants"]:
        vals.append(float(v["value"]))
        for m in re.finditer(r"\d[\d,]*(?:\.\d+)?", v["display"]):
            vals.append(float(m.group(0).replace(",", "")))
    return vals


# Units that turn a bare number into a measurement claim. If one of these follows a
# number, that number must have provenance.
# A unit must end at a word boundary, or the short entries match ordinary prose:
# "101 which" matched "w" (watts) and "5 was" matched "w", turning every number
# before a w/s/m word into a fake measurement claim. The trailing \b is what stops
# that; the alternation is longest-first so "million" wins over "m" and "MiB"
# over "Mi".
# A unit must end at a word boundary, or the short entries match ordinary prose:
# "101 which" matched "w" (watts) and turned every number before a w/s/m word
# into a fake measurement claim. "%" is punctuation so it needs no boundary.
UNITS = r"""(?:GB/s|TB/s|GiB/s|tok/s|tokens?/s|GB|GiB|MB|MiB|KB|TB|TFLOPS|FLOPs|
              MHz|GHz|tok|tokens|positions|bytes?|bits?|dimensions?|heads?|layers?|
              parameters?|billion|million|percent|ms|seconds?|minutes?|hours?|
              watts?|nats|x|s|W|%)(?![a-z])"""


def numbers_in(text):
    """Return (raw, value, is_measurement) triples.

    A number is a measurement claim when it carries a thousands separator, a decimal
    point, or is immediately followed by a unit. Bare integers are treated as
    illustrative -- token ids, ranges, counts of things in a worked example -- and are
    allowed without provenance. This is the distinction that lets a book cite "token
    4021" and "30 or 40" while still catching a fabricated "111.5 GB".
    """
    stripped = re.sub(r"```.*?```", "", text, flags=re.S)
    stripped = re.sub(r"`[^`]*`", "", stripped)
    out = []
    # The lookbehind must exclude a comma as well as a slash: in "786,432/1,048,576"
    # a slash-only guard lets the scan resume mid-number at "1," and capture
    # "048,576", which then looks like an unsourced measurement.
    for m in re.finditer(r"(?<![\w/,])(\d[\d,]*(?:\.\d+)?)", stripped):
        raw = m.group(0).rstrip(",").rstrip(".")
        try:
            val = float(raw.replace(",", ""))
        except ValueError:
            continue
        after = stripped[m.end():m.end() + 24].lstrip()
        unit_after = re.match(UNITS, after, re.I) is not None
        # thousands separator means the author formatted it as a quantity
        # A comma only means "quantity" if it is a real thousands separator, i.e.
        # followed by exactly three digits. "30,40" is a range, not thirty thousand.
        comma = re.fullmatch(r"\d{1,3}(?:,\d{3})+", raw) is not None
        # A bare decimal with no unit is worked-example arithmetic -- a cosine
        # similarity, a probability, a ratio. The reader can check it from the
        # numbers printed beside it. Only a unit makes it a measurement claim.
        decimal = "." in raw and unit_after
        is_measurement = comma or decimal or unit_after
        out.append((raw, val, is_measurement))
    return out


def matches(val, allowed):
    for a in allowed:
        if a == val:
            return True
        # tolerate rounding: 111.52 vs 111.5, 39,237 vs 39200
        if abs(a - val) <= max(0.5, abs(a) * 0.006):
            return True
    return False


def exact_or_structural(val, allowed):
    """Stricter operand test for derivation inputs.

    matches() tolerates 0.6% rounding, which is right for "39,237 vs 39,200" but
    lets 999 pass as 1,000. As an OPERAND in a derivation that slack compounds:
    "999 times 999 is 55,555" would be accepted because 999 matches 1,000. Operands
    must be exact, or structural, or within the rounding tolerance of a value the
    chapter is explicitly allowed to cite.
    """
    if val in STRUCTURAL:
        return True
    # n and n+1 appear together constantly ("65,536 times 65,537 divided by 2" is
    # n(n+1)/2). Accept a structural value's immediate neighbours; 65,537 is exactly
    # as structural as 65,536 and is not an invented measurement.
    for s in STRUCTURAL:
        if s >= 1024 and abs(val - s) == 1:
            return True
    for a in allowed:
        if a == val:
            return True
        # Tolerate rounding in the ALLOWED value only, which is what the tolerance
        # exists for ("39,237" vs "39,200"). Small integers must match exactly so
        # that 999 is not accepted as 1,000.
        if abs(a) >= 1000 and abs(a - val) <= abs(a) * 0.006:
            return True
        if abs(a) < 1000 and abs(a) > 0 and abs(a - val) <= abs(a) * 0.006:
            return True
    return False


def derived_numbers(text, allowed):
    """Numbers the chapter computes and shows its work for.

    A sentence like "786,432 x 921.6 bytes = 724.8 MB" needs no external
    provenance for 724.8: the reader can check it from the two inputs printed
    beside it, and those inputs are themselves sourced. Without this the gate
    rejects every chapter that does in-line arithmetic, which is most of a book
    about cost and memory.

    The rule is strict: a result counts as derived only when every number in the
    expression that produces it is already allowed. Chains are resolved by
    iterating, so 724.8 -> 0.675 works once 724.8 is established.
    """
    derived = set()
    # Run every form to a fixed point. Forms are not order-independent -- 16,777,216
    # (d squared) must be established before "32 x 4 x 16,777,216 = 2,147,483,648"
    # can resolve -- so repeat the whole set until nothing new appears.
    for _pass in range(6):
        before = len(derived)
        # Form 1: an explicit equation, "786,432 x 921.6 = 724.8 MB".
        # Left side of an equation is the clause since the last sentence break.
        for _ in range(4):
            pool = allowed + list(derived)
            grew = False
            for m in re.finditer(r"=\s*(\d[\d,]*(?:\.\d+)?)", text):
                try:
                    result = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                if result in derived:
                    continue
                left = text[max(0, m.start() - 160):m.start()]
                left = re.split(r"[.;!?]\s", left)[-1]
                inputs = [v for _, v, _ in numbers_in(left)]
                # The same figure often appears twice in a clause ("130,659 tokens, the
                # KV traffic per rank is 130,659 x 922"). Collapse duplicates so the
                # arithmetic is two operands, not three.
                inputs = list(dict.fromkeys(inputs))
                if len(inputs) < 2:
                    continue
                if not all(exact_or_structural(v, pool) or 1990 <= v <= 2030
                           for v in inputs):
                    continue
                # The equation must actually balance. Accepting any result whose
                # clause merely contains two allowed numbers let "32 × 4 × 16,777,216
                # = 999,999,999" through.
                tol = max(0.5, abs(result) * 0.006)
                # A result stated in a larger unit is the raw arithmetic divided by that
                # unit's scale: "130,659 × 922 = 120.5 MB" is bytes / 1e6. Try the scale
                # that matches the unit printed after the result.
                after = text[m.end():m.end() + 12]
                scales = [1.0]
                if re.match(r"\s*(?:MB|MiB)\b", after):
                    scales.append(1e6)
                elif re.match(r"\s*(?:GB|GiB)\b", after):
                    scales.append(1e9)
                elif re.match(r"\s*(?:KB)\b", after):
                    scales.append(1e3)
                elif re.match(r"\s*(?:TB)\b", after):
                    scales.append(1e12)
                # A ratio stated as a percentage: "3/64 = 4.7 percent" is 0.046875 x 100.
                if re.match(r"\s*(?:percent|%)\b", after):
                    scales.append(0.01)
                ok = False
                for scale in scales:
                    target = result * scale
                    stol = max(0.5, abs(target) * 0.006)
                    if re.search(r"[×x\*]", left):
                        ok = abs(math.prod(inputs) - target) <= stol
                    if not ok and len(inputs) == 2:
                        a, b = inputs
                        ok = (abs(a * b - target) <= stol
                              or (b and abs(a / b - target) <= stol)
                              or (a and abs(b / a - target) <= stol)
                              or abs(a + b - target) <= stol
                              or abs(abs(a - b) - target) <= stol)
                    if not ok and len(inputs) == 3:
                        a, b, c = inputs
                        ok = (abs(a * b - target) <= stol
                              or abs(a + b + c - target) <= stol
                              or (abs(a * b / c - target) <= stol if c else False))
                    if ok:
                        break
                if ok:
                    derived.add(result)
                    grew = True
            if not grew:
                break

        # Form 2: multiplication stated in words or with a bare x, no equals sign.
        # "50,257 entries at the same width" -> the product of the numbers in the
        # clause. Only accepted when every factor is already allowed.
        for m in re.finditer(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:x|×|\*)\s*(\d[\d,]*(?:\.\d+)?)"
                             r"(?:\s*(?:x|×|\*)\s*(\d[\d,]*(?:\.\d+)?))?", text):
            factors = [float(g.replace(",", "")) for g in m.groups() if g]
            pool = allowed + list(derived)
            if len(factors) >= 2 and all(
                    exact_or_structural(f, pool) for f in factors):
                derived.add(float(round(math.prod(factors), 6)))

        # Form 3: "A and B are P" where P = A * B, stated without symbols.
        # Covers "50,257 entries at 4,096" and "0.68 GiB / 786,432 positions".
        # P is only accepted when it equals the arithmetic of a and b. The old code also
        # accepted P whenever any candidate (including a/b and b/a) matched an allowed
        # value, which let invented totals through.
        for m in re.finditer(r"\b(\d[\d,]*(?:\.\d+)?)\b[^.;]{0,80}?\b"
                             r"(\d[\d,]*(?:\.\d+)?)\b[^.;]{0,40}?\b"
                             r"(\d[\d,]*(?:\.\d+)?)\b", text):
            a, b, p = (float(g.replace(",", "")) for g in m.groups())
            pool = allowed + list(derived)
            if a == 0 or b == 0:
                continue
            if not exact_or_structural(a, pool):
                continue
            if not exact_or_structural(b, pool):
                continue
            tol = max(0.5, abs(p) * 0.006)
            if abs(a * b - p) <= tol or abs(a / b - p) <= tol or abs(b / a - p) <= tol:
                derived.add(p)
        # Form 4: arithmetic written in words, "130,659 times 130,660 divided by 2, or
        # 8,535,952,470 pairs". Chapters describing attention cost write their derivations
        # this way, and Forms 1-3 only parse symbols, so correct arithmetic was being
        # rejected. Accept the stated result when it equals the evaluation of the
        # word-operator expression immediately before it, with every operand allowed.
        WORDS = r"(?:times|multiplied by|divided by|x|×|\*|plus|minus|and|over)"
        # The result may be introduced by "=" or by prose ("... divided by 2, or 8,535,952,470
        # pairs", "... which is 535,179,264 pairs"). Match both.
        RESULT_INTRO = r"(?:=|,?\s*(?:or|which is|is|equals|giving|comes to|yields))\s*"
        # Chains: "Across four streams, that is 8,590,065,664" reuses the previous sentence's
        # result times a word-number. Iterate so a figure derived in one sentence can feed the
        # next, the same way Forms 1-3 resolve chains.
        WORD_NUM = {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8,
                    "sixteen": 16, "thirty-two": 32, "half": 0.5, "double": 2, "twice": 2}
        for _ in range(4):
            grew = False
            for m in re.finditer(RESULT_INTRO + r"(\d[\d,]*(?:\.\d+)?)", text):
                try:
                    result = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                if any(matches(result, [d]) for d in derived):
                    continue
                pool = allowed + list(derived)
                left = text[max(0, m.start() - 220):m.start()]
                left = re.split(r"[.;!?]\s", left)[-1]
                nums = [v for _, v, _ in numbers_in(left)]
                # Drop the result itself if the clause repeats it before the intro word.
                nums = [v for v in nums if not matches(v, [result])]
                tol = max(0.5, abs(result) * 0.006)

                # Explicit word-operator expression.
                if len(nums) >= 2 and re.search(WORDS, left):
                    if all(exact_or_structural(v, pool) for v in nums):
                        if any(abs(result - c) <= tol
                               for c in word_expr_candidates(left, nums)):
                            derived.add(result)
                            grew = True
                            continue

                # Word-number multiplier on a single operand: "across four streams, that is X"
                # or "twice 2,147,516,416".
                mult = None
                for w, val in WORD_NUM.items():
                    if re.search(r"\b" + w + r"\b", left):
                        mult = val
                        break
                if mult is not None:
                    for base in nums:
                        if not exact_or_structural(base, pool):
                            continue
                        if abs(base * mult - result) <= tol:
                            derived.add(result)
                            grew = True
                            break
                    if any(matches(result, [d]) for d in derived):
                        continue

                # A bare "that is X" or "across four streams, that is X" refers to the
                # immediately preceding sentence. If a word-number multiplies that
                # sentence's derived figure, accept X.
                if not nums:
                    prev = text[max(0, m.start() - 400):m.start()]
                    prev = re.split(r"[.;!?]\s", prev)[-2:] if len(
                        re.split(r"[.;!?]\s", prev)) >= 2 else []
                    prev_nums = []
                    for seg in prev:
                        prev_nums += [v for _, v, _ in numbers_in(seg)]
                    mult = None
                    for w, val in WORD_NUM.items():
                        if re.search(r"\b" + w + r"\b", left):
                            mult = val
                            break
                    if mult is not None:
                        for base in prev_nums:
                            if exact_or_structural(base, pool):
                                if abs(base * mult - result) <= tol:
                                    derived.add(result)
                                    grew = True
                                    break
                        if any(matches(result, [d]) for d in derived):
                            continue

                # A bare "that is X" following a sentence whose only number is allowed and
                # which states a multiplier in words is covered above. Also accept a
                # single-operand restatement ("the total is 2,156,080").
                if len(nums) == 1 and exact_or_structural(nums[0], pool):
                    if abs(nums[0] - result) <= tol:
                        derived.add(result)
                        grew = True
            if not grew:
                break

        # Form 6: sums of already-established values. "The 16 full layers cost 16 times
        # 130,659, or 2,090,544 ... The 16 local layers cost 16 times 4,096, or 65,536.
        # The total is 2,156,080." The total is the sum of two figures derived in the two
        # preceding sentences, so look back two sentences for operands.
        for _ in range(3):
            grew = False
            for m in re.finditer(r"\btotal is\s*(\d[\d,]*(?:\.\d+)?)", text):
                try:
                    result = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                if any(matches(result, [d]) for d in derived):
                    continue
                pool = allowed + list(derived)
                back = text[max(0, m.start() - 400):m.start()]
                prior = [v for _, v, _ in numbers_in(back)
                         if exact_or_structural(v, pool)]
                tol = max(0.5, abs(result) * 0.006)
                hit = False
                for a in prior:
                    for b in prior:
                        if matches(a, [b]):
                            continue
                        if abs(a + b - result) <= tol:
                            hit = True
                            break
                    if hit:
                        break
                if hit:
                    derived.add(result)
                    grew = True
            if not grew:
                break

        # Form 7: "A divided by B, or P percent" where A and B are already established
        # (possibly derived earlier in this pass).
        for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s+divided by\s+(\d[\d,]*(?:\.\d+)?)"
                             r"[^.;]{0,40}?(\d[\d,]*(?:\.\d+)?)\s*percent", text):
            a, b, pct = (float(g.replace(",", "")) for g in m.groups())
            pool = allowed + list(derived)
            if b == 0:
                continue
            if not exact_or_structural(a, pool):
                continue
            if not exact_or_structural(b, pool):
                continue
            if abs(a / b * 100 - pct) <= max(0.5, abs(pct) * 0.006):
                derived.add(pct)

        # Form 8: "That is about 0.012 percent of the causal full count." The percentage's
        # two operands live in the two preceding sentences: the derived figure being
        # compared, and the derived figure it is compared against.
        for _ in range(3):
            grew = False
            for m in re.finditer(r"about\s*(\d[\d,]*(?:\.\d+)?)\s*percent", text):
                try:
                    pct = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                if any(matches(pct, [d]) for d in derived):
                    continue
                pool = allowed + list(derived)
                back = text[max(0, m.start() - 450):m.start()]
                prior = [v for _, v, _ in numbers_in(back) if matches(v, pool)]
                for a in prior:
                    for b in prior:
                        if matches(a, [b]) or b == 0:
                            continue
                        if abs(a / b * 100 - pct) <= max(0.5, abs(pct) * 0.006):
                            derived.add(pct)
                            grew = True
                            break
                    if any(matches(pct, [d]) for d in derived):
                        break
            if not grew:
                break

        # Form 9: a derived byte count stated in a larger unit. "130,659 x 928 bytes, or
        # about 121 MB": the arithmetic yields 121,251,552 BYTES and the prose states it
        # as 121 MB. Without this every byte computation reads as unsourced.
        for _ in range(3):
            grew = False
            for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(?:×|x|\*)\s*(\d[\d,]*(?:\.\d+)?)"
                                 r"\s*bytes?[^.;]{0,60}?\b(?:or|about|is|gives)\s*"
                                 r"(\d[\d,]*(?:\.\d+)?)\s*(KB|MB|GB|TB|KiB|MiB|GiB|TiB)", text):
                a = float(m.group(1).replace(",", ""))
                b = float(m.group(2).replace(",", ""))
                stated = float(m.group(3).replace(",", ""))
                unit = m.group(4).upper()
                pool = allowed + list(derived)
                if not (exact_or_structural(a, pool) and exact_or_structural(b, pool)):
                    continue
                total = a * b
                scale = {"KB": 1e3, "MB": 1e6, "GB": 1e9, "TB": 1e12,
                         "KIB": 2**10, "MIB": 2**20, "GIB": 2**30, "TIB": 2**40}[unit]
                if abs(total / scale - stated) <= max(0.5, abs(stated) * 0.02):
                    derived.add(stated)
                    derived.add(total)
                    grew = True
            if not grew:
                break

        # Form 10: subtraction stated in prose. "The mean is 3.46 seconds against a mean
        # prefill of 3.33, which leaves 0.13 seconds for admission."
        for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)[^.;]{0,40}?against\s+(?:a\s+)?"
                             r"[^.;]{0,60}?(\d[\d,]*(?:\.\d+)?)[^.;]{0,40}?\bleaves\s+"
                             r"(?:about\s+)?(\d[\d,]*(?:\.\d+)?)", text):
            a, b, diff = (float(g.replace(",", "")) for g in m.groups())
            pool = allowed + list(derived)
            if not (exact_or_structural(a, pool) and exact_or_structural(b, pool)):
                continue
            if abs(abs(a - b) - diff) <= max(0.05, abs(diff) * 0.02):
                derived.add(diff)

        # Form 11d: "8d² = 134,217,728": a coefficient times a square whose value was
        # established by Form 12. Try every derived square rather than hardcoding d.
        for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(?:×|x|\*)?\s*d²\s*=\s*"
                             r"(\d[\d,]*(?:\.\d+)?)", text):
            coef = float(m.group(1).replace(",", ""))
            res = float(m.group(2).replace(",", ""))
            pool = allowed + list(derived)
            if not (exact_or_structural(coef, pool) or coef in STRUCTURAL):
                continue
            tol = max(0.5, abs(res) * 0.006)
            for sq in list(derived):
                if abs(coef * sq - res) <= tol:
                    derived.add(res)
                    break

        # Form 11b: "32 × 4 × 16,777,216 = 2,147,483,648": an explicit product of three
        # terms with its stated result.
        for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*(?:×|x|\*)\s*(\d[\d,]*(?:\.\d+)?)"
                             r"\s*(?:×|x|\*)\s*(\d[\d,]*(?:\.\d+)?)\s*=\s*"
                             r"(\d[\d,]*(?:\.\d+)?)", text):
            f1, f2, f3, res = (float(g.replace(",", "")) for g in m.groups())
            pool = allowed + list(derived)
            if not all(exact_or_structural(f, pool) or f in STRUCTURAL
                       for f in (f1, f2, f3)):
                continue
            if abs(f1 * f2 * f3 - res) <= max(0.5, abs(res) * 0.006):
                derived.add(res)

        # Form 11c: "2 × 128,000 × 4096 = 1,048,576,000".
        # Covered by 11b; kept separate so a missing '=' still resolves via Form 11.

        # Form 11: powers of two written out as dimensions. d=4096 gives d²=16,777,216, and
        # the FFN parameter count is a product of such terms.
        for m in re.finditer(r"\b(\d[\d,]*(?:\.\d+)?)\s*(?:×|x|\*)\s*(\d[\d,]*(?:\.\d+)?)"
                             r"\s*(?:×|x|\*)\s*(\d[\d,]*(?:\.\d+)?)", text):
            factors = [float(g.replace(",", "")) for g in m.groups()]
            pool = allowed + list(derived)
            if not all(exact_or_structural(f, pool) or f in STRUCTURAL
                       for f in factors):
                continue
            derived.add(round(math.prod(factors), 6))

        # Form 12: a dimension squared. "d = 4096" then "d² = 16,777,216" or a later
        # "16,777,216" used as d-squared. Squares of allowed dimensions are structural.
        for a in allowed:
            if a < 2:
                continue
            sq = a * a
            # int() truncated a fractional square to a bare digit (2.5^2 -> "6"), which
            # then matched the 6 in "812.6" and let a fabricated figure through. Match the
            # square as written instead: integer squares without a decimal point, others
            # with their actual digits.
            token = str(int(sq)) if sq == int(sq) else repr(round(sq, 6))
            if re.search(r"\b" + re.escape(token) + r"\b", text.replace(",", "")):
                derived.add(sq)

        # Form 13: a percentage of a derived total. "a feed-forward share of 57.3 percent"
        # where the share is one previously-derived term over a previously-derived total.
        for _ in range(3):
            grew = False
            for m in re.finditer(r"share of\s*(\d[\d,]*(?:\.\d+)?)\s*percent", text):
                try:
                    pct = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                pool = allowed + list(derived)
                back = text[max(0, m.start() - 350):m.start()]
                prior = [v for _, v, _ in numbers_in(back) if matches(v, pool)]
                for a in prior:
                    for b in prior:
                        if matches(a, [b]) or b == 0:
                            continue
                        if abs(a / b * 100 - pct) <= max(0.5, abs(pct) * 0.03):
                            derived.add(pct)
                            grew = True
                            break
                    if any(matches(pct, [d]) for d in derived):
                        break
            if not grew:
                break

        # Form 14: a stated total that sums previously derived terms. "... for a total of
        # 7,491,026,944" and "the total drops to 6,966,738,944".
        for _ in range(4):
            grew = False
            for m in re.finditer(r"\btotal (?:of|drops to|is|comes to)\s*"
                                 r"(\d[\d,]*(?:\.\d+)?)", text):
                try:
                    total = float(m.group(1).replace(",", ""))
                except ValueError:
                    continue
                if any(matches(total, [d]) for d in derived):
                    continue
                pool = allowed + list(derived)
                back = text[max(0, m.start() - 400):m.start()]
                prior = [v for _, v, _ in numbers_in(back) if matches(v, pool)]
                tol = max(0.5, abs(total) * 0.006)
                for i, a in enumerate(prior):
                    for b in prior[i + 1:]:
                        for c in [0.0] + prior[i + 1:]:
                            if abs(a + b + c - total) <= tol:
                                derived.add(total)
                                grew = True
                                break
                        if any(matches(total, [d]) for d in derived):
                            break
                    if any(matches(total, [d]) for d in derived):
                        break
            if not grew:
                break

        # Form 15: "the total drops to X" where X is the previous total minus one
        # previously derived term (tied embeddings remove one embedding matrix).
        for m in re.finditer(r"\bdrops to\s*(\d[\d,]*(?:\.\d+)?)", text):
            try:
                target = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if any(matches(target, [d]) for d in derived):
                continue
            pool = allowed + list(derived)
            back = text[max(0, m.start() - 400):m.start()]
            prior = [v for _, v, _ in numbers_in(back) if matches(v, pool)]
            tol = max(0.5, abs(target) * 0.006)
            for a in prior:
                for b in prior:
                    if matches(a, [b]):
                        continue
                    if abs(a - b - target) <= tol:
                        derived.add(target)
                        break
                if any(matches(target, [d]) for d in derived):
                    break

        # Form 16: "lifting the share to 61.7 percent" -- same as Form 13 but with
        # "lifting"/"raising" instead of "share of".
        for m in re.finditer(r"(?:share|lifting the share|raising the share)\s*(?:to|of)\s*"
                             r"(\d[\d,]*(?:\.\d+)?)\s*percent", text):
            try:
                pct = float(m.group(1).replace(",", ""))
            except ValueError:
                continue
            if any(matches(pct, [d]) for d in derived):
                continue
            pool = allowed + list(derived)
            back = text[max(0, m.start() - 400):m.start()]
            prior = [v for _, v, _ in numbers_in(back) if matches(v, pool)]
            for a in prior:
                for b in prior:
                    if matches(a, [b]) or b == 0:
                        continue
                    if abs(a / b * 100 - pct) <= max(0.5, abs(pct) * 0.03):
                        derived.add(pct)
                        break
                if any(matches(pct, [d]) for d in derived):
                    break

        # Form 17: a bandwidth computed from bytes-per-clock times a clock rate.
        # "128 bytes × 2,197 MHz = 281 GB/s": 128 B/clk x 2197e6 clk/s = 281e9 B/s.
        for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s*bytes?\s*(?:×|x|\*)\s*"
                             r"(\d[\d,]*(?:\.\d+)?)\s*(MHz|GHz)\s*=\s*"
                             r"(\d[\d,]*(?:\.\d+)?)\s*(GB/s|TB/s|MB/s)", text):
            per_clk = float(m.group(1).replace(",", ""))
            clock = float(m.group(2).replace(",", ""))
            stated = float(m.group(4).replace(",", ""))
            clk_unit = m.group(3).upper()
            out_unit = m.group(5).upper()
            pool = allowed + list(derived)
            if not (exact_or_structural(per_clk, pool) and exact_or_structural(clock, pool)):
                continue
            hz = clock * (1e9 if clk_unit == "GHZ" else 1e6)
            bytes_per_s = per_clk * hz
            scale = {"GB/S": 1e9, "TB/S": 1e12, "MB/S": 1e6}[out_unit]
            if abs(bytes_per_s / scale - stated) <= max(0.5, abs(stated) * 0.02):
                derived.add(stated)

        # Form 5: a stated ratio or percentage whose two inputs are both allowed.
        # "2,156,080 divided by 4,181,088, or 51.6 percent".
        for m in re.finditer(r"(\d[\d,]*(?:\.\d+)?)\s+(?:divided by|over)\s+"
                             r"(\d[\d,]*(?:\.\d+)?)\s*[,\s]*(?:or|is|equals)\s*(?:about\s+)?"
                             r"(\d[\d,]*(?:\.\d+)?)\s*(?:percent|%)", text):
            a, b, pct = (float(g.replace(",", "")) for g in m.groups())
            pool = allowed + list(derived)
            if b == 0:
                continue
            if not exact_or_structural(a, pool):
                continue
            if not exact_or_structural(b, pool):
                continue
            if abs(a / b * 100 - pct) <= max(0.5, abs(pct) * 0.006):
                derived.add(pct)

        if len(derived) == before:
            break

    return derived


def word_expr_candidates(clause, nums):
    """Evaluate a word-operator clause left to right, plus the common shapes.

    "130,659 times 4,096" -> product. "130,659 times 130,660 divided by 2" ->
    product then halve. "16 times 130,659, or 2,090,544" -> the product of the
    first two numbers. Returns every candidate so the caller can accept a match
    without needing a full expression parser.
    """
    out = set()
    if len(nums) < 2:
        return out
    # Dedupe only ADJACENT repeats, keeping order. "n=130,659, that is 130,659 times
    # 130,660 divided by 2" has 130,659 twice but the expression uses it once, so
    # collapse consecutive duplicates rather than a global set.
    uniq = []
    for v in nums:
        if not uniq or not matches(v, [uniq[-1]]):
            uniq.append(v)
    def div(a, b):
        return a / b if b else 0.0

    out.add(math.prod(uniq))
    out.add(math.prod(nums))
    # Ordered shapes the prose actually produces:
    #   "A times B"                  -> A*B
    #   "A times B divided by C"     -> A*B/C   (the n(n+1)/2 shape)
    #   "16 times A plus 16 times B" -> sums of products
    if len(uniq) >= 2:
        out.add(uniq[0] * uniq[1])
        out.add(uniq[1] * uniq[0])
        out.add(uniq[0] + uniq[1])
    if len(uniq) >= 3:
        out.add(div(uniq[0] * uniq[1], uniq[2]))
        out.add(div(uniq[1] * uniq[2], uniq[0]))
        out.add(div(uniq[0] * uniq[2], uniq[1]))
        out.add(uniq[0] + uniq[1] + uniq[2])
        out.add(uniq[0] * uniq[1] + uniq[2])
    if len(nums) >= 3:
        out.add(div(nums[0] * nums[1], nums[2]))
        out.add(nums[0] * nums[1])
        out.add(div(nums[0] * nums[2], nums[1]))
    if len(nums) >= 4:
        out.add(div(nums[0] * nums[1], nums[2] * nums[3]))
        out.add(nums[0] * nums[1] + nums[2] * nums[3])
        out.add(div(nums[0] * nums[1], nums[2]) * nums[3])
        # "n=130,659, that is 130,659 times 130,660 divided by 2": the first number is
        # restating n, so the real expression is nums[0]*nums[2]/nums[3].
        out.add(div(nums[0] * nums[2], nums[3]))
        out.add(div(nums[1] * nums[2], nums[3]))
    if len(nums) >= 5:
        out.add(div(div(nums[0] * nums[1], nums[2]) * nums[3], nums[4]))
    return out

def main():
    draft_path, sources_path = sys.argv[1], sys.argv[2]
    text = open(draft_path, encoding="utf-8").read()
    words = len(re.findall(r"\S+", text))

    allowed = load_allowed(sources_path) + load_textbook()
    allowed = allowed + list(derived_numbers(text, allowed))
    nums = numbers_in(text)

    unsourced = []
    illustrative = 0
    for raw, val, is_measurement in nums:
        if val in STRUCTURAL:
            continue
        # years are always fine in a book about the history of ideas
        if 1990 <= val <= 2030 and float(val).is_integer():
            continue
        if matches(val, allowed):
            continue
        if is_measurement:
            unsourced.append(raw)
        else:
            illustrative += 1

    uniq = sorted(set(unsourced), key=lambda s: -float(s.replace(",", "")))

    print(f"words: {words}")
    print(f"numbers found: {len(nums)}")
    print(f"measurement claims unmatched: {len(uniq)}")
    print(f"illustrative integers (allowed): {illustrative}")

    failed = False

    if words < MIN_WORDS:
        print(f"LENGTH: FAIL -- {words} words, minimum {MIN_WORDS}")
        failed = True
    else:
        print(f"LENGTH: PASS -- {words} words")

    # Structure: a chapter needs resumption points. One H2 is the title; the
    # subheads are what let a reader re-enter a chapter at the idea they want.
    # Enforced here rather than generated at build time, because a regex cannot
    # title a section and an invented heading relocates the slop problem.
    subheads = re.findall(r"^###\s+\S", text, re.M)
    want = max(3, words // 400)
    if len(subheads) < 3:
        print(f"STRUCTURE: FAIL -- {len(subheads)} subheadings, need at least 3")
        failed = True
    elif len(subheads) < want:
        print(f"STRUCTURE: WARN -- {len(subheads)} subheadings for {words} words"
              f" (aim for {want})")
    else:
        print(f"STRUCTURE: PASS -- {len(subheads)} subheadings")

    if uniq:
        print("\nnumbers with no provenance (add to textbook.json or sources.json, or"
              " rewrite the sentence without the figure):")
        for u in uniq[:30]:
            print(f"  {u}")
        # No tolerance here. A fabricated figure must fail on its own: allowing a
        # few "incidentals" let an injected "47.3 GB at 812.6 MB/s" pass untouched.
        # Legitimate arithmetic is handled by derived_numbers(), which requires the
        # chapter to print the inputs it derived from.
        print(f"\nFACT: FAIL -- {len(uniq)} unmatched")
        failed = True
    else:
        print("\nFACT: PASS")

    print("\nGATE: " + ("FAIL" if failed else "PASS"))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
