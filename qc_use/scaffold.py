"""`qc-use init`: a qa/ folder with an example critical path, a secrets file template, and ignore rules."""

from pathlib import Path

EXAMPLE = """---
url: http://localhost:3000/login
secrets: [LOGIN_EMAIL, LOGIN_PASSWORD]
persona:
  role: Head of Operations
  company_size: 51-200
rate:
  onboarding_ease: [confusing, effortful, okay, smooth, effortless]
---
# Onboarding critical path

A new user signs in for the first time and reaches the product's first useful screen.

1. Sign in with LOGIN_EMAIL and LOGIN_PASSWORD
   - expect: the first onboarding screen is showing
2. Complete onboarding as the persona
   - expect: the main dashboard is showing
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
            path.write_text(content)
            lines.append(f"✓ created {path}")
    gitignore = root / ".gitignore"
    existing = gitignore.read_text().splitlines() if gitignore.exists() else []
    missing = [rule for rule in IGNORE if rule not in existing]
    if missing:
        prefix = "\n" if existing and existing[-1].strip() else ""
        gitignore.write_text("\n".join(existing) + prefix + "\n".join(["# qc-use", *missing]) + "\n")
        lines.append(f"✓ ignored {', '.join(missing)} in {gitignore}")
    lines += [
        "",
        "Next: put your AI Gateway key and test credentials in qa/.env, edit qa/onboarding.md, then run",
        "  qc-use run qa/onboarding.md",
    ]
    return lines
