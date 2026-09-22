"""Real-app failure cases without model calls, browser input, or production data."""

from unittest.mock import Mock

import httpx
import pytest

from qc_use import cli, judge, runner, verification
from qc_use.engine import model
from qc_use.report import CheckResult, StepResult
from qc_use.secrets import resolve
from qc_use.spec import Check, Rating, SpecError, Step, TestSpec, load


def spec_for(step, **kwargs):
    return TestSpec(title="Local fixture", url="http://localhost:3000", steps=[step], **kwargs)


def page(text="Pick your handle"):
    return {"url": "http://localhost:3000/onboarding", "title": "Fixture", "text": text, "actions": []}


def test_observation_checks_do_not_grade_the_instruction_or_require_input(monkeypatch):
    step = Step(text="Read the hero", mode="observe", check=[Check.parse("text contains Pick your handle")])
    ask = Mock(side_effect=AssertionError("Exact observations need no model"))
    monkeypatch.setattr(judge, "expectations", ask)
    checks = verification.check_page(spec_for(step), step, page(), "goal")
    assert [(c.kind, c.outcome) for c in checks] == [("check", "pass")]
    ask.assert_not_called()


def test_exact_outcomes_do_not_add_a_hidden_prose_expectation(monkeypatch):
    step = Step(text="Submit, don't use Google, then wait", check=[Check.parse("text contains Pick your handle")])
    ask = Mock()
    monkeypatch.setattr(judge, "expectations", ask)
    checks = verification.check_page(spec_for(step), step, page(), "goal", [{"kind": "click"}])
    assert all(c.outcome == "pass" for c in checks)
    ask.assert_not_called()
    assert verification.check_page(spec_for(step), step, page(), "goal")[0].outcome == "fail"


def test_explicit_action_requirements_remain_independent(monkeypatch):
    step = Step(text="Save", action=["Click Save"], check=[Check.parse("text contains Pick your handle")])
    ask = Mock(return_value=[0.1])
    monkeypatch.setattr(judge, "expectations", ask)
    checks = verification.check_page(spec_for(step), step, page(), "goal", [{"kind": "click", "action": "Cancel"}])
    assert checks[1].kind == "action" and checks[1].outcome == "fail"
    assert ask.call_args.kwargs["action_statements"] == ["Click Save"]


