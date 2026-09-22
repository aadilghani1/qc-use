"""Provider failures stop before input and leave bounded, redacted evidence."""

import json
import threading
import time
from unittest.mock import Mock

import httpx
import pytest

from qc_use import judge, runner
from qc_use.engine import model, requests
from qc_use.engine.errors import ProviderUnavailable
from qc_use.secrets import Redactor
from qc_use.spec import Step, TestSpec


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(requests.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(requests.time, "sleep", lambda seconds: now.__setitem__(0, now[0] + seconds))
    monkeypatch.setattr(requests.random, "uniform", lambda low, high: high)
    return now


@pytest.fixture
def meter():
    value = model.Meter()
    model.configure(meter=value, redact=Redactor({"PASSWORD": "private-value"}))
    yield value
    model.configure()


@pytest.mark.parametrize("status", [429, 502, 503, 504, 529])
def test_burst_recovers_after_more_than_three_attempts(monkeypatch, clock, meter, status):
    post = Mock(side_effect=[httpx.Response(status)] * 4 + [httpx.Response(200, json={"usage": {"cost": 0}})])
    monkeypatch.setattr(model.CLIENT, "post", post)
    model.post_json("https://example.test", "key", {}, purpose="action")
    assert post.call_count == 5 and clock[0] == 7.5
    assert [r["retry_seconds"] for r in meter.requests] == [0.5, 1, 2, 4, 0]
    assert all(r["purpose"] == "action" for r in meter.requests)


def test_outage_stops_at_deadline_and_latches_later_requests(monkeypatch, clock, meter):
    post = Mock(return_value=httpx.Response(503))
    monkeypatch.setattr(model.CLIENT, "post", post)
    with pytest.raises(ProviderUnavailable):
        model.post_json("https://example.test", "key", {})
    count = post.call_count
    assert count > 3 and clock[0] <= 45
    with pytest.raises(ProviderUnavailable):
        model.post_json("https://example.test", "key", {}, purpose="ratings")
    assert post.call_count == count


@pytest.mark.parametrize("value", ["120", "Tue, 22 Sep 2099 15:00:00 GMT"])
def test_retry_after_beyond_deadline_stops_without_early_retry(monkeypatch, clock, meter, value):
    post = Mock(return_value=httpx.Response(429, headers={"Retry-After": value}))
    monkeypatch.setattr(model.CLIENT, "post", post)
    with pytest.raises(ProviderUnavailable):
        model.post_json("https://example.test", "key", {})
    assert post.call_count == 1 and clock[0] == 0


@pytest.mark.parametrize("status", [400, 401, 403, 404, 422])
def test_permanent_errors_do_not_retry(monkeypatch, clock, meter, status):
    post = Mock(return_value=httpx.Response(status))
    monkeypatch.setattr(model.CLIENT, "post", post)
    with pytest.raises(RuntimeError, match=f"HTTP {status}"):
        model.post_json("https://example.test", "key", {})
    assert post.call_count == 1 and meter.unavailable is None


def test_trace_keeps_only_redacted_provider_diagnostics(monkeypatch, clock, meter):
    error = {
        "error": {
            "message": "private-value credential-key",
            "metadata": {"provider_name": "typesafe-ai"},
            "type": "service_unavailable_error",
            "secret_body": "never store this",
        }
    }
    post = Mock(
        side_effect=[
            httpx.Response(503, json=error, headers={"x-vercel-id": "region::request"}),
            httpx.Response(200, json={"usage": {"cost": 0}}),
        ]
    )
    monkeypatch.setattr(model.CLIENT, "post", post)
    model.post_json("https://example.test", "credential-key", {}, purpose="preflight")
    diagnostic = meter.requests[0]["error"]
    assert diagnostic["provider_name"] == "typesafe-ai" and diagnostic["x-vercel-id"] == "region::request"
    saved = json.dumps(meter.requests)
    assert all(value not in saved for value in ["private-value", "credential-key", "never store this"])


def test_stalled_transport_cannot_return_a_late_answer(monkeypatch, meter):
    release = threading.Event()
    finished = threading.Event()

    def stalled(*args, **kwargs):
        release.wait(2)
        finished.set()
        return httpx.Response(200, json={"usage": {"cost": 0}})

    monkeypatch.setattr(model.CLIENT, "post", stalled)
    monkeypatch.setattr(requests, "RETRY_SECONDS", 0.03)
    started = time.monotonic()
    try:
        with pytest.raises(ProviderUnavailable):
            model.post_json("https://example.test", "key", {})
        assert time.monotonic() - started < 1
        assert meter.unpriced == 1 and meter.requests[0]["status"] == "deadline_exceeded"
    finally:
        release.set()
        assert finished.wait(1)
    assert meter.calls == 0


def test_preflight_outage_writes_report_without_starting_chrome(monkeypatch, tmp_path, clock):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "key")
    monkeypatch.setattr(model.CLIENT, "post", Mock(return_value=httpx.Response(503)))
    chrome = Mock()
    monkeypatch.setattr(runner, "Chrome", chrome)
    spec = TestSpec(title="Fixture", url="http://localhost:3000", steps=[Step(text="Sign in"), Step(text="Continue")])
    report = runner.run(spec, results_dir=tmp_path, echo=lambda *_: None)
    chrome.assert_not_called()
    assert report.outcome == "blocked" and report.exit_code == 2
    assert report.provider_issue.kind == "provider_unavailable"
    assert [s.outcome for s in report.steps] == ["blocked", "skipped"]
    trace = json.loads((tmp_path / report.run_id / "trace.json").read_text())
    assert all(r["purpose"] == "preflight" for r in trace["model_requests"])


