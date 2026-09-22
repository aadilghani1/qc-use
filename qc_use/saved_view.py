"""Open saved, masked run evidence in the existing read-only inspector."""

import threading
from pathlib import Path
from types import SimpleNamespace

from .report import SCHEMA, Report
from .watch import Watch


class SavedView(Watch):
    """Serve step evidence without starting Chrome or calling a model."""

    def __init__(self, path):
        path = Path(path).expanduser().resolve()
        path = path / "report.json" if path.is_dir() else path
        report = Report.model_validate_json(path.read_text(encoding="utf-8"))
        if report.schema_version != SCHEMA:
            raise ValueError(f"Unsupported report schema: {report.schema_version}")
        if not report.steps or [s.index for s in report.steps] != list(range(1, len(report.steps) + 1)):
            raise ValueError("Report steps must be numbered from 1 without gaps.")
        super().__init__(
            SimpleNamespace(
                title=report.test.get("title", "Saved run"),
                url=report.test.get("url", ""),
                secrets=[],
                steps=[SimpleNamespace(text=s.text, expect=[]) for s in report.steps],
            )
        )
        self.report = report
        self.root = path.parent
        self.state.update(status=report.outcome, summary=report.summary, elapsed_ms=report.elapsed_ms, saved=True)
        for step in report.steps:
            self.record(step)

    def view(self, index=None):
        """Select a saved step; paths can only address images inside this run folder."""
        if index is None:
            index = next(
                (i for i in reversed(range(len(self.report.steps))) if self.report.steps[i].outcome != "skipped"), 0
            )
        if not 0 <= index < len(self.report.steps):
            raise IndexError("Invalid step")
        step = self.report.steps[index]
        screenshot = b""
        reason = step.screenshot_reason or "No screenshot was saved for this step."
        if step.screenshot:
            image = (self.root / step.screenshot).resolve()
            if image.is_relative_to(self.root) and image.suffix.lower() in {".jpg", ".jpeg"}:
                try:
                    screenshot = image.read_bytes()
                    if not screenshot.startswith(b"\xff\xd8\xff"):
                        screenshot = b""
                except OSError:
                    pass
            if not screenshot:
                reason = "The saved screenshot is missing or is not a local JPEG."
        return {
            **self.state,
            "current": index,
            "shot": index,
            "has_screenshot": bool(screenshot),
            "screenshot_reason": reason,
            "page": {"url": step.url or "", "title": f"Step {step.index}: {step.text}"},
            "actions": [a.model_dump() for a in step.actions],
            "action_count": len(step.actions),
        }, screenshot


def serve(path, open_browser=True, echo=print):
    """Keep a saved view available until the user presses Ctrl+C."""
    view = SavedView(path)
    view.open(echo, open_browser=open_browser, label="Saved report")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        return 0
    finally:
        view.close()
