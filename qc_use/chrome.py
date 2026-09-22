"""A dedicated Chrome with its own profile. Tests never touch the user's everyday browser."""

import json
import os
import platform
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

CANDIDATES = {
    "Darwin": [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
    ],
    "Linux": ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser"],
    "Windows": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    ],
}
# A fresh profile has no saved passwords, sync, or first-run UI to get in the way.
PREFERENCES = {"credentials_enable_service": False, "profile": {"password_manager_enabled": False}}


def find_chrome():
    if path := os.environ.get("QC_USE_CHROME"):
        return path
    for candidate in CANDIDATES.get(platform.system(), []):
        if found := shutil.which(candidate) or (candidate if Path(candidate).exists() else None):
            return found
    return None


class Chrome:
    """Launch Chrome on a private profile and expose its DevTools endpoint."""

    def __init__(self, profile=None, headless=False):
        binary = find_chrome()
        if not binary:
            raise RuntimeError("Chrome was not found. Install Google Chrome or set QC_USE_CHROME to its path.")
        self.temporary = profile is None
        self.profile = Path(profile or tempfile.mkdtemp(prefix="qc-use-profile-"))
        (self.profile / "Default").mkdir(parents=True, exist_ok=True)
        preferences = self.profile / "Default" / "Preferences"
        if not preferences.exists():
            preferences.write_text(json.dumps(PREFERENCES))
        port_file = self.profile / "DevToolsActivePort"
        port_file.unlink(missing_ok=True)
        args = [
            binary,
            f"--user-data-dir={self.profile}",
            "--remote-debugging-port=0",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-default-apps",
            "--disable-sync",
            "--password-store=basic",
            "--use-mock-keychain",
            "--disable-features=Translate,MediaRouter,OptimizationHints",
            "--window-size=1180,900",
            *(["--headless=new"] if headless else []),
            "about:blank",
        ]
        self.process = subprocess.Popen(
            args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError(f"Chrome exited during startup (code {self.process.returncode}).")
            lines = port_file.read_text().splitlines() if port_file.exists() else []
            if lines and lines[0].strip().isdigit():
                self.url = f"http://127.0.0.1:{lines[0].strip()}"
                return
            time.sleep(0.05)
        self.close()
        raise RuntimeError("Chrome did not open its DevTools port within 20 seconds.")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(5)
        if self.temporary:
            shutil.rmtree(self.profile, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()
