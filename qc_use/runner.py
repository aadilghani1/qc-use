"""Run a test file end to end: one private browser, one Jev goal per step, independent checks, one report."""

import json
import secrets as tokens
import time
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, judge
from .capture import masked, screenshot
from .chrome import Chrome, connect, disconnect
from .engine import model
from .engine.agent import Agent, Blocked, NeedsApproval
from .guards import Guardrails, looks_like_production
from .report import (
    EXIT_CODES,
    ActionRecord,
    Approval,
    CheckResult,
    Cost,
    Dialog,
    GeneratedValue,
    RatingResult,
    Report,
    Signal,
    StepResult,
    markdown,
    plural,
)
from .secrets import Redactor, resolve

SETTLE_SECONDS = 1.0  # One read-only re-check for pages that finish rendering just after DONE.


class SetupError(RuntimeError):
    """Nothing ran: the test, its secrets, its keys, or its target URL are not ready."""


def band(p, bands):
    return "pass" if p >= bands.pass_at else "fail" if p <= bands.fail_at else "inconclusive"


def compose_goal(spec, index, results, tag):
    step = spec.steps[index]
    lines = [f"Test: {spec.title}." + (f" {spec.intent}" if spec.intent else "")]
    if spec.persona:
        traits = "; ".join(f"{k.replace('_', ' ')}: {v}" for k, v in spec.persona.items())
        lines.append(f"Act as this persona and use its values in forms: {traits}.")
    if spec.secrets:
        lines.append(f"Declared secrets, entered only by choosing their secret targets: {', '.join(spec.secrets)}.")
    lines.append(f"Run tag for fake test data: {tag}.")
    if results:
        lines.append("Already done: " + " ".join(f"{r.index}. {r.text} ({r.outcome})." for r in results))
    lines.append(f"Current step, the only goal now: {step.text}")
    if step.expect:
        lines.append("Done when: " + "; ".join(step.expect) + ".")
    if index + 1 < len(spec.steps):
        lines.append("Choose DONE as soon as this step is complete. Later steps are not part of this goal.")
    return "\n".join(lines)


def verify(spec, step, browser, goal, guard=None, history=()):
    """Check the step on fresh observations. DONE is a claim; these answers are the evidence."""
    statements = [step.text, *step.expect] if step.expect else [step.text]
    kind = "expect" if step.expect else "implicit"
    for attempt in range(2):
        page = browser.observe(screenshot=False)
        (guard or Guardrails(spec)).after_observe(page)
        if tabs := browser.new_tabs():
            raise Blocked(f"unsupported: the page opened a new tab or window ({tabs[0]})")
        checks = [
            CheckResult(kind=kind, text=text, probability=round(p, 4), outcome=band(p, spec.bands))
            for text, p in zip(
                statements, judge.expectations(page, goal, statements, history, action_statement=step.text), strict=True
            )
        ]
        checks += [
            CheckResult(kind="check", text=str(c), outcome="pass" if c.evaluate(page) else "fail") for c in step.check
        ]
        if all(c.outcome == "pass" for c in checks) or attempt:
            return checks, page
        time.sleep(SETTLE_SECONDS)


