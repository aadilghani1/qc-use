"""Offline contracts for the operation/target policy and the step executor. No paid APIs, no browser."""

import json
import time
from copy import deepcopy
from unittest.mock import Mock

import pytest

from qc_use.engine import agent as loop
from qc_use.engine import model
from qc_use.engine.agent import Agent, Blocked, NeedsApproval, Policy
from qc_use.engine.browser import StalePage, browser_operation, fingerprint


@pytest.fixture(autouse=True)
def default_providers(monkeypatch):
    for name in (
        "JEV_PROVIDER",
        "TYPESAFE_MODEL",
        "AI_GATEWAY_API_KEY",
        "VERCEL_OIDC_TOKEN",
        "TEXT_MODEL_BASE_URL",
        "TEXT_MODEL",
        "TEXT_MODEL_API_KEY",
        "TEXT_MODEL_REASONING",
        "TYPESAFE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)
    model.configure()


def page():
    state = {
        "url": "https://example.test/",
        "title": "Search",
        "text": "Search",
        "scroll": {"y": 0},
        "actions": [
            {"id": "e1", "kind": "fill", "label": "Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e2", "kind": "click", "label": "Open Search", "role": "textbox", "value": "", "node": 10},
            {"id": "e3", "kind": "click", "label": "Go", "role": "button", "value": "", "node": 20},
            {"id": "wait", "kind": "wait", "label": "Wait"},
        ],
    }
    state["fingerprint"] = fingerprint(state)
    return state


def login_page():
    state = page()
    state["actions"] = [
        {"id": "e1", "kind": "fill", "label": "Email", "role": "textbox", "value": "", "node": 1},
        {"id": "e2", "kind": "fill", "label": "Password", "role": "textbox", "value": "", "node": 2, "password": True},
        {"id": "e3", "kind": "upload", "label": "Avatar", "role": "file", "value": "", "node": 3},
        {"id": "e4", "kind": "click", "label": "Sign in", "role": "button", "value": "", "node": 4},
    ]
    state["fingerprint"] = fingerprint(state)
    return state


def choice(ids, selected):
    return {"choice": selected, "confidence": 1.0, "probabilities": {i: float(i == selected) for i in ids}}


def decision(action="e1", **extra):
    return {
        "choice": action,
        "operation": "TYPE_TEXT",
        "target": "1",
        "confidence": 1.0,
        "probabilities": {action: 1.0},
        "latency_ms": 10,
        "usage": {},
        **extra,
    }


@pytest.mark.parametrize("mutation", ["unknown", "nan", "missing", "negative", "non_max", "confidence", "boolean"])
def test_invalid_choice_is_rejected(mutation):
    a = choice(["a", "b"], "a")
    if mutation == "unknown":
        a["choice"] = "invented"
    elif mutation == "nan":
        a["probabilities"]["a"] = float("nan")
    elif mutation == "missing":
        del a["probabilities"]["b"]
    elif mutation == "negative":
        a["probabilities"]["b"] = -1
    elif mutation == "non_max":
        a["choice"] = "b"
    elif mutation == "boolean":
        a["probabilities"]["a"] = True
    else:
        a["confidence"] = 5
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.validate_choice(a, {"a", "b"})


def test_one_index_per_node_with_operation_specific_targets():
    elements, targets, controls = model.action_space(page()["actions"])
    assert len(elements) == 2
    assert elements[0]["operations"] == ["TYPE_TEXT", "CLICK"]
    assert targets["TYPE_TEXT"]["1"]["id"] == "e1"
    assert targets["CLICK"]["1"]["id"] == "e2"
    assert targets["CLICK"]["2"]["id"] == "e3"
    assert "WAIT" in controls


def test_password_fields_accept_only_declared_secrets():
    _, targets, _ = model.action_space(login_page()["actions"], secrets=("LOGIN_EMAIL", "LOGIN_PASSWORD"))
    text = targets["TYPE_TEXT"]
    assert {"1", "1:LOGIN_EMAIL", "1:LOGIN_PASSWORD"} <= set(text)
    assert "2" not in text  # No helper-written text can go into a password field.
    assert text["2:LOGIN_PASSWORD"]["secret"] == "LOGIN_PASSWORD"
    _, without, _ = model.action_space(login_page()["actions"])
    assert not any(t.startswith("2") for t in without["TYPE_TEXT"])


def test_uploads_are_offered_only_for_declared_files():
    _, targets, _ = model.action_space(login_page()["actions"], files=("avatar",))
    ((target, action),) = targets["UPLOAD"].items()
    assert target.endswith(":avatar") and action["id"] == "e3" and action["file"] == "avatar"
    _, none, _ = model.action_space(login_page()["actions"])
    assert "UPLOAD" not in none


def test_secret_values_never_appear_in_the_decision_request(monkeypatch):
    sent = []

    def post(_url, _key, body):
        sent.append(json.dumps(body))
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(body["questions"]["type_text_target"]["criteria"], "2:LOGIN_PASSWORD"),
            },
        }

    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gateway")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(login_page(), "Sign in", [], secrets=("LOGIN_EMAIL", "LOGIN_PASSWORD"))
    assert d["choice"] == "e2" and d["secret"] == "LOGIN_PASSWORD"
    assert "hunter2" not in sent[0] and "LOGIN_PASSWORD" in sent[0]


