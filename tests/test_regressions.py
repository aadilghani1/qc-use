"""Regression checks for secret boundaries, provider contracts, and complete run outcomes."""

import base64
import io
import json
import os
from unittest.mock import Mock

import pytest
from PIL import Image

from qc_use import capture, cli, judge, runner
from qc_use.engine import browser, model
from qc_use.engine.errors import Blocked, StalePage
from qc_use.guards import Guardrails, looks_like_production
from qc_use.report import StepResult
from qc_use.secrets import Redactor, environment
from qc_use.spec import Rating, SpecError, Step, TestSpec, load
from qc_use.watch import Watch


@pytest.fixture
def spec():
    return TestSpec(title="Review", url="http://localhost:3000", steps=[Step(text="Save", expect=["Saved"])])


@pytest.mark.parametrize("secret", ['quoted"password', "back\\slash", "new\nline", "私の秘密", "123"])
def test_text_helper_redacts_before_json_encoding(monkeypatch, secret):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "fake")
    response = Mock(status_code=200, is_error=False)
    response.json.return_value = {"choices": [{"message": {"content": '{"text":"safe"}'}}]}
    post = Mock(return_value=response)
    monkeypatch.setattr(model.CLIENT, "post", post)
    model.configure(redact=Redactor({"PASSWORD": secret}))
    try:
        model.field_text({"page": secret})
        content = post.call_args.kwargs["json"]["messages"][1]["content"]
        assert json.loads(content)["page"] == "[secret:PASSWORD]"
    finally:
        model.configure()


@pytest.mark.parametrize("base", ["https://ai-gateway.vercel.sh.evil.test/v1", "http://ai-gateway.vercel.sh/v1"])
def test_gateway_key_requires_exact_https_origin(monkeypatch, base):
    monkeypatch.delenv("TEXT_MODEL_API_KEY", raising=False)
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "fake")
    assert model.text_key(base) is None


def test_generic_text_provider_gets_no_vendor_reasoning_fields(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "fake")
    monkeypatch.delenv("TEXT_MODEL_REASONING", raising=False)
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"safe"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    model.field_text({})
    assert not {"reasoning", "thinking", "reasoning_effort"} & post.call_args.args[2].keys()


@pytest.mark.parametrize("result", [{}, [], {"model": "jev", "answers": None}])
def test_jev_envelope_rejects_malformed_answers(result):
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.jev_response(result)


@pytest.mark.parametrize(
    "score,probabilities",
    [(float("nan"), {"0": 0.0, "1": 1.0}), (0.0, {"0": 0.0, "1": 0.0}), (1.0, {"0": 1.0, "1": 0.0})],
)
def test_score_requires_valid_distribution_and_weighted_value(monkeypatch, score, probabilities):
    monkeypatch.setattr(
        judge,
        "ask",
        Mock(return_value=({"ease": {"score": score, "probabilities": probabilities, "confidence": 1.0}}, 0)),
    )
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        judge.ratings({}, {"ease": Rating(levels=["bad", "good"])})


@pytest.mark.parametrize(
    "front",
    [
        "files: [avatar.png]",
        "files: {avatar: 1}",
        "rate: [ease]",
        "intent: duplicate",
        "steps: []",
        "url: http://localhost:wrong",
    ],
)
def test_malformed_settings_name_the_file(tmp_path, front):
    path = tmp_path / "bad.md"
    path.write_text(f"---\nurl: http://localhost:3000\n{front}\n---\n1. Run\n")
    with pytest.raises(SpecError, match=r"bad\.md"):
        load(path)


def test_each_command_restores_file_environment(tmp_path, monkeypatch):
    monkeypatch.delenv("LOGIN_PASSWORD", raising=False)
    for name in ("first", "second"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / ".env").write_text(f"LOGIN_PASSWORD={name}")
        with environment(folder):
            assert os.environ["LOGIN_PASSWORD"] == name
    assert "LOGIN_PASSWORD" not in os.environ