def run_step(spec, index, browser, guard, page, history, results, context):
    step = spec.steps[index]
    goal = compose_goal(spec, index, results, context["tag"])
    guard.goal = goal
    dialogs_before = len(browser.dialogs)
    started = time.perf_counter()
    remaining = spec.budget.test - len(history)
    first_action = len(history)

    def complete(current):
        if not all(check.evaluate(current) for check in step.check):
            return False
        probabilities = judge.expectations(
            current, goal, [step.text, *step.expect], history[first_action:], action_statement=step.text
        )
        return all(band(p, spec.bands) == "pass" for p in probabilities)

    agent = Agent(
        browser,
        goal,
        page=page,
        history=history,
        max_actions=max(1, min(spec.budget.step, remaining)),
        secrets=context["secrets"],
        files=spec.files,
        policy=guard,
        screenshots=context["live"] is not None,
        done_when=[step.text, *step.expect, *(str(c) for c in step.check)],
        completion_check=complete,
    )
    outcome, reason, checks, approval, final = "blocked", None, [], None, None
    try:
        if remaining <= 0:
            raise Blocked(f"Reached the test's budget of {spec.budget.test} actions")
        for state in agent.run():
            if context["live"]:
                shot = (state["page"] or {}).get("screenshot")
                context["live"](index, state, masked(browser, shot, context["secrets"]) if shot else None)
        if agent.state["status"] == "done":
            checks, final = verify(spec, step, browser, goal, guard, history[agent.state["first_action"] :])
            outcome = next((o for o in ("fail", "inconclusive") if any(c.outcome == o for c in checks)), "pass")
            if outcome != "pass":
                reason = "; ".join(f"{c.kind} {c.outcome}: {c.text}" for c in checks if c.outcome != "pass")
        else:
            code, p = judge.diagnose(agent.state["page"], goal, history)
            stuck = len(history) >= 3 and all(h["page_changed"] is False for h in history[-3:])
            reason = ("Three actions in a row changed nothing. " if stuck else "Jev found no way forward. ") + (
                f"Most likely: {judge.REASONS[code]} ({p:.0%})"
            )
    except KeyboardInterrupt:
        context["interrupted"] = True
        reason = "Run interrupted; inspect the page before retrying."
    except Blocked as error:
        reason = str(error)
    except NeedsApproval as error:
        outcome, reason = "needs_approval", str(error)
        approval = Approval(
            step=index + 1,
            rule=error.rule,
            action=error.action,
            probability=round(error.probability, 4),
            rerun_with=f'qc-use run {spec.path} --allow "{error.rule}"',
        )
    except (model.BudgetExceeded, RuntimeError, ValueError, TimeoutError) as error:
        reason = str(error) or type(error).__name__
    signals = [*agent.state["signals"], *browser.signals()]
    failing = [s for s in signals if s["kind"] in spec.fail_on]
    if failing and outcome != "needs_approval":  # An opted-in signal is definite evidence, even when blocked.
        checks += [CheckResult(kind="signal", text=f"{s['kind']}: {s['text']}", outcome="fail") for s in failing]
        outcome, reason = "fail", f"fail_on {failing[0]['kind']}: {failing[0]['text']}"
    folder = context["out"] / "steps"
    result = StepResult(
        index=index + 1,
        text=step.text,
        outcome=outcome,
        reason=reason,
        checks=checks,
        actions=[ActionRecord.model_validate(h) for h in history[agent.state["first_action"] :]],
        signals=[Signal(kind=s["kind"], text=s["text"]) for s in signals],
        dialogs=[Dialog(**d) for d in browser.dialogs[dialogs_before:]],
        generated=[
            GeneratedValue(field=c["field"], value=c["value"], source=c["source"])
            for c in agent.state["text_calls"]
            if c["source"] == "fake"
        ],
        decisions=len(agent.state["decisions"]),
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        url=(final or agent.state["page"] or {}).get("url"),
        screenshot=(
            screenshot(browser, final, folder, f"{index + 1:02d}.jpg", context["secrets"])
            if context["screenshots"]
            else None
        ),
    )
    trace = {
        "goal": goal,
        "decisions": agent.state["decisions"],
        "text_calls": agent.state["text_calls"],
        "signals": signals,
    }
    return result, approval, (final or agent.state["page"]), trace