def test_all_heads_are_one_request_and_only_matching_head_executes(monkeypatch):
    calls = []

    def post(_url, _key, body):
        calls.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "TYPE_TEXT"),
                "type_text_target": choice(["1"], "1"),
                "click_target": {"choice": "invented"},
            },
        }

    monkeypatch.setenv("TYPESAFE_API_KEY", "test")
    monkeypatch.setenv("JEV_PROVIDER", "typesafe")
    monkeypatch.setattr(model, "post_json", post)
    d = model.choose(page(), "Find a book", [])
    assert len(calls) == 1
    assert d["operation"] == "TYPE_TEXT" and d["target"] == "1" and d["choice"] == "e1"
    assert set(calls[0]["questions"]) == {"operation", "click_target", "type_text_target"}


def test_click_cannot_consume_a_text_target(monkeypatch):
    def post(_url, _key, body):
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "type_text_target": choice(["1"], "1"),
                "click_target": choice(["1", "2", "999"], "999"),
            },
        }

    monkeypatch.setenv("AI_GATEWAY_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="Invalid TypeSafe"):
        model.choose(page(), "Find a book", [])


def test_gateway_is_the_default_jev_route(monkeypatch):
    calls = []

    def post(url, key, body):
        calls.append((url, key, body["model"]))
        return {
            "model": body["model"],
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "click_target": choice(body["questions"]["click_target"]["criteria"], "2"),
            },
        }

    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gateway")
    monkeypatch.setattr(model, "post_json", post)
    assert model.choose(page(), "Find a book", [])["choice"] == "e3"
    assert calls == [("https://ai-gateway.vercel.sh/typesafe/v1/systemone", "gateway", "typesafe-ai/jev")]


@pytest.mark.parametrize("provider", ["typesafe", "gateway"])
def test_missing_jev_credential_stops_before_any_request(monkeypatch, provider):
    monkeypatch.setenv("JEV_PROVIDER", provider)
    post = Mock()
    monkeypatch.setattr(model, "post_json", post)
    with pytest.raises(ValueError, match="TYPESAFE_API_KEY" if provider == "typesafe" else "AI_GATEWAY_API_KEY"):
        model.choose(page(), "Find a book", [])
    post.assert_not_called()


