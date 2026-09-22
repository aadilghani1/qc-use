"""Run a test file end to end: one private browser, one Jev goal per step, independent checks, one report."""

import base64
import io
import json
import os
import secrets as tokens
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image, ImageDraw

from . import __version__, judge
from .chrome import Chrome
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
from .secrets import MIN_MASKED, Redactor, resolve

# browser-harness reads BU_NAME when it is imported: one daemon name per qc-use process.
DAEMON = f"qc-use-{os.getpid()}"
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


def connect(chrome):
    os.environ["BU_NAME"] = DAEMON
    os.environ["BU_CDP_URL"] = chrome.url
    from browser_harness.admin import daemon_alive, restart_daemon

    if daemon_alive(DAEMON):
        restart_daemon(DAEMON)  # A daemon from an earlier run in this process points at a closed Chrome.


def reap(pid):
    try:
        os.waitpid(pid, 0)
    except (ChildProcessError, OSError):
        pass


def disconnect(browser):
    from browser_harness import _ipc
    from browser_harness.admin import restart_daemon

    try:
        if browser:
            browser.close()
    finally:
        # The daemon is our child. Reap it as it exits, or the harness waits 15 s on the zombie.
        if pid := _ipc.identify(DAEMON, timeout=2.0):
            threading.Thread(target=reap, args=(pid,), daemon=True).start()
        restart_daemon(DAEMON)


# Read-only: where secret values appear on screen, so saved screenshots can black them out.
SECRET_RECTS = """(values => {
  const rects=[], walker=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);
  for (let node; (node=walker.nextNode());) for (const value of values) {
    for (let i=node.textContent.indexOf(value); i>=0; i=node.textContent.indexOf(value,i+value.length)) {
      const range=document.createRange(); range.setStart(node,i); range.setEnd(node,i+value.length);
      for (const r of range.getClientRects()) rects.push([r.x,r.y,r.width,r.height]);
    }
  }
  for (const e of document.querySelectorAll('input,textarea')) {
    if (!values.some(v=>(e.value||'').includes(v))) continue;
    const r=e.getBoundingClientRect(); rects.push([r.x,r.y,r.width,r.height]);
  }
  return rects;
})"""


def masked(browser, data, secrets):
    """JPEG bytes with every visible secret value blacked out, or None if masking could not be done."""
    try:
        data = data or browser.call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
        values = [v for v in secrets.values() if len(v) >= MIN_MASKED]
        rects = browser.evaluate(f"{SECRET_RECTS}({json.dumps(values)})") if values else []
    except Exception:
        return None
    image = Image.open(io.BytesIO(base64.b64decode(data))).convert("RGB")
    draw = ImageDraw.Draw(image)
    for x, y, w, h in rects or []:
        draw.rectangle([x - 2, y - 2, x + w + 2, y + h + 2], fill=(24, 24, 24))
    output = io.BytesIO()
    image.save(output, "JPEG", quality=80)
    return output.getvalue()


def screenshot(browser, page, folder, name, secrets):
    """Save a step screenshot. If masking fails, save nothing."""
    image = masked(browser, page.get("screenshot") if page else None, secrets)
    if image is None:
        return None
    (folder / name).write_bytes(image)
    return f"steps/{name}"


