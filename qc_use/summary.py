"""Combine the reports of one command into a Markdown summary and JUnit XML for CI."""

import re
import xml.etree.ElementTree as ET

from .report import MARK

# XML 1.0 cannot hold most control characters, and page text can contain them.
INVALID_XML = re.compile(r"[^\t\n\r\x20-\ud7ff\ue000-\ufffd\U00010000-\U0010ffff]")
PROBLEMS = {"fail": "failure", "inconclusive": "error", "blocked": "error", "needs_approval": "error"}


def cell(text):
    """Keep one Markdown table cell on one line."""
    return " ".join(str(text).split()).replace("|", "\\|")


def seconds(ms):
    return f"{ms / 1000:.1f}"


def markdown_summary(reports, setup_errors):
    """One table row for each run, then each test file that did not run."""
    lines = ["## qc-use results", ""]
    if reports:
        lines += ["| | Test | Steps passed | Time | Cost | Summary |", "| --- | --- | --- | --- | --- | --- |"]
        for report in reports:
            passed = sum(step.outcome == "pass" for step in report.steps)
            cost = f"${report.cost.usd:.4f}{' est.' if report.cost.estimated else ''}"
            lines.append(
                f"| {MARK[report.outcome]} | {cell(report.test['title'])} | {passed}/{len(report.steps)} | "
                f"{seconds(report.elapsed_ms)} s | {cost} | {cell(report.summary)} |"
            )
        lines.append("")
        lines += [f"- {cell(r.test['title'])}: `{r.artifacts['folder']}/report.md`" for r in reports]
        lines.append("")
    if setup_errors:
        lines += ["### Setup errors", "", *(f"- `{e['file']}`: {cell(e['error'])}" for e in setup_errors), ""]
    if not reports and not setup_errors:
        lines += ["No test ran.", ""]
    return "\n".join(lines) + "\n"


def junit(reports, setup_errors):
    """One test suite for each run and one test case for each step, so CI shows where a path stopped."""
    root = ET.Element("testsuites", name="qc-use")
    totals = dict.fromkeys(("tests", "failures", "errors", "skipped"), 0)
    for report in reports:
        suite = ET.SubElement(root, "testsuite", name=report.test["title"], timestamp=report.started_at)
        properties = ET.SubElement(suite, "properties")
        for name, value in (
            ("file", report.test["file"]),
            ("url", report.test["url"]),
            ("outcome", report.outcome),
            ("run_id", report.run_id),
            ("report", f"{report.artifacts['folder']}/report.md"),
        ):
            ET.SubElement(properties, "property", name=name, value=value)
        counts = dict.fromkeys(totals, 0)
        cases = [(f"{step.index}. {step.text}", step.elapsed_ms, step.outcome, step.reason) for step in report.steps]
        cases += [
            (
                f"rating: {r.name}",
                0,
                "fail" if r.outcome == "fail" else "pass",
                f"rated '{r.label}', below '{r.minimum}'",
            )
            for r in report.ratings
            if r.minimum is not None
        ]
        if report.outcome != "pass" and not any(outcome in PROBLEMS for _, _, outcome, _ in cases):
            # A provider outage or a cleanup failure can stop a run after every step passed.
            cases.append(("run", 0, report.outcome, report.summary))
        for name, ms, outcome, reason in cases:
            case = ET.SubElement(suite, "testcase", classname=report.test["file"], name=name, time=seconds(ms))
            counts["tests"] += 1
            if outcome == "skipped":
                ET.SubElement(case, "skipped", message="Not run: an earlier step did not pass.")
                counts["skipped"] += 1
            elif outcome in PROBLEMS:
                kind = PROBLEMS[outcome]
                ET.SubElement(case, kind, type=outcome, message=reason or outcome).text = reason or outcome
                counts[f"{kind}s"] += 1
        suite.set("time", seconds(report.elapsed_ms))
        for key, value in counts.items():
            suite.set(key, str(value))
            totals[key] += value
    for error in setup_errors:
        suite = ET.SubElement(root, "testsuite", name=error["file"], tests="1", failures="0", errors="1", skipped="0")
        case = ET.SubElement(suite, "testcase", classname=error["file"], name="setup", time="0.0")
        ET.SubElement(case, "error", type="setup_error", message=error["error"]).text = error["error"]
        totals["tests"] += 1
        totals["errors"] += 1
    for key, value in totals.items():
        root.set(key, str(value))
    ET.indent(root)
    text = '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"
    return INVALID_XML.sub("", text)