def rate(spec, results, elapsed_ms):
    summary = {
        "persona": spec.persona,
        "intent": spec.intent,
        "total_seconds": round(elapsed_ms / 1000, 1),
        "steps": [
            {
                "step": r.text,
                "outcome": r.outcome,
                "actions": len(r.actions),
                "waits": sum(a.kind == "wait" for a in r.actions),
                "actions_without_visible_change": sum(a.page_changed is False for a in r.actions),
                "extra_decisions": max(0, r.decisions - len(r.actions)),
                "dialogs": [d.message for d in r.dialogs],
                "signals": [s.kind for s in r.signals],
                "seconds": round(r.elapsed_ms / 1000, 1),
                "typed": [a.text for a in r.actions if a.text],
            }
            for r in results
            if r.outcome != "skipped"
        ],
    }
    ratings = []
    for name, answer in judge.ratings(summary, spec.rate).items():
        rating = spec.rate[name]
        level = max(range(len(rating.levels)), key=lambda i: answer.probabilities[str(i)])
        outcome = "info" if rating.min is None else "pass" if level >= rating.levels.index(rating.min) else "fail"
        ratings.append(
            RatingResult(
                name=name,
                levels=rating.levels,
                level=level,
                label=rating.levels[level],
                score=round(answer.score, 3),
                probabilities={k: round(v, 4) for k, v in answer.probabilities.items()},
                confidence=round(answer.confidence, 4),
                minimum=rating.min,
                outcome=outcome,
            )
        )
    return ratings


def summarize(results, ratings):
    total = len(results)
    stopped = next((r for r in results if r.outcome not in {"pass", "skipped"}), None)
    if stopped:
        verb = {
            "fail": "failed",
            "inconclusive": "was inconclusive",
            "blocked": "was blocked",
            "needs_approval": "needs approval",
        }[stopped.outcome]
        return stopped.outcome, f"Step {stopped.index} of {total} {verb}: {stopped.reason}"
    low = [r for r in ratings if r.outcome == "fail"]
    if low:
        return "fail", "All steps passed, but " + ", ".join(
            f"{r.name.replace('_', ' ')} was rated '{r.label}', below '{r.minimum}'" for r in low
        ) + "."
    return "pass", f"All {total} steps passed."


