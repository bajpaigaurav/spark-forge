#!/usr/bin/env python3
"""Regression tests for the fact gate's derivation detector.

Two classes of bug are pinned here:
  1. Correct arithmetic that the gate rejected (which stalled the loop), so the
     derivation forms must keep accepting it.
  2. Fabricated figures that must never derive, including the Form 12 digit bug
     where int(2.5**2) == 6 matched the "6" inside "812.6".

Run: python3 tests/test_fact_gate.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills"))
import fact_gate  # noqa: E402

ALLOWED = fact_gate.load_textbook() + fact_gate.load_allowed(
    os.path.join(ROOT, "content", "sources.json"))


def derives(text, target):
    return any(abs(v - target) < 1e-6 for v in fact_gate.derived_numbers(text, ALLOWED))


# --- correct derivations the gate must accept ---------------------------------

def test_unit_scaled_result():
    """Bytes / 1e6 stated as MB must resolve."""
    t = ("At a mean prompt length of 130,659 tokens, the KV traffic per rank is "
         "130,659 × 1,024 = 133.8 MB per generated token.")
    assert derives(t, 133.8), "unit-scaled MB result rejected"
    print("ok: unit-scaled result (133.8 MB)")


def test_ratio_as_percent():
    """3/64 stated as a percentage must resolve."""
    t = ("That is 3 bytes of metadata against 64 bytes of payload, "
         "an overhead of 3/64 = 4.7 percent.")
    assert derives(t, 4.7), "percent-scaled ratio rejected"
    print("ok: ratio as percent (4.7%)")


def test_repeated_operand():
    """The same figure twice in a clause must collapse to two operands."""
    t = "The cache is 130,659 × 1,024 = 133.8 MB per token."
    assert derives(t, 133.8), "repeated operand rejected"
    print("ok: repeated operand collapsed")


def test_integer_square():
    """d=4096 then d^2 must still resolve after the Form 12 fix."""
    t = "d = 4096, so d² = 16,777,216 and the FFN is 4 x 16,777,216 = 67,108,864."
    assert derives(t, 16777216) and derives(t, 67108864), "integer square rejected"
    print("ok: integer square (16,777,216)")


# --- fabrications the gate must reject ---------------------------------------

FABRICATED = [
    "47.3 GB",
    "94.7 tok/s",
    "138.2 GB",
    "812.6 MB/s",
    "812.6",
    "351 GB",
    "146 tok/s",
]


def test_fabrications_rejected():
    for n in FABRICATED:
        d = fact_gate.derived_numbers(f"The rig measured {n} on this box.", ALLOWED)
        assert not d, f"{n} leaked as derived: {sorted(d)}"
    print(f"ok: {len(FABRICATED)} fabricated figures rejected")


def test_form12_digit_bug():
    """int(2.5**2) == 6 must not match the 6 in 812.6."""
    d = fact_gate.derived_numbers("812.6", ALLOWED)
    assert 6.25 not in d, "Form 12 fractional-square digit bug returned"
    print("ok: fractional square no longer matches a bare digit")


def test_published_chapters_pass():
    """Every published chapter must pass the fact gate."""
    import json
    q = json.load(open(os.path.join(ROOT, "state", "queue.json"), encoding="utf-8"))
    import subprocess
    failures = []
    for c in q["chapters"]:
        if c["status"] != "published":
            continue
        path = os.path.join(ROOT, "content", "chapters", c["id"] + ".md")
        p = subprocess.run([sys.executable, os.path.join(ROOT, "skills", "fact_gate.py"),
                            path, os.path.join(ROOT, "content", "sources.json")],
                           capture_output=True, text=True)
        if p.returncode != 0:
            failures.append(c["id"])
    assert not failures, f"published chapters failing the gate: {failures}"
    print("ok: all published chapters pass")


if __name__ == "__main__":
    test_unit_scaled_result()
    test_ratio_as_percent()
    test_repeated_operand()
    test_integer_square()
    test_fabrications_rejected()
    test_form12_digit_bug()
    test_published_chapters_pass()
    print("\nall fact_gate tests passed")
