"""Check local setup and credentials without paid model calls."""

import json
import math
import os
import sys
from pathlib import Path

import httpx

from . import __version__, build_identity
from .chrome import Chrome, find_chrome
from .engine import model
from .guards import looks_like_production
from .report import SETUP_ERROR
from .secrets import MIN_MASKED, Redactor, load_env
from .skill import status


def doctor(file=None, *, json_output=False):
    """Return actionable setup checks in text or JSON, including installed skill freshness."""
    checks = []

    def report(ok, message, hint=""):
        checks.append({"ok": ok, "message": message, "hint": hint})

    spec = None
    if file:
        from .spec import SpecError, load

        try:
            spec = load(file)
            load_env(spec.path.parent)
        except (SpecError, OSError) as error:
            report(False, f"Test file: {error}")
    folders = [Path.cwd()] if file else [Path.cwd() / "qa", Path.cwd()]
    for folder in folders:
        try:
            load_env(folder)
        except OSError:
            report(False, f"Cannot read {folder / '.env'}", "Check file permissions.")
    names = [
        *(spec.secrets if spec else []),
        "AI_GATEWAY_API_KEY",
        "VERCEL_OIDC_TOKEN",
        "TYPESAFE_API_KEY",
        "TEXT_MODEL_API_KEY",
    ]
    redact = Redactor({name: os.environ.get(name, "") for name in names})
    report(sys.version_info >= (3, 12), f"Python {sys.version.split()[0]}")
    chrome = find_chrome()
    report(bool(chrome), f"Chrome: {chrome or 'not found'}", "" if chrome else "Install Chrome or set QC_USE_CHROME.")
    if chrome:
        try:
            with Chrome(headless=True):
                report(True, "Chrome starts on a private profile with DevTools")
        except (RuntimeError, OSError) as error:
            report(False, f"Chrome did not start: {error}", "Check QC_USE_CHROME and executable permissions.")
    try:
        url, keys, jev = model.jev_endpoint()
        key = model.credential(keys)
        report(bool(key), f"Jev {jev}", "" if key else f"Set {' or '.join(keys)} in qa/.env or the environment.")
        if key and url.startswith(model.GATEWAY):
            try:
                response = httpx.get(
                    model.GATEWAY + "/v1/credits", headers={"Authorization": f"Bearer {key}"}, timeout=10
                )
                if response.status_code == 200:
                    balance = float(response.json()["balance"])
                    if not math.isfinite(balance):
                        raise ValueError
                    report(
                        balance > 0,
                        f"AI Gateway key works · balance ${balance:.2f}",
                        "" if balance > 0 else "Add credit.",
                    )
                else:
                    report(
                        False,
                        f"AI Gateway credential check returned HTTP {response.status_code}",
                        "Check the key or retry later.",
                    )
            except httpx.HTTPError:
                report(False, "AI Gateway credential check is unreachable", "Check your connection and retry.")
            except (ValueError, TypeError, KeyError):
                report(False, "AI Gateway returned an invalid credit response", "Retry later; no model was called.")
    except ValueError as error:
        report(False, str(error), "Correct the provider setting in your environment.")
    try:
        base, text_model = model.text_settings()
        report(
            bool(model.text_key(base)),
            f"Text helper {text_model} via {base}",
            "Requires a configured API key; model availability is not probed.",
        )
    except ValueError as error:
        report(False, str(error), "Correct the text helper settings.")
    if spec:
        report(True, f"Test file: {spec.title} · {len(spec.steps)} steps")
        production = looks_like_production(spec.url) and not spec.allow_production
        report(not production, f"Target {spec.url}", "Production needs explicit authorization." if production else "")
        for name in spec.secrets:
            value = os.environ.get(name, "")
            ok = len(value) >= MIN_MASKED
            report(
                ok, f"Secret {name}: {'set' if ok else 'missing or too short'}", "" if ok else "Edit qa/.env locally."
            )
        try:
            response = httpx.get(spec.url, timeout=5, follow_redirects=True)
            report(
                response.status_code < 400,
                f"App answers at {spec.url} (HTTP {response.status_code})",
                "" if response.status_code < 400 else "Check the start URL and authentication.",
            )
        except httpx.HTTPError:
            report(False, f"Nothing answers at {spec.url}", "Start the app, then run qc-use again.")
    skills = status()
    ready = all(c["ok"] for c in checks)
    result = redact(
        {"ready": ready, "version": __version__, "build": build_identity(), "checks": checks, "skills": skills}
    )
    if json_output:
        print(json.dumps(result, indent=2))
    else:
        print(f"qc-use {__version__} ({result['build'][:12]})")
        for check in result["checks"]:
            print(
                f"{'✓' if check['ok'] else '✗'} {check['message']}"
                + (f"\n    {check['hint']}" if check["hint"] else "")
            )
        for skill in skills:
            print(
                f"Skill {skill['agent']}: {skill['status']}"
                + ("; run qc-use skill install to refresh." if skill["status"] != "current" else "")
            )
        print(
            "Ready. Provider availability is checked by preflight when a run starts."
            if ready
            else "Fix the setup checks above."
        )
    return 0 if ready else SETUP_ERROR
