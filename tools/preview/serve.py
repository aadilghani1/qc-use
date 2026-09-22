"""Serve the real live-view HTML with fake run data and optional local DialKit controls."""

import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAGE = ROOT.parents[1] / "qc_use" / "watch.html"
START = time.monotonic()
STEPS = [
    ("Sign in with the declared test account", "The onboarding screen is showing"),
    ("Fill in the profile and upload an avatar", "The workspace step is showing"),
    ("Create a workspace for Northwind Freight", "The invite step is showing"),
    ("Skip invitations and open the dashboard", "The dashboard welcomes Priya"),
]


def state():
    """Return synthetic states for tuning without a browser or a model call."""
    elapsed = time.monotonic() - START
    current = min(3, int(elapsed / 5))
    done = elapsed >= 22
    return {
        "title": "Onboarding critical path",
        "url": "http://localhost:3100/login",
        "status": "pass" if done else "running",
        "current": current,
        "elapsed_ms": min(22000, int(elapsed * 1000)),
        "summary": "All 4 steps passed. Each result was checked against fresh evidence." if done else "",
        "steps": [
            {"text": text, "expect": [expect], "outcome": "pass" if done or i < current else None}
            for i, (text, expect) in enumerate(STEPS)
        ],
        "page": {"title": "Beacon · Dashboard", "url": "http://localhost:3100/dashboard"},
        "shot": 1,
        "has_screenshot": True,
        "decision": {
            "operation": "DONE" if done else "CLICK",
            "confidence": 0.96,
            "latency_ms": 317,
            "operations": [
                {"label": "CLICK", "p": 0.96},
                {"label": "WAIT", "p": 0.03},
                {"label": "BLOCKED", "p": 0.01},
            ],
            "targets": [] if done else [{"label": "Continue", "p": 0.98}, {"label": "Back", "p": 0.02}],
        },
        "action_count": 12,
        "actions": [
            {
                "operation": op,
                "action": action,
                "text": text,
                "probability": 0.98,
                "latency_ms": 317,
                "page_changed": True,
            }
            for op, action, text in [
                ("TYPE_TEXT", "Workspace name", "Northwind Freight"),
                ("CLICK", "Continue", None),
                ("CLICK", "Skip for now", None),
            ]
        ],
    }


class Handler(BaseHTTPRequestHandler):
    """Expose only fixture routes and the three named design assets."""

    def do_GET(self):
        global START
        path = self.path.split("?", 1)[0]
        assets = {
            "/dialkit.js": ROOT / "node_modules/dialkit/dist/vanilla/browser.global.js",
            "/dialkit.css": ROOT / "node_modules/dialkit/dist/vanilla/styles.css",
            "/tune.js": ROOT / "tune.js",
        }
        if path == "/":
            START = time.monotonic()
            body = PAGE.read_text().replace("</head>", '<link rel="stylesheet" href="/dialkit.css"></head>')
            body = body.replace("</body>", '<script src="/dialkit.js"></script><script src="/tune.js"></script></body>')
            return self.reply(body.encode(), "text/html")
        if path == "/api/state":
            return self.reply(json.dumps(state()).encode(), "application/json")
        if path == "/api/screenshot":
            return self.reply((ROOT / "fixture.svg").read_bytes(), "image/svg+xml")
        if path in assets and assets[path].is_file():
            return self.reply(assets[path].read_bytes(), "text/css" if path.endswith("css") else "text/javascript")
        self.send_error(404)

    def reply(self, body, kind):
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", 4318), Handler)
    print("Design preview: http://127.0.0.1:4318 (synthetic data only)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
