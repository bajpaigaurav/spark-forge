"""Tests for the punctuation repair in apply_fixes.

The repair exists because a verifier fix ending in a period, swapped into a clause that
already had one, leaves "..". An earlier version replaced every ".." in the chapter and
damaged three chapters that legitimately contain ranges and series: "levels -1, .. 1",
"a + a^2 + .. + a^k", and a CLI path "run .. 2.5 ..". These cases pin that down.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apply_fixes


def check(inp, want):
    got = apply_fixes.repair_punctuation(inp)
    assert got == want, f"{inp!r} -> {got!r}, wanted {want!r}"


def test_double_period_before_capital():
    check("a sentence.. Then next", "a sentence. Then next")


def test_double_period_at_end():
    check("ends here..", "ends here.")


def test_period_before_comma_keeps_comma():
    check("mechanism., and a", "mechanism, and a")


def test_comma_before_period_becomes_period():
    check("architecture,. Next", "architecture. Next")


def test_range_with_two_dots_survives():
    check("levels -1, -0.8667, -0.7333, .. 1. A", "levels -1, -0.8667, -0.7333, .. 1. A")


def test_series_with_two_dots_survives():
    check("1 + a + a^2 + .. + a^k", "1 + a + a^2 + .. + a^k")


def test_cli_path_survives():
    check("run .. 2.5 .. in the list", "run .. 2.5 .. in the list")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"ok  {fn.__name__}")
    print(f"{len(fns)} passed")