def test_every_request_is_redacted_and_metered(monkeypatch):
    seen = {}

    class Response:
        status_code, is_error = 200, False

        def json(self):
            return {"usage": {"cost": 0.002}}

    def send(_url, json, headers):
        seen["body"] = json
        return Response()

    monkeypatch.setattr(model.CLIENT, "post", send)
    meter = model.Meter(limit=0.001)
    model.configure(redact=lambda body: {"text": body["text"].replace("hunter2", "[secret:PW]")}, meter=meter)
    model.post_json("https://example.test", "key", {"text": "password hunter2"})
    assert seen["body"] == {"text": "password [secret:PW]"} and meter.usd == 0.002
    with pytest.raises(model.BudgetExceeded):
        model.post_json("https://example.test", "key", {"text": "x"})


def test_text_helper_defaults_to_mercury_on_the_gateway(monkeypatch):
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gateway")
    post = Mock(return_value={"choices": [{"message": {"content": '{"text":"Zurich","source":"goal"}'}}]})
    monkeypatch.setattr(model, "post_json", post)
    assert model.field_text({"goal": "Fly from Zurich"})[0] == "Zurich"
    url, key, body = post.call_args.args
    assert url == "https://ai-gateway.vercel.sh/v1/chat/completions" and key == "gateway"
    assert body["model"] == "inception/mercury-2.5" and body["reasoning"] == {"enabled": False}


@pytest.mark.parametrize(
    "content",
    [
        "Thinking: Zurich",
        '{"text":null}',
        '{"text":"Zurich","extra":true}',
        '{"text":123}',
        '{"text":"  "}',
        '{"text":"Zurich","source":"invented"}',
    ],
)
def test_text_helper_rejects_invalid_values(monkeypatch, content):
    monkeypatch.setenv("TEXT_MODEL_API_KEY", "test")
    monkeypatch.setattr(model, "post_json", Mock(return_value={"choices": [{"message": {"content": content}}]}))
    with pytest.raises(ValueError, match="nothing typed"):
        model.field_text({"goal": "Find a flight"})


def test_missing_text_credential_stops_before_guessing(monkeypatch):
    monkeypatch.setenv("TEXT_MODEL_BASE_URL", "https://api.example.test/v1")
    with pytest.raises(ValueError, match="TEXT_MODEL_API_KEY"):
        model.field_text({"goal": 'Enter "Zurich"'})


def make_agent(p=None, **options):
    p = p or page()
    browser = Mock(
        fresh=Mock(return_value=True),
        observe=Mock(return_value=p),
        signals=Mock(return_value=[]),
        new_tabs=Mock(return_value=[]),
    )
    a = Agent(browser, "Find a book", page=p, history=[], **options)
    a.state["started_at"] = time.perf_counter()
    return a


def test_stale_decision_is_consumed_before_any_mutation():
    a = make_agent()
    a.browser.fresh.return_value = False
    a.state["decision"] = decision()
    with pytest.raises(StalePage):
        a.act()
    a.browser.act.assert_not_called()
    assert a.state["decision"] is None


def test_secrets_are_typed_by_code_and_recorded_masked(monkeypatch):
    helper = Mock()
    monkeypatch.setattr(loop, "field_text", helper)
    a = make_agent(login_page(), secrets={"LOGIN_PASSWORD": "hunter2"})
    a.state["decision"] = decision("e2", secret="LOGIN_PASSWORD")
    a.act()
    helper.assert_not_called()
    assert a.browser.act.call_args.kwargs["text"] == "hunter2"
    assert a.state["history"][-1]["text"] == "[secret:LOGIN_PASSWORD]"


def test_uploads_use_the_declared_fixture_path():
    a = make_agent(login_page(), files={"avatar": "/fixtures/avatar.png"})
    a.state["decision"] = decision("e3", operation="UPLOAD", file="avatar")
    a.act()
    assert a.browser.act.call_args.kwargs["text"] == "/fixtures/avatar.png"
    assert a.state["history"][-1]["text"] == "[file:avatar]"


def test_guardrails_run_before_any_input():
    class Refuse(Policy):
        def before_act(self, action, page, decision):
            raise NeedsApproval("delete data", action["label"], 0.9)

    a = make_agent(policy=Refuse())
    a.state["decision"] = decision("e3")
    with pytest.raises(NeedsApproval):
        a.act()
    a.browser.act.assert_not_called()


