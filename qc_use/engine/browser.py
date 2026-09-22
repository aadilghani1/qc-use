"""Observed actions through Browser Harness; one CDP session, no per-step subprocess."""

import hashlib
import json
import sys
import threading
import time
from pathlib import Path

from browser_harness.admin import ensure_daemon
from browser_harness.helpers import _send, cdp, drain_events

from .errors import StalePage

# Atomically read visible content and controls, preserving actual DOM node identity.
READ_STATE = Path(__file__).with_name("snapshot.js").read_text()
MARKER = f"(() => {{ const state={READ_STATE}; return state?.marker ?? null; }})()"


def accept_alerts(dialog):
    """Default dialog policy: acknowledge alerts, refuse everything else."""
    return dialog["type"] in {"alert", "beforeunload"}, None


class Browser:
    def __init__(self, url, on_dialog=accept_alerts):
        ensure_daemon()
        self.on_dialog = on_dialog
        self.dialogs = []
        self.target = cdp("Target.createTarget", url="about:blank", background=True)["targetId"]
        self.session = cdp("Target.attachToTarget", targetId=self.target, flatten=True)["sessionId"]
        self.call("Emulation.setDeviceMetricsOverride", width=1120, height=780, deviceScaleFactor=1, mobile=False)
        # Keep rAF/menus rendering in an owned background tab, without activating the user's Chrome tab.
        self.call("Emulation.setFocusEmulationEnabled", enabled=True)
        # Page events report dialogs; Runtime and Network events become console, exception and HTTP signals.
        for domain in ("Page", "Runtime", "Network"):
            self.call(f"{domain}.enable")
        self.popups = set()
        self.call("Page.navigate", url=url)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.evaluate("document.readyState") == "complete":
                break
            time.sleep(0.02)

    def call(self, method, **params):
        return cdp(method, session_id=self.session, **params)

    def evaluate(self, expression):
        response = self.call("Runtime.evaluate", expression=expression, returnByValue=True)
        if response.get("exceptionDetails"):
            raise StalePage("Document changed during evaluation")
        return response.get("result", {}).get("value")

    def dialog(self):
        return _send({"meta": "pending_dialog"}).get("dialog")

    def settle_dialog(self):
        """A native dialog freezes the page. Decide it before any read or input can continue."""
        dialog = self.dialog()
        if not dialog:
            return False
        record = {"type": dialog["type"], "message": dialog.get("message", ""), "url": dialog.get("url", "")}
        try:
            accept, text = self.on_dialog(record)
        except BaseException:
            self.call("Page.handleJavaScriptDialog", accept=False)
            self.dialogs.append({**record, "accepted": False})
            raise
        params = {"accept": accept, **({"promptText": text} if text is not None else {})}
        self.call("Page.handleJavaScriptDialog", **params)
        self.dialogs.append({**record, "accepted": accept})
        return True

    def input(self, operation):
        """Send input on a worker. A dialog opened by the input blocks the CDP call until it is decided."""
        outcome = {}

        def work():
            try:
                outcome["result"] = operation()
            except BaseException as error:
                outcome["error"] = error

        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        decided = False
        while worker.is_alive():
            worker.join(0.025)
            try:
                if worker.is_alive() and self.settle_dialog():
                    decided = True
            except BaseException:
                worker.join(6)  # The dialog was dismissed; let the blocked input call return first.
                raise
        error = outcome.get("error")
        # The input was delivered: a dialog only opens in response to it. Its call may time out while waiting.
        if isinstance(error, TimeoutError) and decided:
            return {"dialog": True}
        if error:
            raise error
        return outcome["result"]

    def signals(self):
        """Console errors, uncaught exceptions and failed HTTP requests for this tab since the last call."""
        found = []
        for event in drain_events():
            if event.get("session_id") != self.session:
                continue
            method, params = event["method"], event["params"]
            if method == "Runtime.consoleAPICalled" and params.get("type") == "error":
                text = " ".join(str(a.get("value", a.get("description", ""))) for a in params.get("args", []))
                found.append({"kind": "console_error", "text": text[:500]})
            elif method == "Runtime.exceptionThrown":
                details = params.get("exceptionDetails", {})
                text = details.get("exception", {}).get("description") or details.get("text", "")
                found.append({"kind": "js_exception", "text": text.splitlines()[0][:500] if text else ""})
            elif (
                method == "Network.responseReceived"
                and params["response"]["status"] >= 400
                and not params["response"]["url"].endswith("/favicon.ico")
            ):
                status = params["response"]["status"]
                found.append(
                    {
                        "kind": "http_5xx" if status >= 500 else "http_4xx",
                        "text": f"{status} {params['response']['url'][:300]}",
                        "status": status,
                    }
                )
            elif method == "Network.loadingFailed" and not params.get("canceled"):
                found.append({"kind": "request_failed", "text": params.get("errorText", "")[:300]})
        return found

    def new_tabs(self):
        """Tabs or windows this page opened. They are outside the controlled page."""
        opened = [
            t
            for t in cdp("Target.getTargets")["targetInfos"]
            if t["type"] == "page" and t.get("openerId") == self.target and t["targetId"] not in self.popups
        ]
        self.popups.update(t["targetId"] for t in opened)
        return [t["url"] for t in opened]

    def observe(self, screenshot=True):
        self.settle_dialog()
        if getattr(self, "after_input", None):
            action, self.after_input = self.after_input, None
            # This is read-only and happens after execution was logged, even if navigation interrupts it.
            try:
                self.call(
                    "Runtime.evaluate",
                    expression="""(action => new Promise(resolve => {
                      const field=window.__jevFast?.nodes.get(action.node);
                      const autocomplete=action.kind==='fill' && field?.getAttribute('role')==='combobox';
                      let frames=0, stopped=false;
                      const finish=()=>{stopped=true;resolve()};
                      setTimeout(finish,autocomplete ? 200 : 50);
                      const ready=()=>{
                        if (stopped) return;
                        const ids=(field?.getAttribute('aria-controls')||field?.getAttribute('aria-owns')||'')
                          .split(/\\s+/).filter(Boolean);
                        const roots=ids.length ? ids.map(id=>document.getElementById(id)).filter(Boolean) : [document];
                        const options=roots.flatMap(root=>[...root.querySelectorAll('[role="option"]')]);
                        if (++frames>=2 && (!autocomplete || options.some(e=>{
                          const r=e.getBoundingClientRect();
                          return r.width && r.height && r.bottom>0 && r.top<innerHeight &&
                            e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true});
                        }))) finish();
                        else requestAnimationFrame(ready);
                      };
                      requestAnimationFrame(ready);
                    }))("""
                    + json.dumps(action)
                    + ")",
                    awaitPromise=True,
                    returnByValue=True,
                )
            except (RuntimeError, TimeoutError):
                self.settle_dialog()
        for attempt in range(10):
            try:
                return browser_operation({"operation": "observe", "session": self.session, "screenshot": screenshot})
            except StalePage:
                if attempt == 9:
                    raise
                time.sleep(0.02)
            except TimeoutError:
                # A dialog opened between reads (a timer, an unload handler). Decide it, then read again.
                if not self.settle_dialog() or attempt == 9:
                    raise
        raise StalePage("Page did not settle")

    def fresh(self, page, action=None):
        if action is not None and action["kind"] in {"click", "select", "upload"}:
            node = action["node"]
            if type(node) is not int:
                return False
            current = self.evaluate(
                "(() => { const c=window.__jevFast; "
                f"return c ? [c.pageKey(),c.guard(c.nodes.get({node}))] : null; }})()"
            )
            return current == [page["page_key"], page["guards"].get(str(node))]
        return self.evaluate(MARKER) == page["marker"]

    def act(self, action, page, text=None):
        if not self.fresh(page, action):
            raise StalePage("Page changed since this decision. Observe again.")
        if action["kind"] == "wait":
            time.sleep(0.1)
        request = {"operation": "act", "session": self.session, "action": action, "text": text}
        result = self.input(lambda: browser_operation(request))
        self.after_input = action if action["kind"] != "wait" else None
        return result

    def close(self):
        if self.target:
            cdp("Target.closeTarget", targetId=self.target)
            self.target = None


