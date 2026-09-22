"""Offline contracts for test files, guardrails, secrets, verdicts and reports. No paid APIs, no browser."""

import base64
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

from qc_use import guards, judge, runner
from qc_use.engine.agent import Blocked, NeedsApproval, StalePage
from qc_use.report import EXIT_CODES, Report, markdown
from qc_use.secrets import Redactor, read_env_file, resolve
from qc_use.spec import Bands, Check, SpecError, load

EXAMPLE = """---
url: http://localhost:3000/login
secrets: [LOGIN_EMAIL, LOGIN_PASSWORD]
persona: { role: Head of Ops, company_size: 50-200 }
never: [cancel the subscription]
rate:
  onboarding_ease: [confusing, effortful, okay, smooth, effortless]
fail_on: [http_5xx]
---
# Onboarding

A new ops lead signs up.

1. Log in with LOGIN_EMAIL and LOGIN_PASSWORD
   - expect: the dashboard is visible
   - check: url contains /home
2. Complete onboarding as the persona,
   including the team size question
   - expect: the checklist shows every item complete
"""


def write(tmp_path, text, name="flow.md"):
    path = tmp_path / name
    path.write_text(text)
    return path


def test_test_file_parses_settings_steps_and_details(tmp_path):
    spec = load(write(tmp_path, EXAMPLE))
    assert spec.title == "Onboarding" and spec.intent == "A new ops lead signs up."
    assert [s.text for s in spec.steps] == [
        "Log in with LOGIN_EMAIL and LOGIN_PASSWORD",
        "Complete onboarding as the persona, including the team size question",
    ]
    assert spec.steps[0].expect == ["the dashboard is visible"]
    assert str(spec.steps[0].check[0]) == "url contains /home"
    assert spec.rate["onboarding_ease"].levels[0] == "confusing"
    assert spec.persona["company_size"] == "50-200" and spec.fail_on == ["http_5xx"]


@pytest.mark.parametrize(
    ("front", "message"),
    [
        ("url: ftp://example.test", "http"),
        ("url: http://localhost:3000\nsecrets: [bad-name]", "environment variable"),
        ("url: http://localhost:3000\nfail_on: [typo]", "fail_on"),
        ("url: http://localhost:3000\nunknown: 1", "unknown"),
        ("url: http://localhost:3000\nrate: {ease: [only]}", "rate"),
        ("url: http://localhost:3000\nbands: {pass_at: 0.3, fail_at: 0.5}", "fail_at"),
        ("url: http://localhost:3000\nfiles: {avatar: missing.png}", "does not exist"),
    ],
)
def test_invalid_test_files_explain_the_problem(tmp_path, front, message):
    with pytest.raises(SpecError, match=message):
        load(write(tmp_path, f"---\n{front}\n---\n1. Do something\n"))


def test_a_test_needs_front_matter_and_steps(tmp_path):
    with pytest.raises(SpecError, match="front matter"):
        load(write(tmp_path, "1. Do something\n"))
    with pytest.raises(SpecError, match="steps"):
        load(write(tmp_path, "---\nurl: http://localhost:3000\n---\nJust prose.\n"))


@pytest.mark.parametrize(
    ("line", "page", "expected"),
    [
        ("url contains /home", {"url": "http://x/home", "title": "", "text": ""}, True),
        ("url matches /orders/\\d+$", {"url": "http://x/orders/42", "title": "", "text": ""}, True),
        ('text contains "3 items"', {"url": "", "title": "", "text": "Cart: 3 ITEMS"}, True),
        ("text does not contain Error", {"url": "", "title": "", "text": "Something failed: error"}, False),
        ("title contains Dashboard", {"url": "", "title": "Dashboard · App", "text": ""}, True),
    ],
)
def test_deterministic_checks(line, page, expected):
    assert Check.parse(line).evaluate(page) is expected


def test_unknown_checks_are_rejected():
    with pytest.raises(SpecError, match="Unknown check"):
        Check.parse("the page looks nice")
    with pytest.raises(SpecError, match="Only url"):
        Check.parse("text matches .*")


@pytest.mark.parametrize(
    ("url", "production"),
    [
        ("http://localhost:3000", False),
        ("http://127.0.0.1:8080", False),
        ("http://192.168.1.20", False),
        ("https://app.test", False),
        ("https://staging.acme.com", False),
        ("https://acme-preview.vercel.app", False),
        ("https://app.acme.com", True),
        ("https://acme.com", True),
    ],
)
def test_production_detection(url, production):
    assert guards.looks_like_production(url) is production


