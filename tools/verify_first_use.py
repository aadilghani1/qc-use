"""Exercise an installed package in a separate project with live and saved evidence. Uses a model key."""

import argparse
import json
import os
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx

import qc_use
from qc_use.demo.app import EMAIL, PASSWORD, serve
from qc_use.scaffold import EXAMPLE


def main():
    """Run the fixture visibly by default; --headless is available for unattended verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--headless", action="store_true")
    args = parser.parse_args()
    assert "site-packages" in str(Path(qc_use.__file__).resolve()), "Use an installed wheel's Python."
    if os.name == "nt":
        raise SystemExit("This live acceptance script requires POSIX signals. Windows installation is checked in CI.")
    server = serve(0)
    command = str(Path(sys.executable).with_name("qc-use"))
    env = {**os.environ, "LOGIN_EMAIL": EMAIL, "LOGIN_PASSWORD": PASSWORD}
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="qc-use-project-") as folder:
            root = Path(folder)

            def run(*parts):
                result = subprocess.run([command, *parts], cwd=root, env=env, capture_output=True, encoding="utf-8")
                assert result.returncode == 0, result.stderr
                return result.stdout

            run("init")
            # This fixture is the test an agent writes after inspecting Beacon's login route.
            spec = EXAMPLE.replace("http://localhost:3000/login", f"http://127.0.0.1:{server.server_port}/login")
            spec = spec.replace("/dashboard", "/onboarding/profile").replace("Check the dashboard", "Check the profile")
            (root / "qa/onboarding.md").write_text(spec, encoding="utf-8")
            assert json.loads(run("validate", "qa/*.md", "--json"))[0]["valid"]
            run("doctor", "qa/onboarding.md", "--json")
            links = queue.Queue()
            finished = threading.Event()

            output = []
            readers = []

            def start(parts, saved=False):
                output.clear()
                readers.clear()
                proc = subprocess.Popen(
                    [command, *parts],
                    cwd=root,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )

                def read(stream, stdout=False):
                    for line in stream:
                        if stdout:
                            output.append(line)
                        if "Run finished." in line:
                            finished.set()
                        if (saved == stdout) and (match := re.search(r"http://127\.0\.0\.1:\d+/\?t=[\w-]+", line)):
                            links.put(match[0])
                            print(line.strip(), flush=True)

                for stream, stdout in ((proc.stdout, True), (proc.stderr, False)):
                    reader = threading.Thread(target=read, args=(stream, stdout), daemon=True)
                    reader.start()
                    readers.append(reader)
                return proc

            process = start(
                [
                    "run",
                    "qa/onboarding.md",
                    "--watch",
                    "--keep-open",
                    "--json-result",
                    *(["--headless"] if args.headless else []),
                ]
            )
            url = links.get(timeout=60)
            base, token = url.split("?", 1)
            deadline = time.monotonic() + 180
            saw_running = saw_image = False
            with httpx.Client(timeout=5) as client:
                while time.monotonic() < deadline:
                    state = client.get(base + "api/state?" + token).json()
                    saw_running |= state["status"] == "running"
                    if state.get("has_screenshot"):
                        image = client.get(base + "api/screenshot?" + token)
                        saw_image |= image.status_code == 200 and image.content.startswith(b"\xff\xd8\xff")
                    if state["status"] != "running":
                        break
                    time.sleep(0.2)
                assert state["status"] == "pass" and saw_running and saw_image, json.dumps(state)
                assert finished.wait(10), "No completed-view notice"
                process.send_signal(signal.SIGINT)
                process.wait(timeout=15)
                for reader in readers:
                    reader.join(timeout=5)
                stdout = "".join(output)
                assert process.returncode == 0
                result = json.loads(stdout)
                assert result["exit_code"] == 0 and not result["setup_errors"]
                assert EMAIL not in stdout and PASSWORD not in stdout
                report = result["reports"][0]
                process = start(["report", report["artifacts"]["folder"], "--no-open"], saved=True)
                saved = links.get(timeout=15)
                saved_base, saved_token = saved.split("?", 1)
                response = client.get(saved_base + "api/state?" + saved_token + "&step=0").json()
                assert response["saved"] and response["has_screenshot"]
                process.send_signal(signal.SIGINT)
                process.wait(timeout=15)
                for reader in readers:
                    reader.join(timeout=5)
                assert process.returncode == 0
            print("PASS: separate-project setup, validation, login, live images, command result, and saved evidence.")
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=15)
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
