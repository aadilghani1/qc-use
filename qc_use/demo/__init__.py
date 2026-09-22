"""`qc-use demo`: serve Beacon locally and run the bundled tests against it, a pass, a failure and a stop."""

import os
import sys
import time
from pathlib import Path

from ..report import SETUP_ERROR
from .app import EMAIL, PASSWORD, serve

TESTS = Path(__file__).with_name("tests")
# Each bundled test shows one outcome: a pass, a real bug (exit 1), and a stop for approval (exit 3).
EXPECTED = {"onboarding.md": 0, "invite.md": 1, "cleanup.md": 3}


def main(port=3100, serve_only=False, headless=False, results="qa-results"):
    from ..secrets import load_env

    load_env(Path.cwd() / "qa")
    load_env(Path.cwd())
    server = serve(port)
    url = f"http://localhost:{port}/login"
    print(f"Beacon demo app: {url}  (sign in as {EMAIL} / {PASSWORD})")
    if serve_only:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    os.environ.setdefault("DEMO_EMAIL", EMAIL)
    os.environ.setdefault("DEMO_PASSWORD", PASSWORD)
    from ..cli import main as cli

    try:
        if port != 3100:
            print("The bundled tests use port 3100. Use `qc-use demo --serve --port N` for other ports.")
            return SETUP_ERROR
        codes = {
            name: cli(["run", str(TESTS / name), "--results", str(results), *(["--headless"] if headless else [])])
            for name in EXPECTED
        }
        if codes == EXPECTED:
            print("qc-use works. You saw a pass, a real bug that qc-use caught, and a risky action that stopped.")
            return 0
        print(f"Unexpected demo outcomes (exit codes {codes}, expected {EXPECTED}). See the reports above.")
        return 1
    finally:
        server.shutdown()
        sys.stdout.flush()
