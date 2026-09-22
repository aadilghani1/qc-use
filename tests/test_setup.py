"""First-run commands work offline and preserve user configuration."""

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, Mock

import httpx
import pytest

from qc_use import cli, doctor, scaffold, skill
from qc_use.secrets import load_env


def test_blank_template_does_not_shadow_project_credentials(tmp_path, monkeypatch):
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    scaffold.init(tmp_path)
    (tmp_path / ".env").write_text("AI_GATEWAY_API_KEY=project-key\n")
    load_env(tmp_path / "qa")
    load_env(tmp_path)
    import os

    assert os.environ["AI_GATEWAY_API_KEY"] == "project-key"
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "shell-key")
    load_env(tmp_path)
    assert os.environ["AI_GATEWAY_API_KEY"] == "shell-key"


def test_init_preserves_existing_test_credentials_and_ignore_rules(tmp_path):
    scaffold.init(tmp_path)
    files = [tmp_path / "qa/onboarding.md", tmp_path / "qa/.env", tmp_path / ".gitignore"]
    for file in files:
        file.write_text(file.read_text() + "\n# Keep this\n")
    expected = [p.read_bytes() for p in files]
    scaffold.init(tmp_path)
    assert [p.read_bytes() for p in files] == expected


def test_validate_reports_all_files_without_browser_or_models(tmp_path, capsys, monkeypatch):
    scaffold.init(tmp_path)
    monkeypatch.setattr(doctor, "Chrome", Mock(side_effect=AssertionError("No browser")))
    code = cli.main(["validate", str(tmp_path / "qa/onboarding.md"), str(tmp_path / "missing.md"), "--json"])
    assert code == 4
    results = json.loads(capsys.readouterr().out)
    assert [r["valid"] for r in results] == [True, False]
    assert "missing.md" in results[1]["error"]


