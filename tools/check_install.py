"""Smoke-test the installed wheel from a new project without keys or a browser."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import qc_use


def main():
    """Prove the installed CLI can scaffold, validate, and install its bundled skill."""
    assert "site-packages" in str(Path(qc_use.__file__).resolve()), "Run with the wheel installed, outside uv run."
    with tempfile.TemporaryDirectory(prefix="qc-use-install-") as folder:
        root = Path(folder)
        env = {k: v for k, v in os.environ.items() if not k.endswith(("API_KEY", "OIDC_TOKEN"))}
        env.update(
            HOME=folder, USERPROFILE=folder, CODEX_HOME=str(root / "codex"), XDG_CONFIG_HOME=str(root / "config")
        )

        command = Path(sys.executable).with_name("qc-use.exe" if os.name == "nt" else "qc-use")

        def run(*args):
            result = subprocess.run(
                [str(command), *args],
                cwd=root,
                env=env,
                encoding="utf-8",
                capture_output=True,
                check=False,
            )
            assert result.returncode == 0, f"{args}: {result.stderr}"
            return result.stdout

        assert qc_use.__version__ in run("--version")
        run("init")
        before = (root / "qa/onboarding.md").read_bytes()
        run("init")
        assert (root / "qa/onboarding.md").read_bytes() == before
        assert json.loads(run("validate", "qa/onboarding.md", "--json"))[0]["valid"]
        assert json.loads(run("validate", "qa/*.md", "--json"))[0]["valid"]
        for kind in ("test", "report", "command"):
            assert "properties" in json.loads(run("schema", kind))
        run("skill", "install", "--path", str(root / "SKILL.md"))
        assert "qc-use validate" in (root / "SKILL.md").read_text(encoding="utf-8")
        run("skill", "install", "--target", "codex")
        status = json.loads(run("skill", "status"))
        assert next(s for s in status if s["agent"] == "codex")["status"] == "current"
        print(f"PASS: installed qc-use {qc_use.__version__}; init, validate, schema, skill install and freshness.")


if __name__ == "__main__":
    main()
