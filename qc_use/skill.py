"""Install SKILL.md for coding agents, so a user's agent can write, run, and explain qc-use tests."""

import os
from pathlib import Path

SKILL = Path(__file__).with_name("SKILL.md")
TARGETS = ("agents", "claude", "codex", "copilot", "cursor", "gemini", "opencode")


def locations():
    """agent -> (folder that shows the agent is installed, where its skill goes). ~/.agents is always written."""
    home = Path.home()
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    folders = {name: home / f".{name}" for name in TARGETS if name != "opencode"}
    folders["codex"] = Path(os.environ.get("CODEX_HOME") or home / ".codex")
    folders["opencode"] = config / "opencode"
    return {name: (folder, folder / "skills" / "qc-use" / "SKILL.md") for name, folder in folders.items()}


def text():
    return SKILL.read_text(encoding="utf-8")


def install(targets=None, path=None):
    """Write the skill for every detected agent, for the named agents, or to one exact path."""
    places = locations()
    if path:
        destination = Path(path).expanduser()
        # A folder, or any path that does not name a .md file, gets SKILL.md inside it.
        if destination.is_dir() or destination.suffix.lower() != ".md":
            destination = destination / "SKILL.md"
        destinations = [("custom", destination)]
    else:
        names = targets or [name for name, (folder, _) in places.items() if name == "agents" or folder.is_dir()]
        unknown = [name for name in names if name not in places]
        if unknown:
            raise ValueError(f"Unknown agent: {', '.join(unknown)}. Choose from {', '.join(TARGETS)} or all.")
        destinations = [(name, places[name][1]) for name in names]
    lines = []
    for name, destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(text(), encoding="utf-8")
        lines.append(f"✓ {name}: {destination}")
    lines.append("Restart your coding agent, then ask it to QA a flow, e.g. “test our onboarding critical path”.")
    return lines


def status():
    """Compare installed skill copies with this package without changing them."""
    result = []
    for name, (folder, path) in locations().items():
        if name != "agents" and not folder.is_dir():
            continue
        try:
            state = "current" if path.read_text(encoding="utf-8") == text() else "outdated or modified"
        except FileNotFoundError:
            state = "missing"
        except OSError:
            state = "unreadable"
        result.append({"agent": name, "path": str(path), "status": state})
    return result