@pytest.mark.parametrize("answer", [None, {"noul": "yes"}])
def test_preflight_requires_a_valid_readiness_answer(monkeypatch, answer):
    monkeypatch.setattr(judge, "ask", Mock(return_value=({"ready": answer}, 1)))
    with pytest.raises(ValueError):
        judge.preflight()


def test_response_after_deadline_is_unpriced_and_not_used(monkeypatch, clock, meter):
    def late(*args, **kwargs):
        clock[0] = 46
        return httpx.Response(200, json={"usage": {"cost": 0.01}})

    monkeypatch.setattr(model.CLIENT, "post", late)
    with pytest.raises(ProviderUnavailable):
        model.post_json("https://example.test", "key", {})
    assert meter.unpriced == 1 and meter.calls == 0


def test_preflight_checks_response_contract_not_model_confidence(monkeypatch):
    monkeypatch.setattr(judge, "ask", Mock(return_value=({"ready": {"noul": 0.1}}, 1)))
    judge.preflight()


@pytest.mark.parametrize("error", [httpx.ReadTimeout("lost"), httpx.WriteError("partial"), httpx.ReadError("lost")])
def test_uncertain_sent_request_stops_with_unknown_pricing(monkeypatch, meter, error):
    post = Mock(side_effect=error)
    monkeypatch.setattr(model.CLIENT, "post", post)
    with pytest.raises(ProviderUnavailable, match="cost unknown"):
        model.post_json("https://example.test", "key", {})
    assert meter.unpriced == 1 and meter.requests[0]["pricing"]["status"] == "unavailable"
    with pytest.raises(ProviderUnavailable):
        model.post_json("https://example.test", "key", {})
    assert post.call_count == 1


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_rejected_request_keeps_its_status_and_is_not_retried(monkeypatch, clock, meter, status):
    post = Mock(return_value=httpx.Response(status))
    monkeypatch.setattr(model.CLIENT, "post", post)
    with pytest.raises(model.ProviderRejected) as error:
        model.post_json("https://example.test", "key", {})
    assert error.value.status == status and post.call_count == 1


@pytest.mark.parametrize(("status", "setup"), [(401, True), (403, True), (500, False)])
def test_rejected_key_at_preflight_is_a_setup_error(monkeypatch, tmp_path, status, setup):
    spec = TestSpec(title="T", url="http://localhost:3000", steps=[Step(text="Save", expect=["Saved"])])
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "revoked")
    monkeypatch.setattr(judge, "preflight", Mock(side_effect=model.ProviderRejected("rejected", status)))
    chrome = Mock()
    monkeypatch.setattr(runner, "Chrome", chrome)
    if setup:
        with pytest.raises(runner.SetupError, match=f"HTTP {status}"):
            runner.run(spec, results_dir=tmp_path, echo=lambda *_: None)
        assert list(tmp_path.iterdir()) == []
    else:
        assert runner.run(spec, results_dir=tmp_path, echo=lambda *_: None).exit_code == 2
    chrome.assert_not_called()