def test_sites_allow_start_origin_and_declared_patterns():
    sites = guards.Sites("http://localhost:3000/login", ["*.acme.test", "auth.example.test:8443"])
    assert sites.allows("http://localhost:3000/dashboard")
    assert not sites.allows("http://localhost:4000/")
    assert sites.allows("https://app.acme.test/x")
    assert sites.allows("https://auth.example.test:8443/cb") and not sites.allows("https://auth.example.test/cb")
    assert not sites.allows("https://evil.test/") and not sites.allows("javascript:alert(1)")


def spec_for(tmp_path, front="url: http://localhost:3000"):
    return load(write(tmp_path, f"---\n{front}\n---\n1. Do something\n"))


def test_links_outside_allowed_sites_are_blocked_before_clicking(tmp_path):
    guard = guards.Guardrails(spec_for(tmp_path))
    link = {"label": "Docs", "kind": "click", "role": "link", "href": "https://elsewhere.test/docs"}
    with pytest.raises(Blocked, match="outside the allowed sites"):
        guard.before_act(link, {"url": "http://localhost:3000/"}, {})
    with pytest.raises(Blocked, match="failed to load"):
        guard.after_observe({"url": "chrome-error://chromewebdata/"})


def test_never_gate_asks_before_clicks_and_caches(tmp_path, monkeypatch):
    gate = Mock(return_value={rule: 0.05 for rule in guards.DEFAULT_NEVER} | {"cancel the plan": 0.9})
    monkeypatch.setattr(judge, "gate", gate)
    guard = guards.Guardrails(spec_for(tmp_path, "url: http://localhost:3000\nnever: [cancel the plan]"))
    button = {"label": "Cancel plan", "kind": "click", "role": "button"}
    page = {"url": "http://localhost:3000/billing"}
    with pytest.raises(NeedsApproval) as stop:
        guard.before_act(button, page, {})
    assert stop.value.rule == "cancel the plan"
    with pytest.raises(NeedsApproval):
        guard.before_act(button, page, {})
    assert gate.call_count == 1
    guard.before_act({"label": "Name", "kind": "fill", "role": "textbox"}, page, {})  # Typing never commits.
    assert gate.call_count == 1


def test_allowed_or_approved_rules_let_the_action_run(tmp_path, monkeypatch):
    monkeypatch.setattr(judge, "gate", Mock(return_value={rule: 0.95 for rule in guards.DEFAULT_NEVER}))
    button = {"label": "Delete", "kind": "click", "role": "button"}
    allowed = guards.Guardrails(spec_for(tmp_path), allowed_rules=["*"])
    allowed.before_act(button, {"url": "http://localhost:3000/"}, {})
    approve = Mock(return_value=True)
    asked = guards.Guardrails(spec_for(tmp_path), approve=approve)
    asked.before_act(button, {"url": "http://localhost:3000/"}, {})
    assert approve.call_count == len(guards.DEFAULT_NEVER)


def test_dialog_policy(tmp_path, monkeypatch):
    guard = guards.Guardrails(spec_for(tmp_path))
    assert guard.on_dialog({"type": "alert", "message": "Saved"}) == (True, None)
    with pytest.raises(Blocked, match="prompt"):
        guard.on_dialog({"type": "prompt", "message": "Name?"})
    monkeypatch.setattr(judge, "dialog", Mock(return_value=(True, {guards.DEFAULT_NEVER[0]: 0.9})))
    with pytest.raises(NeedsApproval):
        guard.on_dialog({"type": "confirm", "message": "Delete workspace?"})


def test_redactor_masks_nested_values_longest_first():
    redact = Redactor({"EMAIL": "jane@acme.test", "USER": "jane", "PIN": "123"})
    masked = redact({"text": "Signed in as jane@acme.test (jane)", "list": ["jane", 123], "PIN 123": "123"})
    assert masked == {"text": "Signed in as [secret:EMAIL] ([secret:USER])", "list": ["[secret:USER]", 123],
                      "PIN 123": "123"}  # Values under four characters are left alone.