def run(
    spec,
    *,
    allow=(),
    allow_production=False,
    approve=None,
    profile=None,
    headless=False,
    results_dir="qa-results",
    live=None,
    screenshots=True,
    echo=print,
):
    if looks_like_production(spec.url) and not (spec.allow_production or allow_production):
        raise SetupError(
            f"{spec.url} looks like a production site. Test against localhost, staging, or a preview deployment, "
            "or set allow_production: true in the test (or pass --allow-production) if you really mean it."
        )
    try:
        secrets = resolve(spec.secrets)
    except ValueError as error:
        raise SetupError(str(error)) from None
    except KeyError as error:
        where = spec.path.parent / ".env" if spec.path else "qa/.env"
        raise SetupError(f"Missing secrets: {error.args[0]}. Set them in the environment or in {where}.") from None
    try:
        jev_url, keys, policy_model = model.jev_endpoint()
    except ValueError as error:
        raise SetupError(str(error)) from None
    if not model.credential(keys):
        raise SetupError(f"Jev needs {' or '.join(keys)}. Run `qc-use doctor` for setup help.")
    run_id = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + tokens.token_hex(2)
    out = Path(results_dir) / run_id
    (out / "steps").mkdir(parents=True)
    redact, meter = Redactor(secrets), model.Meter(spec.max_cost)
    raw_echo = echo

    def safe_echo(message):
        raw_echo(redact.text(message))

    if live:
        live.redact = redact
    model.configure(redact=redact, meter=meter)
    safe_approve = (lambda rule, action, p: approve(redact.text(rule), redact.text(action), p)) if approve else None
    guard = Guardrails(spec, allow, safe_approve)
    context = {"tag": tokens.token_hex(3), "secrets": secrets, "out": out, "live": live, "screenshots": screenshots}
    started, started_at = time.perf_counter(), datetime.now(UTC).isoformat(timespec="seconds")
    results, traces, approval, browser, chrome = [], [], None, None, None
    ratings: list[RatingResult] = []
    cleanup_errors: list[str] = []
    try:
        chrome = Chrome(profile=profile, headless=headless)
        connect(chrome)
        from .engine.browser import Browser

        browser = Browser(spec.url, on_dialog=guard.on_dialog)
        history: list[dict] = []
        try:
            page = browser.observe(screenshot=live is not None)
            guard.after_observe(page)
        except Blocked as error:
            page = None
            results.append(StepResult(index=1, text=spec.steps[0].text, outcome="blocked", reason=str(error)))
        for index in range(len(spec.steps) if page is not None else 0):
            safe_echo(f"  {index + 1}/{len(spec.steps)} {spec.steps[index].text}")
            result, approval, page, trace = run_step(spec, index, browser, guard, page, history, results, context)
            results.append(result)
            traces.append(trace)
            if live:
                live.record(result)
            safe_echo(
                f"      {result.outcome} · {plural(len(result.actions), 'action')} · {result.elapsed_ms / 1000:.1f} s"
                + (f" · {result.reason}" if result.reason else "")
            )
            if result.outcome != "pass":
                break
        results += [
            StepResult(index=i + 1, text=spec.steps[i].text, outcome="skipped")
            for i in range(len(results), len(spec.steps))
        ]
        ratings = []
        if spec.rate and not context.get("interrupted"):
            try:
                ratings = rate(spec, results, round((time.perf_counter() - started) * 1000))
            except (model.BudgetExceeded, RuntimeError, ValueError) as error:
                safe_echo(f"  Ratings unavailable: {error}")
                if any(r.min is not None for r in spec.rate.values()) and all(r.outcome == "pass" for r in results):
                    results[-1].outcome = "inconclusive"
                    results[-1].reason = "A required rating could not be checked."
    except (RuntimeError, ValueError, TimeoutError, OSError, KeyboardInterrupt) as error:
        context["interrupted"] = isinstance(error, KeyboardInterrupt)
        reason = "Run interrupted." if context["interrupted"] else str(error)
        index = len(results)
        if index < len(spec.steps):
            results.append(StepResult(index=index + 1, text=spec.steps[index].text, outcome="blocked", reason=reason))
        elif results:
            results[-1].outcome, results[-1].reason = "blocked", reason
        results += [
            StepResult(index=i + 1, text=spec.steps[i].text, outcome="skipped")
            for i in range(len(results), len(spec.steps))
        ]
    finally:
        if chrome:
            for close in (lambda: disconnect(browser), chrome.close):
                try:
                    close()
                except (RuntimeError, ValueError, TimeoutError, OSError) as error:
                    cleanup_errors.append(str(error))
        model.configure()
    if cleanup_errors:
        safe_echo("  Cleanup: " + "; ".join(cleanup_errors))
        if results and all(r.outcome == "pass" for r in results):
            results[-1].outcome, results[-1].reason = "blocked", "Browser cleanup failed: " + "; ".join(cleanup_errors)
    outcome, summary = summarize(results, ratings)
    route = "Vercel AI Gateway" if jev_url.startswith(model.GATEWAY) else jev_url.split("/")[2]
    report = Report(
        run_id=run_id,
        test={"title": spec.title, "file": str(spec.path or ""), "url": spec.url},
        started_at=started_at,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        outcome=outcome,
        exit_code=130 if context.get("interrupted") else EXIT_CODES[outcome],
        summary=summary,
        steps=results,
        ratings=ratings,
        approval=approval,
        cost=Cost(
            usd=round(meter.usd, 6),
            estimated=meter.estimated,
            model_calls=meter.calls,
            unpriced_calls=meter.unpriced,
            cap=spec.max_cost,
        ),
        models={"policy": policy_model, "route": route, "text": model.text_settings()[1], "qc_use": __version__},
        artifacts={"json": "report.json", "markdown": "report.md", "trace": "trace.json", "folder": str(out)},
    )
    # One more redaction pass on everything written to disk.
    report = report.redacted(redact)
    (out / "report.json").write_text(report.model_dump_json(indent=2))
    (out / "report.md").write_text(markdown(report))
    trace = {"test": spec.model_dump(mode="json"), "gates": guard.gates, "steps": traces}
    (out / "trace.json").write_text(json.dumps(redact(trace), indent=2, default=str))
    return report
