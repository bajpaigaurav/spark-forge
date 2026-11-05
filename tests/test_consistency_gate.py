#!/usr/bin/env python3
"""Regression tests for the consistency gate.

Three defects shipped through the slop and fact gates because neither checks whether
the book agrees with itself. Each is pinned here by constructing the defect in memory
and asserting the gate flags it, so a future refactor cannot quietly stop catching it.

  1. ch 09: a clause pasted twice inside one sentence (duplicate fragment).
  2. ch 12: two fragments pasted twice in a paragraph (duplicate fragment).
  3. ch 14: L^2 x d x 2 bytes labelled "one head of one layer" (unit/label).

Also pinned: derived sources whose arithmetic disagrees with their value, and the
current book passing.

Run: python3 tests/test_consistency_gate.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "skills"))
import consistency_gate  # noqa: E402


def kinds(text):
    """Run every detector over a synthetic chapter and return the finding kinds."""
    paras = consistency_gate.paragraphs(text)
    out = []
    out += consistency_gate.duplicate_sentences(paras)
    out += consistency_gate.duplicate_fragments(paras)
    out += consistency_gate.check_units(text)
    return {k for _, k, _, _ in out}


# --- defect 1: ch 09, clause pasted twice in one sentence --------------------

def test_ch09_duplicate_clause():
    clause = ("divided elementwise by the normalizer phi(Q)·Σ_j phi(K_j) — the row "
              "sums of phi(Q) phi(K)^T — which is what makes the result a weighted "
              "average rather than an unnormalized sum that grows with n")
    text = (f"Compute phi(Q) (phi(K)^T V), {clause}, {clause}. "
            "Associativity does the work.")
    assert "duplicate-fragment" in kinds(text), "ch 09 clause repeat not caught"
    print("ok: ch 09 duplicated clause caught")


# --- defect 2: ch 12, two fragments pasted twice -----------------------------

def test_ch12_duplicate_fragments():
    frag = ("Paging cuts the waste per sequence from most of a worst-case buffer to "
            "at most one block, and a larger batch amortizes each weight read over "
            "more tokens")
    text = f"Memory bounds the batch size. {frag} {frag}."
    assert "duplicate-fragment" in kinds(text), "ch 12 fragment repeat not caught"

    frag2 = "so that shared prefixes are found by tree walk rather than by hash."
    text2 = (f"SGLang manages the cache as a radix tree, {frag2} {frag2} "
             "The idea changed the cache into an addressable resource.")
    assert "duplicate-fragment" in kinds(text2), "ch 12 second fragment not caught"
    print("ok: ch 12 duplicated fragments caught")


# --- defect 3: ch 14, L^2 x d x 2 labelled one head --------------------------

def test_ch14_unit_label():
    text = ("Stored in fp16 at L = 130,659 and d = 128, S for one head of one layer "
            "occupies L × L × 2 bytes, which is 130,659 × 130,659 × 128 × 2 = 4.37 TB.")
    assert "unit-label" in kinds(text), "ch 14 one-head mislabel not caught"
    print("ok: ch 14 L^2 x d x 2 as one head caught")


def test_ch14_correct_label_accepted():
    """The corrected framing (all d heads of one layer) must not be flagged."""
    text = ("the score matrix for a single head occupies L × L × 2 bytes, 34.1 GB, so "
            "all d heads of one layer occupy L × L × d × 2 bytes, which is "
            "130,659 × 130,659 × 128 × 2 = 4.37 TB.")
    assert "unit-label" not in kinds(text), "correct all-heads framing rejected"
    print("ok: corrected all-heads framing accepted")


def test_plain_one_head_accepted():
    """L x L x 2 = C with no extra factor is legitimately one head."""
    text = ("At two bytes each, S occupies 130,659 × 130,659 × 2 = 34.1 GB for a "
            "single head in a single layer.")
    assert "unit-label" not in kinds(text), "legitimate one-head count rejected"
    print("ok: legitimate one-head byte count accepted")


# --- derivation self-consistency --------------------------------------------

def test_derivation_mismatch_caught():
    src = "derived: 111.5 / 34.1"
    got = consistency_gate.evaluate_derivation(src)
    assert got is not None and abs(got[0] - 3.27) < 1e-2, "quotient not evaluated"
    # a fabricated quotient must fail the comparison
    bad = {"id": "x", "value": 3.3, "source": "derived: 111.5 / 34.1"}
    computed, _ = got
    assert abs(computed - 3.3) > 3.3 * consistency_gate.TOLERANCE, "3.3 accepted"
    print("ok: derivation mismatch detectable (3.27 vs 3.3)")


def test_derivation_percent_accepted():
    """A ratio stored as a percentage must resolve to its value."""
    for src, val in [("derived: prefix_cache_hits_total / "
                      "prefix_cache_queries_total = 12,285,952 / 12,804,579", 95.9),
                     ("derived: mtp_accepted_total / mtp_drafted_total = "
                      "42,181 / 62,390", 67.6)]:
        computed, _ = consistency_gate.evaluate_derivation(src)
        assert abs(computed * 100 - val) <= val * consistency_gate.TOLERANCE, src
    print("ok: percent-stored ratios accepted")


def test_live_sources_consistent():
    findings = consistency_gate.check_sources(
        os.path.join(ROOT, "content", "sources.json"))
    assert not findings, f"sources.json self-inconsistent: {findings}"
    print("ok: content/sources.json derivations agree with values")


# --- the whole book passes --------------------------------------------------

def test_book_passes():
    """The current chapters must pass, including the three fixed defects."""
    for cid in ("09-quadratic-wall", "12-paged-attention", "14-flash-attention"):
        path = os.path.join(ROOT, "content", "chapters", cid + ".md")
        findings, _ = consistency_gate.check_chapter(path)
        fails = [f for f in findings if f[0] == "FAIL"]
        assert not fails, f"{cid} still failing: {fails}"
    print("ok: fixed chapters pass")


def test_gate_exit_zero():
    """A temp chapter with no defects must exit zero through main()."""
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False,
                                     encoding="utf-8") as fh:
        fh.write("A short chapter. It has two sentences and no repeated clause "
                 "anywhere inside it at all.\n")
        tmp = fh.name
    try:
        rc = consistency_gate.main(["gate", tmp])
        assert rc == 0, f"clean chapter exited {rc}"
    finally:
        os.unlink(tmp)
    print("ok: clean chapter exits 0")


if __name__ == "__main__":
    test_ch09_duplicate_clause()
    test_ch12_duplicate_fragments()
    test_ch14_unit_label()
    test_ch14_correct_label_accepted()
    test_plain_one_head_accepted()
    test_derivation_mismatch_caught()
    test_derivation_percent_accepted()
    test_live_sources_consistent()
    test_book_passes()
    test_gate_exit_zero()
    print("\nall consistency_gate tests passed")
