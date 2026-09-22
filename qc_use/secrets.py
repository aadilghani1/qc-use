"""Secrets are named in the test and resolved locally. Their values never reach a model, a trace, or a report."""

import os
from contextlib import contextmanager
from pathlib import Path

MIN_MASKED = 4  # Short values cannot be distinguished from ordinary page words safely.


def read_env_file(path):
    values = {}
    path = Path(path)
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_env(directory):
    """Make `qa/.env` values available (keys included) without overriding the real environment."""
    for key, value in read_env_file(Path(directory) / ".env").items():
        if value:
            os.environ.setdefault(key, value)


def resolve(names, templates=(), tag=None):
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        raise KeyError(", ".join(missing))
    short = [name for name in names if len(os.environ[name]) < MIN_MASKED]
    if short:
        raise ValueError(f"Secrets must have at least {MIN_MASKED} characters: {', '.join(short)}. Nothing ran.")
    values = {name: os.environ[name] for name in names}
    for name in templates:
        if not tag or name not in values or "{tag}" not in values[name]:
            raise ValueError(f"Secret template {name} needs a {{tag}} placeholder and a run tag.")
        values[name] = values[name].replace("{tag}", tag)
    return values


class Redactor:
    """Replace every secret value in any JSON-like structure with [secret:NAME]."""

    def __init__(self, secrets):
        self.pairs = sorted(
            ((value, f"[secret:{name}]") for name, value in secrets.items() if value),
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
            return {k: self(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [self(v) for v in value]
        return value


@contextmanager
def environment(*directories):
    """Load one command's files without retaining their values in the next command."""
    original = dict(os.environ)
    try:
        for directory in directories:
            load_env(directory)
        yield
    finally:
        os.environ.clear()
        os.environ.update(original)
