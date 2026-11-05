#!/usr/bin/env python3
"""Tests for the review/diagram pass.

The reviewers answer in terse bullets (a quoted clause plus the correction), so a
finding is a bullet, not a labelled section. A report that says NONE must yield no
findings -- otherwise a reviewer that correctly found nothing looks identical to one
that found three things.

Run: python3 tests/test_review.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import review  # noqa: E402


def test_findings_from_bullets():
    r = """- "attention multiplies Q by K" -- it multiplies Q by K transpose, and scales by sqrt(d_head).
- "12 x 4096^2 is 201,300,000" -- the exact value is 201,326,592."""
    f = review.findings(r)
    assert len(f) == 2, f
    assert "Q by K transpose" in f[0][1], f[0]
    assert "201,326,592" in f[1][1], f[1]
    print("ok: findings parsed from bullets")


def test_none_report():
    assert review.findings("NONE") == []
    assert review.findings("none") == []
    assert review.findings("NONE\n") == []
    print("ok: NONE yields no findings")


def test_empty_report():
    assert review.findings("") == []
    assert review.findings(None) == []
    print("ok: empty report yields nothing")


def test_numbered_bullets_stripped():
    r = """1. "the KV cache stores logits" -- it stores keys and values per layer.
2. "fp16 max is 64000" -- fp16's largest finite value is 65504."""
    f = review.findings(r)
    assert len(f) == 2, f
    assert not f[0][1].startswith("1."), f[0][1]
    assert "65504" in f[1][1]
    print("ok: numbered bullets stripped")


def test_short_lines_ignored():
    r = """NONE of note.
- "ok" """
    f = review.findings(r)
    assert f == [], f
    print("ok: short/noise lines ignored")


def test_reviewer_prompts_present():
    for name in ("ML_REVIEWER", "OPS_REVIEWER", "DIAGRAM_PLANNER", "VERIFY_REVIEWER"):
        p = getattr(review, name)
        assert isinstance(p, str) and len(p) > 200, name
    # The terse constraint is what stops the spiral; pin it.
    assert "under 250 words" in review.ML_REVIEWER
    assert "under 250 words" in review.OPS_REVIEWER
    assert "Do not plan" in review.ML_REVIEWER
    assert "REFUTE" in review.VERIFY_REVIEWER.upper()
    print("ok: all four reviewer prompts present and terse")


def test_roundtrip_review_and_diagram():
    cid = "_test-chapter"
    review.save_review(cid, "ml", "- test finding")
    assert review.load_review(cid, "ml") == "- test finding"
    spec = {"needed": True, "kind": "flow", "title": "t", "nodes": ["a", "b"]}
    review.save_diagram(cid, spec)
    assert review.load_diagram(cid) == spec
    os.remove(os.path.join(review.REVIEWS, f"{cid}.ml.txt"))
    os.remove(os.path.join(review.DIAGRAMS, cid + ".json"))
    print("ok: review and diagram roundtrip")


if __name__ == "__main__":
    test_findings_from_bullets()
    test_none_report()
    test_empty_report()
    test_numbered_bullets_stripped()
    test_short_lines_ignored()
    test_reviewer_prompts_present()
    test_roundtrip_review_and_diagram()
    print("\nall review tests passed")