def fingerprint(state):
    content = {k: state[k] for k in ("url", "text", "actions", "scroll")}
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def browser_operation(request):
    operation = request["operation"]
    session = request["session"]

    def call(method, **params):
        return cdp(method, session_id=session, **params)

    def evaluate(expression):
        result = call("Runtime.evaluate", expression=expression, returnByValue=True)
        if result.get("exceptionDetails"):
            if operation == "act" and request["action"]["kind"] == "select":
                raise RuntimeError("Dropdown execution was interrupted; inspect before retrying.")
            raise StalePage("Document changed during evaluation")
        return result.get("result", {}).get("value")

    if operation == "act":
        action = request["action"]
        kind = action["kind"]
        if kind == "upload":
            if type(action["node"]) is not int:
                raise ValueError("Invalid observed node")
            # The file path comes from the test's declared fixtures, never from model output.
            handle = call(
                "Runtime.evaluate",
                expression=f"(() => {{ const e=window.__jevFast?.nodes.get({action['node']}); "
                "return e?.isConnected && e.type==='file' && !e.disabled ? e : null; })()",
            ).get("result", {})
            if not handle.get("objectId"):
                raise StalePage("Upload field changed. Observe again.")
            call("DOM.setFileInputFiles", files=[request["text"]], objectId=handle["objectId"])
            return {"executed": action["id"]}
        if kind == "scroll":
            call("Input.dispatchMouseEvent", type="mouseWheel", x=550, y=650, deltaX=0, deltaY=action["delta"])
        elif kind != "wait":
            if type(action["node"]) is not int:
                raise ValueError("Invalid observed node")
            # Code-owned node IDs refer to actual observed elements, never model-generated selectors.
            target = evaluate(
                """(action => {
              const e=window.__jevFast?.nodes.get(action.node);
              if (!e?.isConnected || e.matches(':disabled') || e.closest('[aria-disabled="true"],[inert]') ||
                  !e.checkVisibility({checkOpacity:true,checkVisibilityCSS:true})) return null;
              if (action.kind==='fill' && (e.readOnly || e.getAttribute('aria-readonly')==='true')) return null;
              const r=e.getBoundingClientRect(), x=r.x+r.width/2, y=r.y+r.height/2;
              if (!r.width || !r.height || x<0 || y<0 || x>=innerWidth || y>=innerHeight) return null;
              if (!e.contains(document.elementFromPoint(x,y))) return null;
              if (action.kind==='select') {
                if (e.tagName!=='SELECT' || ![...e.options].some(o=>o.value===action.value &&
                    !o.disabled && !o.closest('optgroup[disabled]'))) return null;
                e.value=action.value;
                e.dispatchEvent(new Event('input',{bubbles:true}));
                e.dispatchEvent(new Event('change',{bubbles:true}));
              }
              return {x,y};
            })("""
                + json.dumps(action)
                + ")"
            )
            if target is None:
                if kind == "select":
                    raise RuntimeError("Dropdown execution was not confirmed; inspect before retrying.")
                raise StalePage("Target changed or is covered. Observe again.")
            if kind != "select":
                x, y = target["x"], target["y"]
                for event in ("mousePressed", "mouseReleased"):
                    call("Input.dispatchMouseEvent", type=event, x=x, y=y, button="left", clickCount=1)
                if kind == "fill":
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyDown",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                        commands=["selectAll"],
                    )
                    call(
                        "Input.dispatchKeyEvent",
                        type="keyUp",
                        key="a",
                        code="KeyA",
                        modifiers=4 if sys.platform == "darwin" else 2,
                    )
                    call("Input.insertText", text=request["text"])
        return {"executed": action["id"]}

    info = evaluate(READ_STATE)
    if info is None:
        raise StalePage("Document is navigating")
    info["fingerprint"] = fingerprint(info)
    if request.get("screenshot", True):
        info["screenshot"] = call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
    return info