def test_secrets_resolve_from_environment_and_env_file(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("# test\nLOGIN_EMAIL='qa@acme.test'\n")
    assert read_env_file(tmp_path / ".env") == {"LOGIN_EMAIL": "qa@acme.test"}
    monkeypatch.setenv("LOGIN_PASSWORD", "hunter22")
    monkeypatch.delenv("MISSING_ONE", raising=False)
    assert resolve(["LOGIN_PASSWORD"]) == {"LOGIN_PASSWORD": "hunter22"}
    with pytest.raises(KeyError, match="MISSING_ONE"):
        resolve(["LOGIN_PASSWORD", "MISSING_ONE"])


@pytest.mark.parametrize(("p", "outcome"), [(0.95, "pass"), (0.8, "pass"), (0.5, "inconclusive"), (0.2, "fail")])
def test_probability_bands_never_round_up(p, outcome):
    assert runner.band(p, Bands()) == outcome


def test_goal_names_only_the_current_step_and_secret_names(tmp_path):
    spec = load(write(tmp_path, EXAMPLE))
    goal = runner.compose_goal(spec, 0, [], "ab12")
    assert "Current step, the only goal now: Log in with LOGIN_EMAIL" in goal
    assert "Done when: the dashboard is visible." in goal and "Later steps are not part of this goal." in goal
    assert "LOGIN_EMAIL, LOGIN_PASSWORD" in goal and "role: Head of Ops" in goal and "ab12" in goal


def test_production_url_and_missing_secret_stop_before_launch(tmp_path, monkeypatch):
    launched = Mock()
    monkeypatch.setattr(runner, "Chrome", launched)
    with pytest.raises(runner.SetupError, match="production"):
        runner.run(spec_for(tmp_path, "url: https://app.acme.com"))
    monkeypatch.delenv("LOGIN_PASSWORD", raising=False)
    with pytest.raises(runner.SetupError, match="LOGIN_PASSWORD"):
        runner.run(spec_for(tmp_path, "url: http://localhost:3000\nsecrets: [LOGIN_PASSWORD]"))
    launched.assert_not_called()


def test_exit_codes_distinguish_failures_from_unknowns():
    assert EXIT_CODES == {"pass": 0, "fail": 1, "inconclusive": 2, "blocked": 2, "needs_approval": 3}


def test_report_markdown_states_the_verdict_and_rerun_hint():
    report = Report.model_validate({
        "run_id": "r1", "test": {"title": "Onboarding", "file": "qa/flow.md", "url": "http://localhost:3000"},
        "started_at": "2026-09-22T10:00:00+00:00", "elapsed_ms": 2100, "outcome": "needs_approval", "exit_code": 3,
        "summary": "Step 1 of 1 needs approval.",
        "steps": [{"index": 1, "text": "Delete the workspace", "outcome": "needs_approval", "reason": "risky"}],
        "approval": {"step": 1, "rule": "delete data", "action": "Delete", "probability": 0.9,
                     "rerun_with": 'qc-use run qa/flow.md --allow "delete data"'},
        "cost": {"usd": 0.0001, "estimated": False, "model_calls": 3, "unpriced_calls": 0, "cap": 0.25},
        "models": {"policy": "typesafe-ai/jev", "route": "Vercel AI Gateway", "text": "inception/mercury-2.5"},
        "artifacts": {"json": "report.json", "markdown": "report.md", "trace": "trace.json", "folder": "x"},
    })
    text = markdown(report)
    assert text.startswith("# ✋ Onboarding: needs approval")
    assert '--allow "delete data"' in text and "0 actions" in text


def test_summary_reports_the_first_non_passing_step():
    steps = [Mock(outcome="pass", index=1, reason=None), Mock(outcome="fail", index=2, reason="expect fail: x"),
             Mock(outcome="skipped", index=3, reason=None)]
    assert runner.summarize(steps, []) == ("fail", "Step 2 of 3 failed: expect fail: x")


def test_bundled_demo_tests_and_examples_are_valid():
    root = Path(runner.__file__).parent
    paths = [*root.joinpath("demo", "tests").glob("*.md"), *root.parent.joinpath("examples").glob("*.md")]
    for path in paths:
        if path.name != "README.md":
            assert load(path).steps


def test_a_step_passes_only_on_fresh_evidence(tmp_path, monkeypatch):
    spec = load(write(tmp_path, EXAMPLE))
    fresh = {"url": "http://localhost:3000/home", "title": "Home", "text": "Dashboard", "actions": []}
    browser = Mock(observe=Mock(return_value=fresh))
    monkeypatch.setattr(judge, "expectations", Mock(return_value=[0.1]))
    monkeypatch.setattr(runner, "SETTLE_SECONDS", 0)
    checks, _ = runner.verify(spec, spec.steps[0], browser, "goal")
    assert [(c.kind, c.outcome) for c in checks] == [("expect", "fail"), ("check", "pass")]
    assert browser.observe.call_count == 2  # One read-only re-check, then the answer stands.


def test_screenshots_black_out_secret_values_or_are_not_saved():
    buffer = io.BytesIO()
    Image.new("RGB", (100, 60), "white").save(buffer, "JPEG")
    data = base64.b64encode(buffer.getvalue()).decode()
    browser = Mock(evaluate=Mock(return_value=[[10, 10, 30, 20]]))
    image = Image.open(io.BytesIO(runner.masked(browser, data, {"PASSWORD": "hunter22"})))
    assert "hunter22" in browser.evaluate.call_args.args[0]
    assert image.getpixel((25, 20))[0] < 60 and image.getpixel((90, 50))[0] > 200
    browser.evaluate.side_effect = StalePage("changed")
    assert runner.masked(browser, data, {"PASSWORD": "hunter22"}) is None