def test_step_budget_blocks_before_another_action():
    a = make_agent(max_actions=1)
    a.state["history"].append({"page_changed": True, "kind": "click"})
    a.state["decision"] = decision("e3")
    with pytest.raises(Blocked, match="budget"):
        a.act()
    a.browser.act.assert_not_called()


def test_generated_text_reused_only_for_identical_retry_context(monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10, "source": "goal"}))
    monkeypatch.setattr(loop, "field_text", helper)
    a = make_agent()
    a.browser.act.side_effect = [StalePage("Changed before input"), None]
    a.state["decision"] = decision()
    with pytest.raises(StalePage):
        a.act()
    a.state["decision"] = decision()
    a.act()
    assert helper.call_count == 1
    assert a.browser.act.call_count == 2  # The first call rejects before any browser input.
    assert a.pending_text is None


def test_changed_field_context_does_not_reuse_generated_text(monkeypatch):
    helper = Mock(return_value=("book", {"model": "test", "latency_ms": 10, "source": "goal"}))
    monkeypatch.setattr(loop, "field_text", helper)
    a = make_agent()
    a.browser.act.side_effect = [StalePage("Changed before input"), None]
    a.state["decision"] = decision()
    with pytest.raises(StalePage):
        a.act()
    a.state["page"]["text"] = "Different page context"
    a.state["decision"] = decision()
    a.act()
    assert helper.call_count == 2


def test_text_helper_without_a_value_blocks_the_step(monkeypatch):
    monkeypatch.setattr(loop, "field_text", Mock(side_effect=ValueError("nothing typed")))
    a = make_agent()
    a.state["decision"] = decision()
    with pytest.raises(Blocked, match="no value"):
        a.act()
    a.browser.act.assert_not_called()


def test_loading_waits_do_not_trigger_no_progress_stop():
    a = make_agent()
    for _ in range(5):
        a.state["decision"] = decision("wait", operation="WAIT")
        a.act()
    assert len(a.state["history"]) == 5 and a.state["status"] == "ready"


def test_three_unchanged_actions_stop_the_step():
    a = make_agent()
    for _ in range(3):
        a.state["decision"] = decision("e3", operation="CLICK")
        a.act()
    assert a.state["status"] == "blocked"


def test_stale_observation_preserves_executed_action():
    a = make_agent()
    a.state["decision"] = decision("e3")
    a.browser.observe.side_effect = StalePage("changed")
    with pytest.raises(StalePage):
        a.act()
    assert a.state["history"][-1]["action"] == "Go"
    a.browser.act.assert_called_once()


def test_new_tab_blocks_after_the_action_is_recorded():
    a = make_agent()
    a.browser.new_tabs.return_value = ["https://accounts.example.test/oauth"]
    a.state["decision"] = decision("e3")
    with pytest.raises(Blocked, match="new tab"):
        a.act()
    assert a.state["history"][-1]["action"] == "Go"


def test_navigation_during_prediction_reobserves_without_action(monkeypatch):
    a = make_agent()
    a.browser.fresh.side_effect = StalePage("Document navigating")
    a.tick()
    assert a.state["status"] == "ready" and a.state["decision"] is None
    a.browser.act.assert_not_called()


def test_observation_is_one_atomic_browser_read(monkeypatch):
    import qc_use.engine.browser as browser

    p = page()
    cdp = Mock(return_value={"result": {"value": p}})
    monkeypatch.setattr(browser, "cdp", cdp)
    actual = browser_operation({"operation": "observe", "session": "test", "screenshot": False})
    assert actual["actions"] == p["actions"]
    assert cdp.call_count == 1
    assert cdp.call_args.args[0] == "Runtime.evaluate"