def test_cli_isolates_environment_between_files(tmp_path, monkeypatch, spec):
    seen = []
    for name in ("first", "second"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / ".env").write_text(f"LOGIN_PASSWORD={name}")
        (folder / "test.md").write_text("---\nurl: http://localhost:3000\n---\n1. Observe\n")
    monkeypatch.delenv("LOGIN_PASSWORD", raising=False)

    def run(*args, **kwargs):
        seen.append(os.environ["LOGIN_PASSWORD"])
        raise runner.SetupError("test stop")

    monkeypatch.setattr(runner, "run", run)
    assert cli.main(["run", *[str(tmp_path / n / "test.md") for n in ("first", "second")]]) == 4
    assert seen == ["first", "second"]
    assert "LOGIN_PASSWORD" not in os.environ


def test_gate_does_not_reuse_same_label_on_different_targets(spec, monkeypatch):
    guard = Guardrails(spec)
    gate = Mock(side_effect=[{guard.rules[0]: 0.01}, {guard.rules[0]: 0.99}])
    monkeypatch.setattr(judge, "gate", gate)
    guard.before_act({"node": 1, "label": "Confirm", "kind": "click"}, {"url": spec.url}, {})
    from qc_use.engine.errors import NeedsApproval

    with pytest.raises(NeedsApproval):
        guard.before_act({"node": 2, "label": "Confirm", "kind": "click"}, {"url": spec.url}, {})
    assert gate.call_count == 2


@pytest.mark.parametrize("url,tabs", [("https://outside.test", []), ("http://localhost:3000", ["https://popup.test"])])
def test_verify_blocks_outside_sites_and_popups_before_judging(spec, monkeypatch, url, tabs):
    b = Mock(observe=Mock(return_value={"url": url}), new_tabs=Mock(return_value=tabs))
    expectations = Mock()
    monkeypatch.setattr(judge, "expectations", expectations)
    with pytest.raises(Blocked):
        runner.verify(spec, spec.steps[0], b, "goal")
    expectations.assert_not_called()


def test_public_dev_suffix_is_not_a_staging_signal():
    assert looks_like_production("https://myapp.dev")
    assert not looks_like_production("https://staging.myapp.dev")


@pytest.fixture
def fake_run(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "fake")
    monkeypatch.setattr(runner, "Chrome", Mock())
    monkeypatch.setattr(runner, "connect", Mock())
    monkeypatch.setattr(runner, "disconnect", Mock())
    b = Mock(observe=Mock(return_value={"url": "http://localhost:3000"}))
    monkeypatch.setattr(browser, "Browser", Mock(return_value=b))
    monkeypatch.setattr(
        runner, "run_step", Mock(return_value=(StepResult(index=1, text="Save", outcome="pass"), None, {}, {}))
    )
    return b


def test_missing_required_rating_is_inconclusive_even_without_actions(spec, fake_run, tmp_path, monkeypatch):
    spec.rate = {"ease": Rating(levels=["bad", "good"], min="good")}
    monkeypatch.setattr(runner, "rate", Mock(side_effect=ValueError("bad score")))
    report = runner.run(spec, results_dir=tmp_path, screenshots=False, echo=lambda *_: None)
    assert report.outcome == "inconclusive" and report.exit_code == 2
    assert "required rating" in report.steps[-1].reason


@pytest.mark.parametrize("error", [StalePage("changed"), TimeoutError("timeout")])
def test_startup_failure_still_writes_a_report(spec, fake_run, tmp_path, error):
    fake_run.observe.side_effect = error
    report = runner.run(spec, results_dir=tmp_path, screenshots=False, echo=lambda *_: None)
    assert report.outcome == "blocked"
    assert (tmp_path / report.run_id / "report.json").is_file()


def test_cleanup_failure_preserves_results(spec, fake_run, tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "disconnect", Mock(side_effect=RuntimeError("cleanup")))
    report = runner.run(spec, results_dir=tmp_path, screenshots=False, echo=lambda *_: None)
    assert report.steps[0].text == "Save" and report.outcome == "blocked"
    assert (tmp_path / report.run_id / "report.json").is_file()


def test_unpriced_requests_stop_at_next_call():
    meter = model.Meter(0.25)
    meter.charge({"usage": {"prompt_tokens": 1000, "completion_tokens": 10}})
    with pytest.raises(model.BudgetExceeded, match="unknown"):
        meter.check()


@pytest.mark.parametrize("cost", [-1, float("nan"), float("inf"), True, "bad"])
def test_invalid_cost_does_not_reduce_spend(cost):
    meter = model.Meter(0.25)
    meter.charge({"usage": {"cost": cost}})
    assert meter.usd == 0 and meter.unpriced == 1


