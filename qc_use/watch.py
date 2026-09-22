"""`qc-use run --watch`: a read-only live view of a run. Loopback only, behind a per-run token."""

import json
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .engine import model

PAGE = Path(__file__).with_name("watch.html")


def top(probabilities, labels, limit=6):
    ranked = sorted(probabilities.items(), key=lambda item: -item[1])[:limit]
    return [{"label": labels.get(key, key), "p": round(p, 4)} for key, p in ranked]


class Watch:
    def __init__(self, spec):
        self.token = secrets.token_urlsafe(16)
        self.lock = threading.Lock()
        self.started = time.perf_counter()
        self.state = {
            "title": spec.title, "url": spec.url, "status": "running", "current": 0, "summary": "",
            "steps": [{"text": s.text, "expect": s.expect, "outcome": None, "reason": None} for s in spec.steps],
            "decision": None, "actions": [], "page": None, "shot": 0,
        }
        self.screenshot = b""

    @classmethod
    def start(cls, spec, echo=print):
        watch = cls(spec)
        server = ThreadingHTTPServer(("127.0.0.1", 0), watch.handler())
        threading.Thread(target=server.serve_forever, daemon=True).start()
        watch.server = server
        url = f"http://127.0.0.1:{server.server_port}/?t={watch.token}"
        echo(f"  Watching live at {url}")
        webbrowser.open(url)
        return watch

    def __call__(self, index, state, image=None):
        """Called by the runner after every tick of the current step, with a masked JPEG of the page."""
        last = state["decisions"][-1] if state["decisions"] else None
        decision = None
        if last:
            questions = last["request"]["questions"]
            target_question = questions.get(f"{last['operation'].lower()}_target", {})
            targets = {k: v.get("element", k) + (f" · {v['enters']}" if "secret" in v.get("enters", "") else "")
                       for k, v in target_question.get("criteria", {}).items()}
            decision = {
                "operation": last["operation"], "confidence": last["confidence"], "latency_ms": last["latency_ms"],
                "operations": top(last["operation_probabilities"], {}),
                "targets": top(last["target_probabilities"], targets),
            }
        page = state["page"] or {}
        redact = model.HOOKS["redact"] or (lambda value: value)
        with self.lock:
            self.state.update(
                current=index,
                decision=decision,
                page=redact({"url": page.get("url", ""), "title": page.get("title", "")}),
                actions=redact([
                    {k: h.get(k) for k in ("action", "operation", "text", "probability", "latency_ms", "page_changed")}
                    for h in state["history"][-12:]
                ]),
                elapsed_ms=round((time.perf_counter() - self.started) * 1000),
            )
            if image:
                self.screenshot = image
                self.state["shot"] += 1

    def record(self, result):
        with self.lock:
            step = self.state["steps"][result.index - 1]
            step.update(outcome=result.outcome, reason=result.reason,
                        checks=[c.model_dump() for c in result.checks])

    def finish(self, report=None):
        with self.lock:
            self.state["status"] = report.outcome if report else "stopped"
            self.state["summary"] = report.summary if report else ""
            self.state["elapsed_ms"] = round((time.perf_counter() - self.started) * 1000)
        time.sleep(1)  # Let the open page fetch the final state before the process exits.

    def handler(self):
        watch = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                query = parse_qs(urlparse(self.path).query)
                if query.get("t", [""])[0] != watch.token or not self.headers.get("Host", "").startswith("127.0.0.1"):
                    return self.reply(403, b"Forbidden", "text/plain")
                path = urlparse(self.path).path
                if path == "/":
                    return self.reply(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                with watch.lock:
                    if path == "/api/state":
                        return self.reply(200, json.dumps(watch.state).encode(), "application/json")
                    if path == "/api/screenshot" and watch.screenshot:
                        return self.reply(200, watch.screenshot, "image/jpeg")
                self.reply(404, b"Not found", "text/plain")

            def reply(self, status, body, kind):
                self.send_response(status)
                self.send_header("Content-Type", kind)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        return Handler
