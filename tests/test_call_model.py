#!/usr/bin/env python3
"""Regression tests for the reasoning-starvation root cause in call_model.

The loop stalled for hours because a budget-starved call was retried with the
identical request, which fails identically. These tests pin the escalation
ladder and the wall-clock deadline without spending model tokens: they stub
urlopen and inspect the request bodies call_model sends.

Run: python3 tests/test_call_model.py
"""
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import forge  # noqa: E402


class FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def reply(finish, content, reasoning, budget):
    """A gateway response shaped like the real one."""
    return FakeResp(json.dumps({
        "choices": [{"message": {"content": content}, "finish_reason": finish}],
        "usage": {"completion_tokens": budget,
                  "completion_tokens_details": {"reasoning_tokens": reasoning}},
    }).encode())


def run_with(script):
    """Drive call_model against a scripted list of responses; return the bodies sent."""
    sent = []
    it = iter(script)

    def fake_urlopen(req, timeout=None):
        sent.append(json.loads(req.data))
        return next(it)

    orig = forge.urllib.request.urlopen
    forge.urllib.request.urlopen = fake_urlopen
    try:
        result = forge.call_model("sys", "user", max_tokens=3000, effort="high", retries=5)
    finally:
        forge.urllib.request.urlopen = orig
    return result, sent


def test_starved_call_retries_with_low_effort_no_budget_growth():
    """A spiralled call must retry at low effort, never with a bigger budget."""
    result, sent = run_with([
        reply("length", "", 3000, 3000),
        reply("length", "", 3000, 3000),
        reply("stop", "the report", 6113, 9000),
    ])
    assert result == "the report", result
    assert len(sent) == 3, len(sent)
    assert sent[0]["reasoning_effort"] == "high" and sent[0]["max_tokens"] == 3000
    # Every retry drops to low effort...
    assert sent[1]["reasoning_effort"] == "low", sent[1]
    assert sent[2]["reasoning_effort"] == "low", sent[2]
    # ...and never grows the budget, which is what bought 160000 tokens of reasoning.
    assert all(b["max_tokens"] == 3000 for b in sent), [b["max_tokens"] for b in sent]
    print("ok: retry drops effort, budget stays fixed")


def test_retries_differ_from_first_attempt():
    """Retries must not repeat the FIRST attempt: effort drops to low.

    Attempts 2..N are deliberately identical to each other -- a spiralled draw is a
    sampling accident, so repeating the same cheap request is exactly the intended fix.
    """
    _, sent = run_with([
        reply("length", "", 3000, 3000),
        reply("length", "", 3000, 3000),
        reply("length", "", 3000, 3000),
        reply("length", "", 3000, 3000),
        reply("length", "", 3000, 3000),
    ])
    assert len(sent) == 5, len(sent)
    assert sent[0]["reasoning_effort"] == "high", sent[0]
    assert all(b["reasoning_effort"] == "low" for b in sent[1:]), \
        [b["reasoning_effort"] for b in sent]
    print("ok: retries drop to low effort and repeat cheaply")


def test_retry_budget_is_five():
    """Five cheap attempts are the policy; a bad draw costs ~10 min, a good one ~110s."""
    assert forge.call_model.__defaults__[3] == 5, forge.call_model.__defaults__
    print("ok: default retries is 5")


def test_success_first_attempt_sends_one_call():
    result, sent = run_with([reply("stop", "fine", 2000, 2500)])
    assert result == "fine" and len(sent) == 1
    print("ok: happy path is one call")


def test_deadline_blocks_all_attempts():
    """Past the deadline no call is made at all, so a run cannot start into the cron kill."""
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append(json.loads(req.data))
        return reply("length", "", 3000, 3000)

    orig = forge.urllib.request.urlopen
    forge.urllib.request.urlopen = fake_urlopen
    try:
        result = forge.call_model("sys", "user", max_tokens=3000, effort="high",
                                  retries=5, deadline=time.time() - 1)
    finally:
        forge.urllib.request.urlopen = orig
    assert result is None, result
    assert len(sent) == 0, f"made {len(sent)} calls past the deadline"
    print("ok: deadline stops every attempt")


def test_deadline_stops_midway():
    """A deadline hit between attempts stops retrying rather than running into the wall."""
    sent = []
    now = [1000.0]

    def fake_urlopen(req, timeout=None):
        sent.append(json.loads(req.data))
        now[0] += 5000.0  # this call overshot the deadline
        return reply("length", "", 3000, 3000)

    orig_urlopen = forge.urllib.request.urlopen
    orig_time = forge.time.time
    forge.urllib.request.urlopen = fake_urlopen
    forge.time.time = lambda: now[0]
    try:
        result = forge.call_model("sys", "user", max_tokens=3000, effort="high",
                                  retries=5, deadline=now[0] + 100)
    finally:
        forge.urllib.request.urlopen = orig_urlopen
        forge.time.time = orig_time
    assert result is None, result
    assert len(sent) == 1, f"retried {len(sent)} times after the deadline"
    print("ok: deadline stops retrying mid-run")


def test_deadline_constant_has_headroom():
    """The run budget must stay under the cron tick's 3600s kill."""
    assert forge.RUN_BUDGET_SECONDS < 3600, forge.RUN_BUDGET_SECONDS
    print(f"ok: run budget {forge.RUN_BUDGET_SECONDS}s < 3600s tick kill")


# --- prompt-shape regressions -------------------------------------------------
# These pin the constraint that caused the revise spiral: asking the model to make the
# revision at least as long as the draft makes it plan an expansion instead of revising,
# and it then reasons to the budget on every attempt (verified at 30k/40k/60k/90k, all
# finish=length, zero content). Removing the instruction returned finish=stop at 16.5k.

def test_no_expansion_forcing_constraints():
    import inspect
    revise_src = inspect.getsource(forge.revise)
    prompt = revise_src.split('user = f"""')[1].split('"""')[0]
    assert "at least as long as the draft" not in prompt, \
        "revise prompt still forces the revision to be as long as the draft"
    assert "must be longer than the original" not in forge.POLISH_SYSTEM, \
        "polish prompt still forces growth"
    assert "must be at least as long as the draft" not in forge.REVISER_SYSTEM, \
        "reviser system prompt still forces growth"
    print("ok: no expansion-forcing constraints in any prompt")


def test_revise_starts_at_low_effort():
    import inspect
    src = inspect.getsource(forge.revise)
    assert 'effort="low"' in src, "revise must start at low effort, high effort spirals"
    print("ok: revise starts at low effort")


def test_long_report_is_trimmed():
    """A long critic report makes the reviser spiral; revise() must trim it."""
    import inspect
    src = inspect.getsource(forge.revise)
    assert "REVISE_REPORT_CHARS" in src, "revise() no longer trims the report"
    assert forge.REVISE_REPORT_CHARS <= 2000, forge.REVISE_REPORT_CHARS
    print("ok: long reports are trimmed before revising")


if __name__ == "__main__":
    test_starved_call_retries_with_low_effort_no_budget_growth()
    test_retries_differ_from_first_attempt()
    test_retry_budget_is_five()
    test_success_first_attempt_sends_one_call()
    test_deadline_blocks_all_attempts()
    test_deadline_stops_midway()
    test_deadline_constant_has_headroom()
    test_no_expansion_forcing_constraints()
    test_revise_starts_at_low_effort()
    test_long_report_is_trimmed()
    print("\nall call_model tests passed")
