"""The run's answer: report.json for agents and CI, report.md for people. Every number comes from the trace."""

from typing import Literal, get_origin

from pydantic import BaseModel, ConfigDict, Field

from .engine.answers import Probability

Outcome = Literal["pass", "fail", "inconclusive"]
StepOutcome = Literal["pass", "fail", "inconclusive", "blocked", "needs_approval", "skipped"]
TestOutcome = Literal["pass", "fail", "inconclusive", "blocked", "needs_approval"]
EXIT_CODES = {"pass": 0, "fail": 1, "inconclusive": 2, "blocked": 2, "needs_approval": 3}
SETUP_ERROR = 4  # Invalid test file, missing secret or key, refused URL: nothing ran.
SCHEMA = "qc-use.report/1"


class ReportModel(BaseModel):
    """Reject non-finite numbers in report data."""

    model_config = ConfigDict(allow_inf_nan=False)

    def redacted(self, redact):
        """Mask data without rewriting code-owned field names or outcome literals."""

        def value(item):
            if isinstance(item, ReportModel):
                return {
                    name: getattr(item, name) if get_origin(field.annotation) is Literal else value(getattr(item, name))
                    for name, field in type(item).model_fields.items()
                }
            if isinstance(item, list):
                return [value(part) for part in item]
            return redact(item)

        return type(self).model_validate(value(self))


class CheckResult(ReportModel):
    kind: Literal["expect", "implicit", "check", "signal"]
    text: str
    outcome: Outcome
    probability: Probability | None = None


class ActionRecord(ReportModel):
    action: str
    kind: str
    operation: str
    target: str | None
    probability: Probability
    confidence: Probability
    latency_ms: int
    text: str | None = None
    text_source: str | None = None
    page_changed: bool | None = None
    url: str
    elapsed_ms: int


class Signal(ReportModel):
    kind: str
    text: str


class Dialog(ReportModel):
    type: str
    message: str
    accepted: bool


class GeneratedValue(ReportModel):
    field: str
    value: str
    source: str


class StepResult(ReportModel):
    index: int
    text: str
    outcome: StepOutcome
    reason: str | None = None
    checks: list[CheckResult] = []
    actions: list[ActionRecord] = []
    signals: list[Signal] = []
    dialogs: list[Dialog] = []
    generated: list[GeneratedValue] = []
    decisions: int = 0
    elapsed_ms: int = 0
    url: str | None = None
    screenshot: str | None = None


class RatingResult(ReportModel):
    name: str
    levels: list[str]
    level: int
    label: str
    score: float
    probabilities: dict[str, Probability]
    confidence: Probability
    minimum: str | None = None
    outcome: Literal["pass", "fail", "info"]


class Approval(ReportModel):
    step: int
    rule: str
    action: str
    probability: Probability
    rerun_with: str


class Cost(ReportModel):
    usd: float = Field(ge=0)
    estimated: bool
    model_calls: int
    unpriced_calls: int
    cap: float = Field(gt=0)


class Report(ReportModel):
    schema_version: str = SCHEMA
    run_id: str
    test: dict[str, str]
    started_at: str
    elapsed_ms: int
    outcome: TestOutcome
    exit_code: int
    summary: str
    steps: list[StepResult]
    ratings: list[RatingResult] = []
    approval: Approval | None = None
    cost: Cost
    models: dict[str, str]
    artifacts: dict[str, str]


MARK = {"pass": "✅", "fail": "❌", "inconclusive": "❔", "blocked": "⛔", "needs_approval": "✋", "skipped": "⏭️"}


def plural(count, noun):
    return f"{count} {noun}{'' if count == 1 else 's'}"


def markdown(report):
    lines = [
        f"# {MARK[report.outcome]} {report.test['title']}: {report.outcome.replace('_', ' ')}",
        "",
        report.summary,
        "",
        f"`{report.test['url']}` · {report.elapsed_ms / 1000:.1f} s · "
        f"${report.cost.usd:.4f}{' (estimated)' if report.cost.estimated else ''} · "
        f"{report.cost.model_calls} model calls · run `{report.run_id}`",
        "",
    ]
    if report.approval:
        a = report.approval
        lines += [
            "## Needs approval",
            "",
            f"Step {a.step} stopped before **{a.action}**: it may break the rule *never {a.rule}* "
            f"({a.probability:.0%}). If this is expected, rerun with `{a.rerun_with}`.",
            "",
        ]
    lines += ["## Steps", ""]
    for step in report.steps:
        lines.append(f"### {MARK[step.outcome]} {step.index}. {step.text}")
        lines.append("")
        if step.outcome == "skipped":
            lines += ["Not run: an earlier step did not pass.", ""]
            continue
        facts = [
            plural(len(step.actions), "action"),
            plural(step.decisions, "decision"),
            f"{step.elapsed_ms / 1000:.1f} s",
        ]
        lines += [" · ".join(facts), ""]
        if step.reason:
            lines += [f"**Why:** {step.reason}", ""]
        for check in step.checks:
            p = f" ({check.probability:.0%})" if check.probability is not None else ""
            lines.append(f"- {MARK[check.outcome]} {check.kind}: {check.text}{p}")
        if step.checks:
            lines.append("")
        for value in step.generated:
            lines.append(f"- Generated test value for *{value.field}*: `{value.value}`")
        for dialog in step.dialogs:
            verb = "accepted" if dialog.accepted else "dismissed"
            lines.append(f"- Dialog ({dialog.type}) {verb}: “{dialog.message}”")
        for signal in step.signals:
            lines.append(f"- Signal `{signal.kind}`: {signal.text}")
        if step.generated or step.dialogs or step.signals:
            lines.append("")
        if step.actions:
            lines += ["<details><summary>Actions</summary>", ""]
            for i, action in enumerate(step.actions, 1):
                typed = f" ← `{action.text}`" if action.text else ""
                lines.append(
                    f"{i}. {action.operation} **{action.action}**{typed} · {action.probability:.0%} · "
                    f"{action.latency_ms} ms"
                )
            lines += ["", "</details>", ""]
        if step.screenshot:
            lines += [f"![Step {step.index}]({step.screenshot})", ""]
    if report.ratings:
        lines += ["## Ratings", ""]
        for rating in report.ratings:
            spread = ", ".join(f"{rating.levels[int(k)]} {p:.0%}" for k, p in rating.probabilities.items() if p >= 0.01)
            limit = f" · minimum *{rating.minimum}*: {rating.outcome}" if rating.minimum else ""
            lines.append(
                f"- **{rating.name.replace('_', ' ')}**: most likely *{rating.label}* "
                f"(confidence {rating.confidence:.0%}; {spread}){limit}"
            )
        lines += ["", "Ratings are Jev's judgment from the run's evidence, not measurements.", ""]
    lines += [
        "---",
        f"Jev `{report.models['policy']}` via {report.models['route']} · text helper `{report.models['text']}` · "
        f"[report.json]({report.artifacts['json']}) · [trace]({report.artifacts['trace']})",
    ]
    return "\n".join(lines) + "\n"
