"""Run one goal on an existing page. Typed choices, observable state, bounded execution."""

import time
from collections.abc import Callable

from .contracts import BrowserPort, Page
from .errors import Blocked, NeedsApproval, StalePage
from .model import choose, field_context, field_text

__all__ = ["Agent", "Blocked", "NeedsApproval", "Policy", "StalePage"]


class Policy:
    """Guardrail hooks. They raise Blocked or NeedsApproval; the defaults allow everything."""

    def before_act(self, action, page, decision):
        pass

    def after_observe(self, page):
        pass


class Agent:
    def __init__(
        self,
        browser: BrowserPort,
        goal,
        *,
        page,
        history,
        max_actions=15,
        secrets=None,
        files=None,
        policy=None,
        screenshots=False,
        done_when=(),
        completion_check: Callable[[Page], bool] | None = None,
    ):
        self.browser = browser
        self.done_when = tuple(done_when)
        self.completion_check = completion_check
        self.secrets = secrets or {}  # name -> value. Values are typed by code and never sent to a model.
        self.files = files or {}  # name -> path of a declared fixture.
        self.policy = policy or Policy()
        self.screenshots = screenshots
        self.max_actions = max_actions
        self.pending_text: tuple | None = None
        self.before_action: Page | None = None  # The page before the last action, until a read after it succeeds.
        self.state = {
            "goal": goal,
            "page": page,
            "decision": None,
            "history": history,  # Shared across steps, so recent actions carry over.
            "first_action": len(history),
            "status": "ready",
            "decisions": [],
            "text_calls": [],
            "signals": [],
            "started_at": None,
            "elapsed_ms": 0,
        }

    def elapsed(self):
        return round((time.perf_counter() - self.state["started_at"]) * 1000)

    def observe(self):
        state = self.state
        state["page"] = self.browser.observe(screenshot=self.screenshots)
        state["signals"].extend(self.browser.signals())
        if tabs := self.browser.new_tabs():
            raise Blocked(f"unsupported: the page opened a new tab or window ({tabs[0]})")
        self.policy.after_observe(state["page"])

    def tick(self):
        state = self.state
        if state["started_at"] is None:
            state["started_at"] = time.perf_counter()
        try:
            self.predict()
            self.act()
        except StalePage:
            state["decision"] = None
            state["status"] = "ready"
            self.observe()
            self.settle_change()
        state["elapsed_ms"] = self.elapsed()
        return state

    def predict(self):
        state = self.state
        if not self.browser.fresh(state["page"]):
            self.observe()
        state["decision"] = None
        if len(state["decisions"]) >= self.max_actions * 2:
            raise Blocked(f"Reached this step's budget of {self.max_actions * 2} decisions")
        state["decision"] = choose(
            state["page"], state["goal"], state["history"], tuple(self.secrets), tuple(self.files), self.done_when
        )
        state["decisions"].append(
            {**state["decision"], "fingerprint": state["page"]["fingerprint"], "elapsed_ms": self.elapsed()}
        )
        state["status"] = "predicted"

    def act(self):
        state = self.state
        decision, page = state["decision"], state["page"]
        # Consume once, before any mutation or model call. A retry cannot double-click.
        state["decision"] = None
        selected = decision["choice"]
        if (
            selected not in {"DONE", "BLOCKED"}
            and len(state["history"]) > state["first_action"]
            and (
                self.completion_check(page)
                if self.completion_check is not None
                else (decision.get("done_probability") or 0) >= 0.9
            )
        ):
            selected = "DONE"  # Stop before another action can leave the verified checkpoint.
        if selected in {"DONE", "BLOCKED"}:
            if not self.browser.fresh(page):
                state["status"] = "ready"
                raise StalePage("Page changed since the decision. Choose again.")
            state["status"] = "done" if selected == "DONE" else "blocked"
            return
        action = next(a for a in page["actions"] if a["id"] == selected)
        if len(state["history"]) - state["first_action"] >= self.max_actions:
            raise Blocked(f"Reached this step's budget of {self.max_actions} actions")
        self.policy.before_act(action, page, decision)
        text, shown, source, helper = None, None, None, None
        if action["kind"] == "fill" and decision.get("secret"):
            text, shown, source = self.secrets[decision["secret"]], f"[secret:{decision['secret']}]", "secret"
        elif action["kind"] == "fill":
            if not self.browser.fresh(page):
                raise StalePage("Page changed before text generation. Choose again.")
            context = field_context(state["goal"], action, page, state["history"])
            if self.pending_text and self.pending_text[0] == context:
                _, text, helper = self.pending_text
            else:
                try:
                    text, helper = field_text(context)
                except ValueError:
                    raise Blocked(f"The text helper had no value for '{action['label']}'") from None
                self.pending_text = (context, text, helper)
                state["text_calls"].append({**helper, "field": action["label"], "value": text})
            shown, source = text, helper["source"]
        elif action["kind"] == "upload":
            text, shown, source = str(self.files[decision["file"]]), f"[file:{decision['file']}]", "file"
        record = {
            "action": action["label"],
            "kind": action["kind"],
            "choice": selected,
            "operation": decision["operation"],
            "target": decision["target"],
            "probability": decision["probabilities"][selected],
            "confidence": decision["confidence"],
            "latency_ms": decision["latency_ms"],
            "text": shown,
            "text_source": source,
            "text_latency_ms": helper["latency_ms"] if helper else 0,
            "page_changed": None,
            "url": page["url"],
            "elapsed_ms": self.elapsed(),
        }
        # Browser.act checks freshness immediately before input, including after text generation.
        try:
            self.browser.act(action, page, text=text)
        except StalePage:
            raise  # Nothing ran: the freshness check failed before input.
        except BaseException:
            # A dialog decision, a timeout, or an interrupt can stop input that already ran. Record it once.
            state["history"].append({**record, "uncertain": True})
            raise
        self.pending_text = None
        # Record execution before observing. A stale post-action observation must not erase the action.
        state["history"].append(record)
        self.before_action = page
        self.observe()
        self.settle_change()

    def settle_change(self):
        """Compare the first successful read after an action with the page before it, then check for a stuck run."""
        state, before = self.state, self.before_action
        if before is None:
            return
        self.before_action = None
        state["history"][-1].update(
            page_changed=state["page"]["fingerprint"] != before["fingerprint"], url=state["page"]["url"]
        )
        repeated = state["history"][-3:]
        stuck = len(repeated) == 3 and all(h["page_changed"] is False and h["kind"] != "wait" for h in repeated)
        state["status"] = "blocked" if stuck else "ready"

    def run(self):
        while self.state["status"] not in {"done", "blocked"}:
            yield self.tick()