def verify(spec, step, browser, goal):
    """Check the step on fresh observations. DONE is a claim; these answers are the evidence."""
    statements = step.expect or [step.text]
    kind = "expect" if step.expect else "implicit"
    for attempt in range(2):
        page = browser.observe(screenshot=True)
        checks = [
            CheckResult(kind=kind, text=text, probability=round(p, 4), outcome=band(p, spec.bands))
            for text, p in zip(statements, judge.expectations(page, goal, statements))
        ]
        checks += [CheckResult(kind="check", text=str(c), outcome="pass" if c.evaluate(page) else "fail")
                   for c in step.check]
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
    agent = Agent(
        browser, goal, page=page, history=history, max_actions=max(1, min(spec.budget.step, remaining)),
        secrets=context["secrets"], files=spec.files, policy=guard, screenshots=context["live"] is not None,
        done_when=step.expect,
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
            checks, final = verify(spec, step, browser, goal)
            outcome = next((o for o in ("fail", "inconclusive") if any(c.outcome == o for c in checks)), "pass")
            if outcome != "pass":
                reason = "; ".join(f"{c.kind} {c.outcome}: {c.text}" for c in checks if c.outcome != "pass")
        else:
            code, p = judge.diagnose(agent.state["page"], goal, history)
            stuck = len(history) >= 3 and all(h["page_changed"] is False for h in history[-3:])
            reason = ("Three actions in a row changed nothing. " if stuck else "Jev found no way forward. ") + (
                f"Most likely: {judge.REASONS[code]} ({p:.0%})"
            )
    except Blocked as error:
        reason = str(error)
    except NeedsApproval as error:
        outcome, reason = "needs_approval", str(error)
        approval = Approval(
            step=index + 1, rule=error.rule, action=error.action, probability=round(error.probability, 4),
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
        actions=[ActionRecord.model_validate(h) for h in history[agent.state["first_action"]:]],
        signals=[Signal(kind=s["kind"], text=s["text"]) for s in signals],
        dialogs=[Dialog(**d) for d in browser.dialogs[dialogs_before:]],
        generated=[GeneratedValue(field=c["field"], value=c["value"], source=c["source"])
                   for c in agent.state["text_calls"] if c["source"] == "fake"],
        decisions=len(agent.state["decisions"]),
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        url=(final or agent.state["page"] or {}).get("url"),
        screenshot=(screenshot(browser, final, folder, f"{index + 1:02d}.jpg", context["secrets"])
                    if context["screenshots"] else None),
    )
    trace = {"goal": goal, "decisions": agent.state["decisions"], "text_calls": agent.state["text_calls"],
             "signals": signals}
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
        ratings.append(RatingResult(
            name=name, levels=rating.levels, level=level, label=rating.levels[level], score=round(answer.score, 3),
            probabilities={k: round(v, 4) for k, v in answer.probabilities.items()},
            confidence=round(answer.confidence, 4), minimum=rating.min, outcome=outcome,
        ))
    return ratings


def summarize(results, ratings):
    total = len(results)
    stopped = next((r for r in results if r.outcome not in {"pass", "skipped"}), None)
    if stopped:
        verb = {"fail": "failed", "inconclusive": "was inconclusive", "blocked": "was blocked",
                "needs_approval": "needs approval"}[stopped.outcome]
        return stopped.outcome, f"Step {stopped.index} of {total} {verb}: {stopped.reason}"
    low = [r for r in ratings if r.outcome == "fail"]
    if low:
        return "fail", "All steps passed, but " + ", ".join(
            f"{r.name.replace('_', ' ')} was rated '{r.label}', below '{r.minimum}'" for r in low) + "."
    return "pass", f"All {total} steps passed."


def run(spec, *, allow=(), allow_production=False, approve=None, profile=None, headless=False,
        results_dir="qa-results", live=None, screenshots=True, echo=print):
    if looks_like_production(spec.url) and not (spec.allow_production or allow_production):
        raise SetupError(
            f"{spec.url} looks like a production site. Test against localhost, staging, or a preview deployment, "
            "or set allow_production: true in the test (or pass --allow-production) if you really mean it."
        )
    try:
        secrets = resolve(spec.secrets)
    except KeyError as error:
        where = spec.path.parent / ".env" if spec.path else "qa/.env"
        raise SetupError(f"Missing secrets: {error.args[0]}. Set them in the environment or in {where}.") from None
    jev_url, keys, policy_model = model.jev_endpoint()
    if not model.credential(keys):
        raise SetupError(f"Jev needs {' or '.join(keys)}. Run `qc-use doctor` for setup help.")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-") + tokens.token_hex(2)
    out = Path(results_dir) / run_id
    (out / "steps").mkdir(parents=True)
    redact, meter = Redactor(secrets), model.Meter(spec.max_cost)
    model.configure(redact=redact, meter=meter)
    guard = Guardrails(spec, allow, approve)
    context = {"tag": tokens.token_hex(3), "secrets": secrets, "out": out, "live": live, "screenshots": screenshots}
    started, started_at = time.perf_counter(), datetime.now(timezone.utc).isoformat(timespec="seconds")
    results, traces, approval, browser, chrome = [], [], None, None, None
    try:
        chrome = Chrome(profile=profile, headless=headless)
        connect(chrome)
        from .engine.browser import Browser

        browser = Browser(spec.url, on_dialog=guard.on_dialog)
        history = []
        try:
            page = browser.observe(screenshot=live is not None)
            guard.after_observe(page)
        except Blocked as error:
            page = None
            results.append(StepResult(index=1, text=spec.steps[0].text, outcome="blocked", reason=str(error)))
        for index in range(len(spec.steps) if page is not None else 0):
            echo(f"  {index + 1}/{len(spec.steps)} {spec.steps[index].text}")
            result, approval, page, trace = run_step(spec, index, browser, guard, page, history, results, context)
            results.append(result)
            traces.append(trace)
            if live:
                live.record(result)
            echo(f"      {result.outcome} · {plural(len(result.actions), 'action')} · {result.elapsed_ms / 1000:.1f} s"
                 + (f" · {result.reason}" if result.reason else ""))
            if result.outcome != "pass":
                break
        results += [StepResult(index=i + 1, text=spec.steps[i].text, outcome="skipped")
                    for i in range(len(results), len(spec.steps))]
        ratings = []
        if spec.rate and any(r.actions for r in results):
            try:
                ratings = rate(spec, results, round((time.perf_counter() - started) * 1000))
            except (model.BudgetExceeded, RuntimeError, ValueError) as error:
                echo(f"  Ratings skipped: {error}")
    finally:
        try:
            if chrome:
                disconnect(browser)
        finally:
            if chrome:
                chrome.close()
            model.configure()
    outcome, summary = summarize(results, ratings)
    route = "Vercel AI Gateway" if jev_url.startswith(model.GATEWAY) else jev_url.split("/")[2]
    report = Report(
        run_id=run_id,
        test={"title": spec.title, "file": str(spec.path or ""), "url": spec.url},
        started_at=started_at,
        elapsed_ms=round((time.perf_counter() - started) * 1000),
        outcome=outcome,
        exit_code=EXIT_CODES[outcome],
        summary=summary,
        steps=results,
        ratings=ratings,
        approval=approval,
        cost=Cost(usd=round(meter.usd, 6), estimated=meter.estimated, model_calls=meter.calls,
                  unpriced_calls=meter.unpriced, cap=spec.max_cost),
        models={"policy": policy_model, "route": route, "text": model.text_settings()[1],
                "qc_use": __version__},
        artifacts={"json": "report.json", "markdown": "report.md", "trace": "trace.json", "folder": str(out)},
    )
    # One more redaction pass on everything written to disk.
    report = Report.model_validate(redact(report.model_dump(mode="json")))
    (out / "report.json").write_text(report.model_dump_json(indent=2))
    (out / "report.md").write_text(markdown(report))
    trace = {"test": spec.model_dump(mode="json"), "gates": guard.gates, "steps": traces}
    (out / "trace.json").write_text(json.dumps(redact(trace), indent=2, default=str))
    return report
