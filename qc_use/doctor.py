"""`qc-use doctor`: is everything ready to run? Free checks only; no model is called."""

import os
import sys
from pathlib import Path

import httpx

from .chrome import Chrome, find_chrome
from .engine import model
from .guards import looks_like_production
from .report import SETUP_ERROR
from .secrets import MIN_MASKED, load_env


def doctor(file=None):
    problems = 0

    def report(ok, message, hint=""):
        nonlocal problems
        mark = {True: "✓", False: "✗", None: "!"}[ok]
        problems += ok is False
        print(f"{mark} {message}" + (f"\n    {hint}" if hint else ""))

    spec = None
    if file:
        from .spec import SpecError, load

        try:
            spec = load(file)
            load_env(spec.path.parent)
        except (SpecError, OSError) as error:
            report(False, f"Test file: {error}")
    load_env(Path.cwd() / "qa")
    load_env(Path.cwd())

    report(sys.version_info >= (3, 12), f"Python {sys.version.split()[0]}")
    chrome = find_chrome()
    report(bool(chrome), f"Chrome: {chrome or 'not found'}", "" if chrome else "Install Chrome or set QC_USE_CHROME.")
    if chrome:
        try:
            with Chrome(headless=True):
                report(True, "Chrome starts on a private profile with DevTools")
        except RuntimeError as error:
            report(False, f"Chrome did not start: {error}")

    url, keys, jev = model.jev_endpoint()
    key = model.credential(keys)
    via_gateway = url.startswith(model.GATEWAY)
    report(
        bool(key),
        f"Jev {jev} via {'Vercel AI Gateway' if via_gateway else 'TypeSafe'}",
        "" if key else f"Set {' or '.join(keys)} in qa/.env or the environment.",
    )
    if key and via_gateway:
        try:
            response = httpx.get(model.GATEWAY + "/v1/credits", headers={"Authorization": f"Bearer {key}"}, timeout=10)
            if response.status_code == 200:
                report(True, f"AI Gateway key works · balance ${float(response.json().get('balance', 0)):.2f}")
            else:
                report(False, f"AI Gateway rejected the key (HTTP {response.status_code})")
        except httpx.HTTPError as error:
            report(False, f"AI Gateway unreachable: {error}")
    base, text_model = model.text_settings()
    text_key = model.text_key(base)
    report(
        bool(text_key),
        f"Text helper {text_model} via {base}",
        "" if text_key else "Set TEXT_MODEL_API_KEY, or AI_GATEWAY_API_KEY for the gateway.",
    )

    if spec:
        report(True, f"Test file: {spec.title} · {len(spec.steps)} steps")
        production = looks_like_production(spec.url) and not spec.allow_production
        warning = "Looks like production; qc-use will refuse it without allow_production." if production else ""
        report(not production, f"Target {spec.url}", warning)
        for name in spec.secrets:
            value = os.environ.get(name)
            if not value:
                report(False, f"Secret {name} is not set", "Add it to qa/.env or the environment.")
            elif len(value) < MIN_MASKED:
                report(False, f"Secret {name} is shorter than {MIN_MASKED} characters; qc-use will refuse the run")
            else:
                report(True, f"Secret {name} is set")
        try:
            status = httpx.get(spec.url, timeout=5, follow_redirects=True).status_code
            report(status < 500, f"App answers at {spec.url} (HTTP {status})")
        except httpx.HTTPError:
            report(False, f"Nothing answers at {spec.url}", "Start the app, then run qc-use again.")
    print("Ready." if not problems else f"{problems} problem{'s' if problems > 1 else ''} to fix.")
    return 0 if not problems else SETUP_ERROR
