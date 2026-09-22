"""Offline contracts for CI outputs: the Markdown summary, JUnit XML, and preview base URLs."""

import xml.etree.ElementTree as ET
from unittest.mock import Mock

import pytest

from qc_use import cli, runner
from qc_use.report import Cost, RatingResult, Report, StepResult
from qc_use.spec import SpecError, Step, TestSpec, rebase
from qc_use.summary import junit, markdown_summary

TEST = "---\nurl: http://localhost:3000/login?next=/home\nsecrets: [PASSWORD]\n---\n# Sign in\n\n1. Sign in\n"


def report(outcome="fail", steps=None, ratings=(), summary="Step 2 of 3 failed: expect fail: the dashboard"):
    steps = steps or [
        StepResult(index=1, text="Sign in", outcome="pass", elapsed_ms=1200),
        StepResult(index=2, text="Open <reports> & filters", outcome="fail", reason="expect fail: the dashboard"),
        StepResult(index=3, text="Export", outcome="skipped"),
    ]
    return Report(
        run_id="20260922-120000-abcd",
        test={"title": "Sign in", "file": "qa/sign-in.md", "url": "http://localhost:3000/login"},
        started_at="2026-09-22T12:00:00+00:00",
        elapsed_ms=4200,
        outcome=outcome,
        exit_code=0,
        summary=summary,
        steps=steps,
        ratings=list(ratings),
        cost=Cost(usd=0.0012, estimated=False, model_calls=9, unpriced_calls=0, cap=0.25),
        models={},
        artifacts={"folder": "qa-results/20260922-120000-abcd"},
    )


def cases(xml):
    root = ET.fromstring(xml)
    return root, {case.get("name"): case for case in root.iter("testcase")}


def test_junit_has_one_case_for_each_step_and_required_rating():
    rating = RatingResult(
        name="ease",
        levels=["hard", "ok", "easy"],
        level=0,
        label="hard",
        score=0.1,
        probabilities={"0": 0.8, "1": 0.1, "2": 0.1},
        confidence=0.8,
        minimum="ok",
        outcome="fail",
    )
    root, found = cases(junit([report(ratings=[rating])], []))
    assert (root.get("tests"), root.get("failures"), root.get("errors"), root.get("skipped")) == ("4", "2", "0", "1")
    assert found["1. Sign in"].find("*") is None and found["1. Sign in"].get("time") == "1.2"
    assert found["2. Open <reports> & filters"].find("failure").get("message") == "expect fail: the dashboard"
    assert found["3. Export"].find("skipped") is not None
    assert "below 'ok'" in found["rating: ease"].find("failure").get("message")


@pytest.mark.parametrize("outcome", ["blocked", "inconclusive", "needs_approval"])
def test_junit_reports_stops_as_errors_not_app_failures(outcome):
    steps = [StepResult(index=1, text="Pay", outcome=outcome, reason="stopped here")]
    root, found = cases(junit([report(outcome, steps)], []))
    assert found["1. Pay"].find("error").get("type") == outcome
    assert root.get("failures") == "0" and root.get("errors") == "1"


def test_junit_marks_a_run_that_stopped_after_every_step_passed():
    steps = [StepResult(index=1, text="Save", outcome="pass")]
    _, found = cases(junit([report("blocked", steps, summary="Provider unavailable")], []))
    assert found["run"].find("error").get("message") == "Provider unavailable"


def test_junit_stays_valid_xml_with_control_characters():
    steps = [StepResult(index=1, text="Read \x00\x1b page", outcome="fail", reason="bad \x07 text")]
    _, found = cases(junit([report("fail", steps)], [{"file": "qa/x.md", "error": "bad \x0b file"}]))
    assert "1. Read  page" in found and found["setup"].find("error").get("message") == "bad  file"


def test_summary_is_a_one_line_row_for_each_run():
    text = markdown_summary([report(summary="Line one\nline | two")], [{"file": "qa/bad.md", "error": "no url"}])
    row = next(line for line in text.splitlines() if line.startswith("| ❌"))
    assert "1/3" in row and "4.2 s" in row and "$0.0012" in row and "Line one line \\| two" in row
    assert "- `qa/bad.md`: no url" in text and "qa-results/20260922-120000-abcd/report.md" in text


def test_ci_files_hold_setup_errors_without_secret_values(tmp_path, monkeypatch):
    secret = "ci-password-<&>"
    monkeypatch.setenv("PASSWORD", secret)
    (tmp_path / "test.md").write_text(TEST)
    monkeypatch.setattr(runner, "run", Mock(side_effect=runner.SetupError(f"Refused {secret}")))
    summary, xml = tmp_path / "summary.md", tmp_path / "out" / "junit.xml"
    (tmp_path / "summary.md").write_text("Earlier step output\n")
    code = cli.main(["run", str(tmp_path / "test.md"), "--summary", str(summary), "--junit", str(xml)])
    assert code == 4
    written = summary.read_text() + xml.read_text()
    assert summary.read_text().startswith("Earlier step output\n")
    assert secret not in written and "&lt;&amp;&gt;" not in written
    assert "Refused [secret:PASSWORD]" in written
    assert ET.fromstring(xml.read_text()).get("errors") == "1"


def test_ci_files_list_invalid_test_files(tmp_path):
    (tmp_path / "bad.md").write_text("1. No front matter\n")
    xml = tmp_path / "junit.xml"
    assert cli.main(["run", str(tmp_path / "bad.md"), "--junit", str(xml)]) == 4
    _, found = cases(xml.read_text())
    assert "front matter" in found["setup"].find("error").get("message")


def test_base_url_moves_the_start_origin_and_keeps_the_path():
    spec = TestSpec(title="T", url="http://localhost:3000/login?next=/home", steps=[Step(text="Go", expect=["x"])])
    moved = rebase(spec, "https://app-git-fix.preview.example.test")
    assert moved.url == "https://app-git-fix.preview.example.test/login?next=/home"
    assert moved.steps == spec.steps and spec.url.startswith("http://localhost")


@pytest.mark.parametrize(
    "base", ["https://preview.test/app", "preview.test", "ftp://preview.test", "https://x.test/?a"]
)
def test_base_url_must_be_an_http_origin(base):
    spec = TestSpec(title="T", url="http://localhost:3000/login", steps=[Step(text="Go", expect=["x"])])
    with pytest.raises(SpecError, match="--base-url"):
        rebase(spec, base)


def test_cli_runs_the_test_on_the_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("PASSWORD", "long-enough")
    (tmp_path / "test.md").write_text(TEST)
    run = Mock(side_effect=runner.SetupError("stop"))
    monkeypatch.setattr(runner, "run", run)
    cli.main(["run", str(tmp_path / "test.md"), "--base-url", "http://127.0.0.1:4000"])
    assert run.call_args.args[0].url == "http://127.0.0.1:4000/login?next=/home"
