"""Secrets are named in the test and resolved locally. Their values never reach a model, a trace, or a report."""

import os
from pathlib import Path

MIN_MASKED = 4  # Shorter values would mask ordinary words; `doctor` warns about them.


def read_env_file(path):
    values = {}
    path = Path(path)
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_env(directory):
    """Make `qa/.env` values available (keys included) without overriding the real environment."""
    for key, value in read_env_file(Path(directory) / ".env").items():
        os.environ.setdefault(key, value)


def resolve(names):
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise KeyError(", ".join(missing))
    return {name: os.environ[name] for name in names}


class Redactor:
    """Replace every secret value in any JSON-like structure with [secret:NAME]."""

    def __init__(self, secrets):
        self.pairs = sorted(
            ((value, f"[secret:{name}]") for name, value in secrets.items() if len(value) >= MIN_MASKED),
            key=lambda pair: -len(pair[0]),
        )

    def text(self, value):
        for secret, mask in self.pairs:
            value = value.replace(secret, mask)
        return value

    def __call__(self, value):
        if not self.pairs:
            return value
        if isinstance(value, str):
            return self.text(value)
        if isinstance(value, dict):
            return {self(k): self(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self(v) for v in value]
        return value
