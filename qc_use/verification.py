"""Check explicit outcomes and action evidence without replaying browser input."""

import time

from . import judge
from .engine.errors import Blocked, StalePage
from .guards import Guardrails
from .report import CheckResult


def band(p, bands):
    """Map a model probability to the test's declared outcome bands."""
    return "pass" if p >= bands.pass_at else "fail" if p <= bands.fail_at else "inconclusive"


def check_page(spec, step, page, goal, history=()):
    """Use explicit assertions; step prose is only a fallback when no outcomes are declared."""
    checks = []
    if step.mode == "act":
        performed = any(h.get("kind") not in {None, "wait"} for h in history)
        checks.append(
            CheckResult(kind="action", text="Recorded input for this step", outcome="pass" if performed else "fail")
        )
    statements = [*step.action, *step.expect]
    kinds = ["action"] * len(step.action) + ["expect"] * len(step.expect)
    if not statements and not step.check:
        statements, kinds = [step.text], ["implicit"]
    if statements:
        probabilities = judge.expectations(page, goal, statements, history, action_statements=step.action)
        checks += [
            CheckResult(kind=kind, text=text, probability=round(p, 4), outcome=band(p, spec.bands))
            for text, kind, p in zip(statements, kinds, probabilities, strict=True)
        ]
    checks += [
        CheckResult(kind="check", text=str(c), outcome="pass" if c.evaluate(page) else "fail") for c in step.check
    ]
    return checks


def verify(spec, step, browser, goal, guard=None, history=()):
    """Poll fresh evidence until all checks pass or the verification timeout expires."""
    deadline = time.monotonic() + spec.verify_timeout
    guard = guard or Guardrails(spec)
    checks, page = [], None
    while True:
        try:
            page = browser.observe(screenshot=False)
            guard.after_observe(page)
            if tabs := browser.new_tabs():
                raise Blocked(f"unsupported: the page opened a new tab or window ({tabs[0]})")
            checks = check_page(spec, step, page, goal, history)
            if all(c.outcome == "pass" for c in checks):
                return checks, page
        except StalePage:
            if time.monotonic() >= deadline:
                raise
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            if page is None:
                raise Blocked("No stable page before the verification timeout; no input repeated.")
            return checks, page
        time.sleep(min(0.25, remaining))