def test_only_direct_jev_uses_jev_token_estimate():
    unknown, jev = model.Meter(), model.Meter()
    unknown.charge({"usage": {"input_tokens": 1000}})
    jev.charge({"usage": {"input_tokens": 1000}}, direct_jev=True)
    assert unknown.unpriced == 1 and unknown.usd == 0
    assert jev.estimated and jev.usd > 0


def test_watch_redacts_decisions_and_reasons(spec):
    watch = Watch(spec)
    watch.redact = Redactor({"PASSWORD": "fake-password"})
    watch.record(StepResult(index=1, text="Save", outcome="blocked", reason="fake-password"))
    assert watch.state["steps"][0]["reason"] == "[secret:PASSWORD]"
    state = {
        "decisions": [
            {
                "request": {"questions": {"click_target": {"criteria": {"1": {"element": "fake-password"}}}}},
                "operation": "CLICK",
                "confidence": 1,
                "latency_ms": 1,
                "operation_probabilities": {"CLICK": 1},
                "target_probabilities": {"1": 1},
            }
        ],
        "page": {},
        "history": [],
    }
    watch(0, state)
    assert "fake-password" not in json.dumps(watch.state)


@pytest.mark.parametrize("after", [None, {"rects": [], "state": "changed"}])
def test_changed_or_unsupported_screenshot_is_omitted(after):
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10)).save(buffer, "JPEG")
    b = Mock(
        evaluate=Mock(side_effect=[{"rects": [], "state": "before"}, after]),
        call=Mock(return_value={"data": base64.b64encode(buffer.getvalue()).decode()}),
    )
    assert capture.masked(b, "old-image", {"PIN": "123"}) is None


def test_unsupported_screenshot_never_captures():
    b = Mock(evaluate=Mock(return_value=None))
    assert capture.masked(b, None, {"PIN": "123"}) is None
    b.call.assert_not_called()


def test_short_secret_stops_before_chrome(spec, monkeypatch):
    spec.secrets = ["PIN"]
    monkeypatch.setenv("PIN", "123")
    chrome = Mock()
    monkeypatch.setattr(runner, "Chrome", chrome)
    with pytest.raises(runner.SetupError, match="at least 4"):
        runner.run(spec)
    chrome.assert_not_called()


def test_secret_matching_outcome_does_not_corrupt_report(spec, fake_run, tmp_path, monkeypatch):
    spec.secrets = ["PASSWORD"]
    monkeypatch.setenv("PASSWORD", "pass")
    report = runner.run(spec, results_dir=tmp_path, screenshots=False, echo=lambda *_: None)
    assert report.outcome == "pass"
    assert report.summary == "All 1 steps [secret:PASSWORD]ed."


def test_redaction_preserves_protocol_field_names():
    assert Redactor({"PASSWORD": "text"})({"text": "text"}) == {"text": "[secret:PASSWORD]"}


def test_interrupt_preserves_report_and_exit_code(spec, fake_run, tmp_path):
    fake_run.observe.side_effect = KeyboardInterrupt()
    report = runner.run(spec, results_dir=tmp_path, screenshots=False, echo=lambda *_: None)
    assert report.exit_code == 130 and report.outcome == "blocked"
    assert (tmp_path / report.run_id / "report.json").is_file()


@pytest.mark.parametrize(
    "host,status", [("127.0.0.1:4318", 200), ("127.0.0.1.evil.test:4318", 403), ("127.0.0.1:9999", 403)]
)
def test_watch_requires_exact_host_and_redacts_responses(spec, host, status):
    from types import SimpleNamespace

    watch = Watch(spec)
    watch.server = SimpleNamespace(server_port=4318)
    watch.redact = Redactor({"PASSWORD": "fake-password"})
    watch.state["summary"] = "fake-password"
    request = Mock()
    request.makefile.return_value = io.BytesIO(
        f"GET /api/state?t={watch.token} HTTP/1.1\r\nHost: {host}\r\n\r\n".encode()
    )
    watch.handler()(request, ("127.0.0.1", 123), watch.server)
    output = b"".join(c.args[0] for c in request.sendall.call_args_list)
    assert f" {status} ".encode() in output
    assert b"fake-password" not in output
    if status == 200:
        assert b"[secret:PASSWORD]" in output


