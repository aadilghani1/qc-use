"""A test file: YAML front matter for settings, then numbered steps in plain words."""

import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

Signal = Literal["console_error", "js_exception", "http_4xx", "http_5xx", "request_failed"]
CHECK = re.compile(
    r"^(?P<subject>url|title|text)\s+(?P<verb>contains|matches|does not contain|absent)\s+(?P<value>.+)$", re.I
)
STEP = re.compile(r"^(\d+)[.)]\s+(.+)$")
DETAIL = re.compile(r"^\s+[-*]\s+(expect|check):\s*(.+)$", re.I)


class SpecError(ValueError):
    """The test file is invalid. The message says where and why."""


def unquote(value):
    value = value.strip()
    return value[1:-1] if len(value) > 1 and value[0] == value[-1] and value[0] in "\"'`" else value


class Check(BaseModel):
    """A deterministic check on the page after a step. Counts and dates belong here, not in `expect:`."""

    subject: Literal["url", "title", "text"]
    verb: Literal["contains", "matches", "absent"]
    value: str = Field(min_length=1)

    @classmethod
    def parse(cls, line):
        match = CHECK.match(line.strip())
        if not match:
            raise SpecError(
                f"Unknown check '{line}'. Use: url contains X, url matches REGEX, title contains X, "
                "text contains X, or text does not contain X."
            )
        verb = match["verb"].lower()
        verb = "absent" if verb in {"does not contain", "absent"} else verb
        if verb == "matches" and match["subject"].lower() != "url":
            raise SpecError(f"Only url supports 'matches': '{line}'")
        value = unquote(match["value"])
        if verb == "matches":
            try:
                re.compile(value)
            except re.error as error:
                raise SpecError(f"Invalid regular expression in '{line}': {error}") from None
        return cls(subject=match["subject"].lower(), verb=verb, value=value)

    def __str__(self):
        verb = "does not contain" if self.verb == "absent" else self.verb
        return f"{self.subject} {verb} {self.value}"

    def evaluate(self, page):
        subject = {"url": page["url"], "title": page["title"], "text": page["text"]}[self.subject]
        if self.verb == "matches":
            return re.search(self.value, subject) is not None
        found = self.value.casefold() in subject.casefold()
        return found if self.verb == "contains" else not found


class Step(BaseModel):
    text: str = Field(min_length=1)
    expect: list[str] = []
    check: list[Check] = []


class Rating(BaseModel):
    """A Jev score over the finished run. Levels go from worst to best."""

    levels: list[str] = Field(min_length=2, max_length=10)
    min: str | None = None  # Fail the test when the most likely level is below this one.

    @model_validator(mode="after")
    def known_minimum(self):
        if self.min is not None and self.min not in self.levels:
            raise ValueError(f"min '{self.min}' is not one of the levels")
        return self


class Budget(BaseModel):
    step: int = Field(15, ge=1, le=60)
    test: int = Field(60, ge=1, le=300)


class Bands(BaseModel):
    """Jev yes/no answers are probabilities. Between the bands a check is inconclusive, never a pass."""

    pass_at: float = Field(0.8, gt=0, le=1)
    fail_at: float = Field(0.2, ge=0, lt=1)

    @model_validator(mode="after")
    def ordered(self):
        if self.fail_at >= self.pass_at:
            raise ValueError("fail_at must be below pass_at")
        return self


class TestSpec(BaseModel):
    __test__ = False  # Not a pytest class.
    model_config = ConfigDict(extra="forbid")

    path: Path | None = None
    title: str
    intent: str = ""
    url: str
    allow: list[str] = []
    allow_production: bool = False
    secrets: list[str] = []
    files: dict[str, Path] = {}
    persona: dict[str, str | int | float | bool | list[str]] = {}
    never: list[str] = []
    never_defaults: bool = True
    never_threshold: float = Field(0.3, gt=0, lt=1)
    rate: dict[str, Rating] = {}
    fail_on: list[Signal] = []
    budget: Budget = Budget()
    bands: Bands = Bands()
    max_cost: float = Field(0.25, gt=0)
    steps: list[Step] = Field(min_length=1)

    @field_validator("url")
    @classmethod
    def web_url(cls, value):
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("must be an http(s) URL such as http://localhost:3000")
        return value

    @field_validator("secrets")
    @classmethod
    def secret_names(cls, names):
        for name in names:
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
                raise ValueError(f"'{name}' is not a valid environment variable name")
        return names

    @field_validator("rate", mode="before")
    @classmethod
    def level_lists(cls, rate):
        return {name: {"levels": r} if isinstance(r, list) else r for name, r in (rate or {}).items()}


def parse_body(body):
    """Split markdown into a title, an intent paragraph, and numbered steps with expect/check details."""
    title, intent, steps = None, [], []
    for line in body.splitlines():
        if not line.strip():
            continue
        if line.startswith("# ") and title is None and not steps:
            title = line[2:].strip()
        elif match := STEP.match(line):
            steps.append({"text": match[2].strip(), "expect": [], "check": []})
        elif (match := DETAIL.match(line)) and steps:
            kind, value = match[1].lower(), match[2].strip()
            steps[-1][kind].append(Check.parse(value) if kind == "check" else unquote(value))
        elif steps and line.startswith((" ", "\t")):
            steps[-1]["text"] += " " + line.strip()
        elif not steps:
            intent.append(line.strip())
    return title, " ".join(intent), steps


def load(path):
    path = Path(path)
    source = path.read_text()
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", source, re.S)
    if not match:
        raise SpecError(f"{path}: start the file with YAML front matter between --- lines (url: is required).")
    try:
        settings = yaml.safe_load(match[1]) or {}
    except yaml.YAMLError as error:
        raise SpecError(f"{path}: invalid front matter: {error}") from None
    if not isinstance(settings, dict):
        raise SpecError(f"{path}: front matter must be key: value settings.")
    title, intent, steps = parse_body(match[2])
    files = {name: (path.parent / file).resolve() for name, file in (settings.pop("files", None) or {}).items()}
    for name, file in files.items():
        if not file.is_file():
            raise SpecError(f"{path}: declared file '{name}' does not exist: {file}")
    try:
        return TestSpec(
            path=path.resolve(),
            title=settings.pop("title", None) or title or path.stem,
            intent=intent,
            steps=steps,
            files=files,
            **settings,
        )
    except ValidationError as error:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'file'}: {e['msg']}" for e in error.errors())
        raise SpecError(f"{path}: {problems}") from None