def test_delayed_result_waits_without_repeating_input(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(verification.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(verification.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    step = Step(text="Observe", mode="observe", check=[Check.parse("text contains Pick your handle")])
    b = Mock(
        observe=Mock(side_effect=lambda **_: page("Loading" if clock[0] < 3.5 else "Pick your handle")),
        new_tabs=Mock(return_value=[]),
    )
    checks, _ = verification.verify(spec_for(step), step, b, "goal")
    assert all(c.outcome == "pass" for c in checks) and clock[0] == 3.5
    b.act.assert_not_called()


def test_wait_has_a_deadline(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(verification.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(verification.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    step = Step(text="Observe", mode="observe", check=[Check.parse("text contains Missing")])
    b = Mock(observe=Mock(return_value=page()), new_tabs=Mock(return_value=[]))
    checks, _ = verification.verify(spec_for(step, verify_timeout=1), step, b, "goal")
    assert checks[0].outcome == "fail" and clock[0] == 1
    b.act.assert_not_called()


def test_document_checks_are_distinct_and_truncated_absence_is_unknown():
    state = {**page("Footer"), "document_text": "Hero\nFooter", "document_text_truncated": False}
    assert Check.parse("document contains Hero").evaluate(state)
    assert not Check.parse("text contains Hero").evaluate(state)
    state["document_text_truncated"] = True
    with pytest.raises(ValueError, match="truncated"):
        Check.parse("document does not contain Missing").evaluate(state)


def test_new_settings_and_observation_contract_parse(tmp_path):
    path = tmp_path / "test.md"
    path.write_text(
        "---\nurl: http://localhost:3000\nverify_timeout: 6\n---\n"
        "1. Read hero\n   - mode: observe\n   - check: text contains Hero\n"
    )
    spec = load(path)
    assert spec.steps[0].mode == "observe" and spec.verify_timeout == 6
    path.write_text(path.read_text().replace("   - check: text contains Hero", "   - action: Click Save"))
    with pytest.raises(SpecError, match="observe steps"):
        load(path)


def test_retries_are_visible_and_do_not_repeat_browser_actions(monkeypatch):
    responses = [httpx.Response(503, headers={"Retry-After": "2"}), httpx.Response(200, json={"usage": {"cost": 0}})]
    post = Mock(side_effect=responses)
    sleep = Mock()
    monkeypatch.setattr(model.CLIENT, "post", post)
    monkeypatch.setattr(model.time, "sleep", sleep)
    meter = model.Meter(0.25)
    model.configure(meter=meter)
    try:
        model.post_json("https://example.test/api", "fake", {})
    finally:
        model.configure()
    sleep.assert_called_once_with(2)
    assert [r["status"] for r in meter.requests] == [503, 200]
    assert meter.pricing == [{"source": "provider", "usd": 0.0, "status": "zero"}]


def test_transport_retries_respect_request_cap(monkeypatch):
    post = Mock(side_effect=httpx.ConnectError("offline"))
    monkeypatch.setattr(model.CLIENT, "post", post)
    monkeypatch.setattr(model.time, "sleep", Mock())
    meter = model.Meter(0.25, max_calls=2)
    model.configure(meter=meter)
    try:
        with pytest.raises(model.BudgetExceeded, match="request count"):
            model.post_json("https://example.test/api", "fake", {})
    finally:
        model.configure()
    assert post.call_count == 2 and len(meter.requests) == 2


def test_missing_zero_and_tiny_costs_are_distinguishable():
    meter = model.Meter()
    for payload in [{}, {"usage": {"cost": 0}}, {"usage": {"cost": 0.0000000123}}]:
        meter.charge(payload)
    assert [p["status"] for p in meter.pricing] == ["unavailable", "zero", "priced"]
    assert meter.usd == 0.0000000123 and meter.unpriced == 1


@pytest.mark.parametrize("bad", [{"score": 99}, None, "invalid", []])
def test_invalid_rating_preserves_valid_siblings_and_raw_diagnostics(monkeypatch, bad):
    good = {"score": 1, "probabilities": {"0": 0, "1": 1}, "confidence": 1}
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "fake")
    monkeypatch.setattr(
        judge, "post_json", Mock(return_value={"model": "fixture", "answers": {"good": good, "bad": bad}})
    )
    issues = {}
    rates = {name: Rating(levels=["bad", "good"]) for name in ["good", "bad"]}
    result = judge.ratings({}, rates, issues)
    assert list(result) == ["good"] and issues["bad"]["response"] == bad


def test_ratings_include_content_checks_and_partial_coverage(monkeypatch):
    step = Step(text="Read", mode="observe", check=[Check.parse("text contains Hero")])
    spec = spec_for(step, rate={"clarity": Rating(levels=["unclear", "clear"])})
    answer = model.ScoreAnswer(score=1, probabilities={"0": 0, "1": 1}, confidence=0.4)
    ratings = Mock(return_value={"clarity": answer})
    monkeypatch.setattr(judge, "ratings", ratings)
    results = [
        StepResult(
            index=1,
            text="Read",
            outcome="inconclusive",
            evidence={"text": "Hero"},
            checks=[CheckResult(kind="check", text="text contains Hero", outcome="pass")],
        )
    ]
    result = runner.rate(spec, results, 100)
    sent = ratings.call_args.args[0]
    assert sent["steps"][0]["evidence"]["text"] == "Hero"
    assert sent["coverage"] == {"passed": 0, "total": 1}
    assert result[0].partial and result[0].completed_steps == 0


def test_secret_templates_are_opt_in_and_keep_passwords_literal(monkeypatch):
    monkeypatch.setenv("EMAIL", "qa+{tag}@example.test")
    monkeypatch.setenv("PASSWORD", "literal-{tag}-password")
    result = resolve(["EMAIL", "PASSWORD"], ["EMAIL"], "abc123")
    assert result == {"EMAIL": "qa+abc123@example.test", "PASSWORD": "literal-{tag}-password"}


def test_repeat_requires_an_explicit_fixture_contract(tmp_path, monkeypatch, capsys):
    path = tmp_path / "test.md"
    path.write_text("---\nurl: http://localhost:3000\n---\n1. Sign up\n")
    run = Mock()
    monkeypatch.setattr(runner, "run", run)
    assert cli.main(["run", str(path), "--repeat", "3"]) == 4
    run.assert_not_called()
    assert "repeat_safe" in capsys.readouterr().err


def test_manual_auth_cannot_silently_run_headless(tmp_path, monkeypatch, capsys):
    path = tmp_path / "test.md"
    path.write_text("---\nurl: http://localhost:3000\n---\n1. Observe\n")
    run = Mock()
    monkeypatch.setattr(runner, "run", run)
    assert cli.main(["run", str(path), "--manual-auth", "--headless", "--profile", str(tmp_path / "profile")]) == 4
    run.assert_not_called()
    assert "visible Chrome" in capsys.readouterr().err