def test_executor_rejects_a_stale_page_before_browser_input(monkeypatch):
    import qc_use.engine.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.fresh = Mock(return_value=False)
    operation = Mock()
    monkeypatch.setattr(browser, "browser_operation", operation)
    with pytest.raises(StalePage):
        b.act(page()["actions"][0], page(), "book")
    operation.assert_not_called()


def test_dialog_opened_by_input_is_decided_while_the_input_waits(monkeypatch):
    import qc_use.engine.browser as browser

    b = browser.Browser.__new__(browser.Browser)
    b.dialogs, calls = [], []
    pending = [None, {"type": "confirm", "message": "Delete?", "url": "x"}]
    b.dialog = lambda: pending.pop() if pending else None
    b.call = lambda method, **params: calls.append((method, params))
    b.on_dialog = lambda record: (False, None)

    def blocked_input():
        while not calls:
            time.sleep(0.01)
        raise TimeoutError("input waited on the dialog")

    assert b.input(blocked_input) == {"dialog": True}
    assert calls == [("Page.handleJavaScriptDialog", {"accept": False})]
    assert b.dialogs == [{"type": "confirm", "message": "Delete?", "url": "x", "accepted": False}]


@pytest.mark.parametrize("response", [{"exceptionDetails": {}}, {"result": {}}])
def test_interrupted_dropdown_mutation_cannot_be_retried_as_stale(monkeypatch, response):
    import qc_use.engine.browser as browser

    if "exceptionDetails" in response:
        response["exceptionDetails"] = {"text": "Execution context destroyed"}
    cdp = Mock(return_value=response)
    monkeypatch.setattr(browser, "cdp", cdp)
    with pytest.raises(RuntimeError, match="Dropdown execution"):
        browser_operation(
            {
                "operation": "act",
                "session": "test",
                "action": {
                    "id": "e1",
                    "kind": "select",
                    "node": 1,
                    "value": "Design",
                },
            }
        )
    assert cdp.call_count == 1


def test_fingerprint_tracks_values_and_identity_not_screenshots():
    p = page()
    other = deepcopy(p)
    other["screenshot"] = "changed"
    assert fingerprint(p) == fingerprint(other)
    other["actions"][0]["node"] = 99
    assert fingerprint(p) != fingerprint(other)


def test_step_done_does_not_override_the_chosen_action(monkeypatch):
    sent = []

    def post(_url, _key, body):
        sent.append(body)
        return {
            "model": "test",
            "answers": {
                "operation": choice(body["questions"]["operation"]["criteria"], "CLICK"),
                "click_target": choice(body["questions"]["click_target"]["criteria"], "2"),
                "step_done": {"type": "noul", "noul": 0.97},
            },
        }

    monkeypatch.setenv("AI_GATEWAY_API_KEY", "gateway")
    monkeypatch.setattr(model, "post_json", post)
    a = make_agent(done_when=["the results are visible"])
    a.predict()
    assert len(sent) == 1 and "step_done" in sent[0]["questions"]
    a.act()
    assert a.state["status"] == "ready"
    a.browser.act.assert_called_once()


@pytest.mark.parametrize("exact_passes, expected", [(True, "done"), (False, "ready")])
@pytest.mark.parametrize("done_probability", [0.73, 0.99])
def test_completion_uses_independent_evidence_before_next_input(exact_passes, expected, done_probability):
    a = make_agent(completion_check=lambda page: exact_passes)
    a.state["history"].append({"action": "Save", "kind": "click", "page_changed": True})
    a.state["decision"] = decision("e3", operation="CLICK", done_probability=done_probability)
    a.act()
    assert a.state["status"] == expected
    if exact_passes:
        a.browser.act.assert_not_called()
    else:
        a.browser.act.assert_called_once()


def test_preexisting_checkpoint_does_not_skip_requested_action():
    check = Mock(return_value=True)
    a = make_agent(completion_check=check)
    a.state["decision"] = decision("e3", operation="CLICK", done_probability=0.99)
    a.act()
    check.assert_not_called()
    a.browser.act.assert_called_once()
