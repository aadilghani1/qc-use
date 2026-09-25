"""`qc-use init`: a qa/ folder with an example critical path, a secrets file template, and ignore rules."""

from pathlib import Path

EXAMPLE = """---
url: http://localhost:3000/login
secrets: [LOGIN_EMAIL, LOGIN_PASSWORD]
---
# Sign in

Adapt the labels and expected route to your app. Use an existing test account.

1. Enter LOGIN_EMAIL in the email field
   - action: Enter LOGIN_EMAIL in the email field
   - expect: the email field holds the LOGIN_EMAIL secret
2. Enter LOGIN_PASSWORD in the password field
   - action: Enter LOGIN_PASSWORD in the password field
   - expect: the password field is filled
3. Click Sign in
   - action: Click Sign in
   - check: url contains /dashboard
4. Check the dashboard
   - mode: observe
   - check: url contains /dashboard
"""

ENV = """# qc-use reads this file; keep it out of git. Values here never reach a model.
# Inference: one Vercel AI Gateway key runs Jev and the text helper. https://vercel.com/docs/ai-gateway
AI_GATEWAY_API_KEY=

# Test secrets, referenced by name in your tests.
LOGIN_EMAIL=
LOGIN_PASSWORD=
"""
IGNORE = ["qa-results/", "qa/.env"]


def init(directory):
    root = Path(directory)
    qa = root / "qa"
    qa.mkdir(parents=True, exist_ok=True)
    lines = []
    for path, content in [(qa / "onboarding.md", EXAMPLE), (qa / ".env", ENV)]:
        if path.exists():
            lines.append(f"· kept {path}")
        else:
            path.write_text(content, encoding="utf-8")
            lines.append(f"✓ created {path}")
    gitignore = root / ".gitignore"
    existing = gitignore.read_text(encoding="utf-8").splitlines() if gitignore.exists() else []
    missing = [rule for rule in IGNORE if rule not in existing]
    if missing:
        prefix = "\n" if existing and existing[-1].strip() else ""
        gitignore.write_text("\n".join(existing) + prefix + "\n".join(["# qc-use", *missing]) + "\n", encoding="utf-8")
        lines.append(f"✓ ignored {', '.join(missing)} in {gitignore}")
    lines += [
        "",
        "Next: put your AI Gateway key and test credentials in qa/.env, edit qa/onboarding.md, then run",
        "  qc-use validate qa/onboarding.md",
        "  qc-use run qa/onboarding.md --watch",
    ]
    return lines