def test_skill_paths_status_and_refresh(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "custom-codex"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    skill.install(targets=list(skill.TARGETS))
    assert len(skill.status()) == len(skill.TARGETS)
    assert all(row["status"] == "current" for row in skill.status())
    places = skill.locations()
    assert places["codex"][1] == tmp_path / "custom-codex/skills/qc-use/SKILL.md"
    assert places["opencode"][1] == tmp_path / "config/opencode/skills/qc-use/SKILL.md"
    places["codex"][1].write_text("old instructions")
    assert next(r for r in skill.status() if r["agent"] == "codex")["status"] == "outdated or modified"
    skill.install(targets=["codex"])
    assert all(row["status"] == "current" for row in skill.status())
    with pytest.raises(ValueError, match="Unknown agent"):
        skill.install(targets=["typo"])


@pytest.mark.parametrize("problem", ["chrome", "provider", "not_found", "bad_credit"])
def test_doctor_returns_actionable_json_for_setup_failures(tmp_path, monkeypatch, capsys, problem):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(doctor, "status", list)
    monkeypatch.setattr(doctor, "find_chrome", lambda: "/missing/chrome")
    monkeypatch.setattr(
        doctor, "Chrome", Mock(side_effect=FileNotFoundError("missing Chrome")) if problem == "chrome" else MagicMock()
    )
    monkeypatch.setenv("JEV_PROVIDER", "typo" if problem == "provider" else "gateway")
    monkeypatch.setenv("AI_GATEWAY_API_KEY", "private-provider-key")
    monkeypatch.setattr(
        doctor.httpx,
        "get",
        lambda url, **kw: httpx.Response(
            404 if problem == "not_found" and "localhost" in url else 200,
            json={} if problem == "bad_credit" else {"balance": "5"},
        ),
    )
    path = tmp_path / "flow.md"
    path.write_text(
        "---\nurl: http://localhost:3000\n---\n# Test\n\n1. Read\n   - mode: observe\n   - check: text contains Ready\n"
    )
    assert cli.main(["doctor", str(path), "--json"]) == 4
    output = capsys.readouterr().out
    assert "private-provider-key" not in output
    result = json.loads(output)
    assert not result["ready"] and any(not c["ok"] for c in result["checks"])


def test_doctor_file_uses_the_same_environment_as_run(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AI_GATEWAY_API_KEY", raising=False)
    monkeypatch.setenv("JEV_PROVIDER", "gateway")
    (tmp_path / "qa/flows").mkdir(parents=True)
    (tmp_path / "qa/.env").write_text("AI_GATEWAY_API_KEY=wrong-qa-key\n")
    (tmp_path / ".env").write_text("AI_GATEWAY_API_KEY=right-root-key\n")
    path = tmp_path / "qa/flows/test.md"
    path.write_text("---\nurl: http://localhost:3000\n---\n# Observe\n1. Read\n   - check: text contains Ready\n")
    monkeypatch.setattr(doctor, "Chrome", MagicMock())
    monkeypatch.setattr(doctor, "find_chrome", lambda: "chrome")
    monkeypatch.setattr(doctor, "status", list)
    calls = []

    def get(url, **kwargs):
        calls.append(kwargs.get("headers", {}))
        return httpx.Response(200, json={"balance": "5"})

    monkeypatch.setattr(doctor.httpx, "get", get)
    assert cli.main(["doctor", str(path), "--json"]) == 0
    assert calls[0]["Authorization"] == "Bearer right-root-key"
    assert json.loads(capsys.readouterr().out)["ready"]


def test_all_shipped_examples_validate():
    from qc_use.spec import load

    examples = Path(__file__).resolve().parents[1] / "examples"
    for path in examples.glob("*.md"):
        if path.name != "README.md":
            assert load(path).steps


def test_cli_writes_utf8_even_when_redirected_to_legacy_encoding(tmp_path):
    import os
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "qc_use.cli", "init", str(tmp_path)],
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert "✓ created" in result.stdout.decode("utf-8")


@pytest.mark.parametrize("target", ["folder", "new-folder"])
def test_skill_install_into_a_folder_writes_skill_md(tmp_path, target):
    folder = tmp_path / target
    if target == "folder":
        folder.mkdir()
    assert cli.main(["skill", "install", "--path", str(folder)]) == 0
    assert (folder / "SKILL.md").read_text(encoding="utf-8") == skill.text()


def test_per_user_chrome_on_windows_is_found(tmp_path, monkeypatch):
    from qc_use import chrome

    installed = tmp_path / "Google" / "Chrome" / "Application" / "chrome.exe"
    installed.parent.mkdir(parents=True)
    installed.touch()
    monkeypatch.delenv("QC_USE_CHROME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr(chrome.platform, "system", lambda: "Windows")
    monkeypatch.setattr(chrome.shutil, "which", lambda _: None)
    assert chrome.find_chrome() == str(installed)


ROOT = Path(__file__).resolve().parent.parent


def test_plugin_ships_the_same_skill_as_the_package():
    # A symlink would ship as a short text file on Windows checkouts, so the copy is checked byte for byte.
    plugin = ROOT / "plugins/qc-use/skills/qc-use/SKILL.md"
    assert plugin.read_bytes() == (ROOT / "qc_use/SKILL.md").read_bytes()


def test_release_versions_agree():
    import tomllib

    import qc_use

    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    plugin = json.loads((ROOT / "plugins/qc-use/.claude-plugin/plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin/marketplace.json").read_text(encoding="utf-8"))
    assert project == qc_use.__version__ == plugin["version"]
    assert [(p["name"], (ROOT / p["source"]).is_dir()) for p in market["plugins"]] == [("qc-use", True)]
    for doc in ("README.md", "docs/ci.md"):
        refs = set(re.findall(r"aadilghani1/qc-use@v([\w.]+)", (ROOT / doc).read_text(encoding="utf-8")))
        assert refs == {project}, doc