def test_watch_finish_closes_server(spec):
    watch = Watch(spec)
    watch.server = Mock()
    watch.final_seen.set()
    watch.finish()
    watch.server.shutdown.assert_called_once()
    watch.server.server_close.assert_called_once()


def test_watch_final_steps_match_report_after_rating_failure(spec):
    watch = Watch(spec)
    watch.final_seen.set()
    watch.record(StepResult(index=1, text="Save", outcome="pass"))
    report = Mock(
        outcome="inconclusive",
        summary="Required rating unavailable.",
        steps=[StepResult(index=1, text="Save", outcome="inconclusive", reason="Required rating unavailable.")],
    )
    watch.finish(report)
    assert watch.state["status"] == "inconclusive"
    assert watch.state["steps"][0]["outcome"] == "inconclusive"
    assert watch.state["steps"][0]["reason"] == report.summary


@pytest.mark.parametrize("kind", ["fill", "upload"])
def test_fill_and_upload_gate_runs_before_input(spec, monkeypatch, kind):
    guard = Guardrails(spec)
    gate = Mock(return_value={guard.rules[0]: 0.99})
    monkeypatch.setattr(judge, "gate", gate)
    from qc_use.engine.errors import NeedsApproval

    with pytest.raises(NeedsApproval):
        guard.before_act({"node": 1, "kind": kind, "label": "Account"}, {"url": spec.url}, {})
    gate.assert_called_once()


@pytest.mark.parametrize("setup_error", [False, True])
def test_cli_masks_headers_setup_errors_and_repeat_summaries(
    spec, fake_run, monkeypatch, tmp_path, capsys, setup_error
):
    spec.repeat_safe = True
    secret = "private-review-password"
    monkeypatch.setenv("PASSWORD", secret)
    spec.secrets = ["PASSWORD"]
    spec.title = f"Run {secret}"
    spec.url = f"http://localhost:3000/?token={secret}"
    spec.path = tmp_path / "test.md"
    monkeypatch.setattr("qc_use.spec.load", Mock(return_value=spec))
    if setup_error:
        monkeypatch.setattr(runner, "run", Mock(side_effect=runner.SetupError(f"Refused {spec.url}")))
    code = cli.main(["run", str(spec.path), "--repeat", "2", "--results", str(tmp_path)])
    captured = capsys.readouterr()
    assert code == (4 if setup_error else 0)
    assert secret not in captured.out + captured.err
    assert "[secret:PASSWORD]" in captured.out
    if setup_error:
        assert "[secret:PASSWORD]" in captured.err
    else:
        assert "Pass rate for Run [secret:PASSWORD]: 2/2" in captured.out


def test_manual_auth_finishes_before_observation(spec, fake_run, tmp_path):
    def handoff():
        fake_run.observe.assert_not_called()
        fake_run.call.assert_called_once_with("Page.bringToFront")

    report = runner.run(spec, results_dir=tmp_path, screenshots=False, echo=lambda *_: None, manual_auth=handoff)
    assert report.outcome == "pass"
    fake_run.observe.assert_called_once()


def test_manual_auth_eof_writes_blocked_report(spec, fake_run, tmp_path):
    report = runner.run(
        spec, results_dir=tmp_path, screenshots=False, echo=lambda *_: None, manual_auth=Mock(side_effect=EOFError)
    )
    assert report.outcome == "blocked" and "Manual sign-in cancelled" in report.steps[0].reason
    assert (tmp_path / report.run_id / "report.json").is_file()
    fake_run.observe.assert_not_called()


@pytest.mark.parametrize("answer", [None, [], "invalid"])
def test_malformed_selected_answer_cannot_execute(answer):
    response = model.jev_response({"model": "jev", "answers": {"operation": answer}})
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.validate_choice(response["answers"]["operation"], {"CLICK"})


def test_private_browser_activates_its_capture_surface(monkeypatch):
    monkeypatch.setattr(browser, "ensure_daemon", Mock())
    calls = Mock(
        side_effect=lambda method, **_: {
            "Target.createTarget": {"targetId": "owned"},
            "Target.attachToTarget": {"sessionId": "session"},
            "Runtime.evaluate": {"result": {"value": "complete"}},
        }.get(method, {})
    )
    monkeypatch.setattr(browser, "cdp", calls)
    instance = browser.Browser("http://localhost:3000")
    assert instance.target == "owned"
    assert calls.call_args_list[0].kwargs == {"url": "about:blank", "background": False}
