"""qc-use: critical-path QA in plain words. Powered by TypeSafe Jev."""

import argparse
import glob
import json
import os
import shlex
import sys
from functools import partial
from pathlib import Path

from . import __version__, build_identity

MARK = {"pass": "✅", "fail": "❌", "inconclusive": "❔", "blocked": "⛔", "needs_approval": "✋"}


def test_files(patterns):
    """Expand file patterns consistently across shells, without repeating a test."""
    found: dict[str, str] = {}
    for pattern in patterns:
        matches = [pattern] if Path(pattern).exists() else sorted(glob.glob(pattern, recursive=True)) or [pattern]
        for path in matches:
            found.setdefault(str(Path(path).resolve()), path)
    return list(found.values())


def ask_person(rule, action, probability):
    print(f"\n  ✋ '{action}' may break the rule 'never {rule}' ({probability:.0%}).")
    try:
        answer = input("     Allow it for the rest of this run? [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in {"y", "yes"}


def run_command(args):
    from .report import SETUP_ERROR
    from .runner import SetupError, run
    from .secrets import Redactor, load_env
    from .spec import SpecError, load, rebase

    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not (args.json or args.json_result)
    output = partial(print, flush=True) if not (args.json or args.json_result) else (lambda *_: None)
    redact = Redactor({})

    def echo(message):
        output(redact.text(message))

    def notice(message):
        print(redact.text(message), file=sys.stderr, flush=True)

    codes, reports, setup_errors, redactors = [], [], [], []
    kept_live = None
    initial_environment = dict(os.environ)

    def setup_error(file, message):
        print(redact.text(f"qc-use: {message}"), file=sys.stderr)
        setup_errors.append({"file": str(file), "error": redact.text(str(message))})
        codes.append(SETUP_ERROR)

    try:
        for file in test_files(args.files):
            os.environ.clear()
            os.environ.update(initial_environment)
            redact = Redactor({})
            try:
                spec = load(file)
            except (SpecError, OSError) as error:
                setup_error(file, error)
                continue
            try:
                for folder in (spec.path.parent, Path.cwd()):
                    load_env(folder)
            except (OSError, UnicodeError):
                setup_error(file, f"Cannot read {folder / '.env'}. Check UTF-8 encoding and file permissions.")
                continue
            redact = Redactor({name: os.environ.get(name, "") for name in spec.secrets})
            redactors.append(redact)
            if args.base_url:
                try:
                    spec = rebase(spec, args.base_url)
                except SpecError as error:
                    setup_error(file, error)
                    continue
            if args.repeat > 1 and not spec.repeat_safe:
                setup_error(file, "repeat needs repeat_safe: true and equivalent test account state for each run.")
                continue
            if args.manual_auth and (args.headless or not args.profile or not interactive):
                setup_error(file, "--manual-auth needs an interactive terminal, --profile, and visible Chrome.")
                continue
            for attempt in range(args.repeat):
                label = f" (run {attempt + 1}/{args.repeat})" if args.repeat > 1 else ""
                echo(f"qc-use · {spec.title}{label} · {spec.url}")
                live = None
                try:
                    if args.watch:
                        from .watch import Watch

                        live = Watch.start(spec, notice)
                    report = run(
                        spec,
                        allow=args.allow,
                        allow_production=args.allow_production,
                        approve=ask_person if interactive else None,
                        profile=args.profile,
                        headless=args.headless,
                        manual_auth=(lambda: input("Sign in in the private Chrome window, then press Enter here: "))
                        if args.manual_auth
                        else None,
                        results_dir=args.results,
                        live=live,
                        screenshots=not args.no_screenshots,
                        echo=echo,
                    )
                except KeyboardInterrupt:
                    if live:
                        live.finish()
                    raise
                except (SetupError, RuntimeError, ValueError, TimeoutError, OSError) as error:
                    setup_error(file, error)
                    if live:
                        live.finish()
                    break
                if live:
                    keep_open = args.keep_open and report.exit_code != 130
                    live.finish(report, keep_open=keep_open)
                    if keep_open:
                        kept_live = live
                    folder = str(Path(report.artifacts["folder"]).resolve())
                    quoted = "'" + folder.replace("'", "''") + "'" if sys.platform == "win32" else shlex.quote(folder)
                    notice(f"Reopen saved evidence: qc-use report {quoted}")
                reports.append(report)
                codes.append(report.exit_code)
                cost = f"${report.cost.usd:.8f}{' est.' if report.cost.estimated else ''}"
                seconds = report.elapsed_ms / 1000
                echo(f"{MARK[report.outcome]} {report.outcome} · {report.summary} ({seconds:.1f} s, {cost})")
                echo(f"   {Path(report.artifacts['folder']) / 'report.md'}\n")
                if report.exit_code == 130:
                    break
            if codes and codes[-1] == 130:
                break
            if args.repeat > 1:
                runs = [r for r in reports if r.test["file"] == str(spec.path)]
                passed = sum(r.outcome == "pass" for r in runs)
                echo(f"Pass rate for {spec.title}: {passed}/{len(runs)}")
        write_summaries(args, reports, setup_errors, redactors)
        if args.json_result:
            from .report import CommandResult

            result = CommandResult(
                reports=reports, setup_errors=setup_errors, exit_code=max(codes, default=SETUP_ERROR)
            )
            for redactor in redactors:
                result = result.redacted(redactor)
            print(result.model_dump_json(indent=2), flush=True)
        elif args.json:
            payload = [r.model_dump(mode="json") for r in reports]
            print(json.dumps(payload[0] if len(payload) == 1 else payload, indent=2), flush=True)
        if kept_live:
            kept_live.hold(notice)
        return max(codes, default=SETUP_ERROR)
    finally:
        if kept_live:
            kept_live.close()


def write_summaries(args, reports, setup_errors, redactors):
    """Write the CI summary files from data that passed through every run's Redactor."""
    from .summary import junit, markdown_summary

    if not (args.summary or args.junit):
        return
    # Redact before formatting: XML escaping would hide a secret that contains & or < from a later text pass.
    for redact in redactors:
        reports = [report.redacted(redact) for report in reports]
        setup_errors = redact(setup_errors)
    if args.summary:
        # Append, because CI summary files such as $GITHUB_STEP_SUMMARY can hold other steps' output.
        with Path(args.summary).open("a", encoding="utf-8") as file:
            file.write(markdown_summary(reports, setup_errors))
    if args.junit:
        path = Path(args.junit)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(junit(reports, setup_errors), encoding="utf-8")


def init_command(args):
    from .scaffold import init

    for line in init(Path(args.directory)):
        print(line)
    return 0


def demo_command(args):
    from .demo import main

    return main(port=args.port, serve_only=args.serve, headless=args.headless, results=args.results, watch=args.watch)


def skill_command(args):
    from .report import SETUP_ERROR
    from .skill import TARGETS, install, status, text

    if args.action == "status":
        print(json.dumps(status(), indent=2))
        return 0
    if args.action == "print":
        print(text(), end="")
        return 0
    targets = list(TARGETS) if args.target == "all" else [args.target] if args.target else None
    try:
        lines = install(targets=targets, path=args.path)
    except (ValueError, OSError) as error:
        print(f"qc-use: Cannot install the skill: {error}", file=sys.stderr)
        return SETUP_ERROR
    for line in lines:
        print(line)
    return 0


def doctor_command(args):
    from .doctor import doctor

    return doctor(args.file, json_output=args.json)


def schema_command(args):
    from pydantic import BaseModel

    from .report import CommandResult, Report
    from .spec import TestSpec

    models: dict[str, type[BaseModel]] = {"report": Report, "test": TestSpec, "command": CommandResult}
    model = models[args.kind]
    print(json.dumps(model.model_json_schema(), indent=2))
    return 0


def validate_command(args):
    """Validate test files without credentials, network calls, or Chrome."""
    from .report import SETUP_ERROR
    from .spec import SpecError, load

    results = []
    for path in test_files(args.files):
        try:
            spec = load(path)
            results.append({"file": str(path), "valid": True, "title": spec.title, "steps": len(spec.steps)})
        except (SpecError, OSError) as error:
            results.append({"file": str(path), "valid": False, "error": str(error)})
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            print(f"{result['file']}: " + (f"valid ({result['steps']} steps)" if result["valid"] else result["error"]))
    return 0 if all(r["valid"] for r in results) else SETUP_ERROR


def report_command(args):
    """Serve a saved report through the existing local inspector."""
    from .report import SETUP_ERROR
    from .saved_view import serve

    try:
        return serve(args.path, open_browser=not args.no_open)
    except (OSError, ValueError) as error:
        print(f"qc-use: Cannot open report: {error}", file=sys.stderr)
        return SETUP_ERROR


def parser():
    root = argparse.ArgumentParser(prog="qc-use", description=__doc__)
    root.add_argument("--version", action="version", version=f"qc-use {__version__} ({build_identity()[:12]})")
    commands = root.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run one or more test files, e.g. qa/onboarding.md")
    run.add_argument("files", nargs="+")
    run.add_argument(
        "--allow",
        action="append",
        default=[],
        metavar="RULE",
        help="Allow a never-do rule for this run (exact rule text, or '*' for all).",
    )
    run.add_argument("--allow-production", action="store_true", help="Run against a URL that looks like production.")
    run.add_argument("--profile", help="Reuse a Chrome profile folder instead of a fresh one (e.g. to stay logged in).")
    run.add_argument(
        "--manual-auth", action="store_true", help="Pause in visible Chrome for manual sign-in before testing."
    )
    run.add_argument("--headless", action="store_true", help="Run Chrome without a window.")
    run.add_argument("--watch", action="store_true", help="Open the live inspector while the test runs.")
    run.add_argument(
        "--repeat",
        type=int,
        default=1,
        metavar="N",
        help="Run N times; requires repeat_safe: true. Profiles do not reset server accounts.",
    )
    run.add_argument("--results", default="qa-results", help="Where run folders are written (default qa-results).")
    run.add_argument(
        "--base-url",
        metavar="URL",
        help="Start on this origin instead, keeping each test's path, e.g. a preview deployment.",
    )
    run.add_argument("--junit", metavar="FILE", help="Write JUnit XML with one test case for each step.")
    run.add_argument("--summary", metavar="FILE", help="Append a Markdown summary table, e.g. to $GITHUB_STEP_SUMMARY.")
    run.add_argument("--no-screenshots", action="store_true", help="Do not save step screenshots.")
    run.add_argument(
        "--keep-open", action="store_true", help="Keep one watched run open until Ctrl+C; requires --watch."
    )
    json_flags = run.add_mutually_exclusive_group()
    json_flags.add_argument("--json", action="store_true", help="Print report.json to stdout instead of progress.")
    json_flags.add_argument(
        "--json-result", action="store_true", help="Print reports and setup errors in a command result."
    )
    run.set_defaults(handler=run_command)

    init = commands.add_parser("init", help="Create qa/ with an example test and ignore rules.")
    init.add_argument("directory", nargs="?", default=".")
    init.set_defaults(handler=init_command)

    demo = commands.add_parser("demo", help="Run the bundled demo app and its example test.")
    demo.add_argument("--serve", action="store_true", help="Only serve the demo app.")
    demo.add_argument("--port", type=int, default=3100)
    demo.add_argument("--headless", action="store_true")
    demo.add_argument("--watch", action="store_true", help="Open the live inspector for each demo run.")
    demo.add_argument("--results", default="qa-results", help="Where demo run folders are written.")
    demo.set_defaults(handler=demo_command)

    skill = commands.add_parser("skill", help="Print or install the coding-agent skill.")
    skill.add_argument("action", nargs="?", choices=["print", "install", "status"], default="print")
    skill.add_argument("--target", help="One agent (claude, codex, cursor, gemini, copilot, opencode, agents) or all.")
    skill.add_argument("--path", help="Write SKILL.md to this exact path instead.")
    skill.set_defaults(handler=skill_command)

    doctor = commands.add_parser("doctor", help="Check Chrome, inference keys, and optionally a test file.")
    doctor.add_argument("file", nargs="?")
    doctor.add_argument("--json", action="store_true", help="Print structured setup checks and build identity.")
    doctor.set_defaults(handler=doctor_command)

    validate = commands.add_parser("validate", help="Check test files offline without running them.")
    validate.add_argument("files", nargs="+")
    validate.add_argument("--json", action="store_true")
    validate.set_defaults(handler=validate_command)

    report = commands.add_parser("report", help="Open a saved run folder or report.json in the inspector.")
    report.add_argument("path")
    report.add_argument("--no-open", action="store_true", help="Print the local URL without opening a browser.")
    report.set_defaults(handler=report_command)

    schema = commands.add_parser("schema", help="Print the JSON schema of a report, test, or command result.")
    schema.add_argument("kind", choices=["report", "test", "command"])
    schema.set_defaults(handler=schema_command)
    return root


def main(argv=None):
    from .report import SETUP_ERROR

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    if getattr(args, "keep_open", False) and (not args.watch or args.repeat != 1 or len(test_files(args.files)) != 1):
        print("qc-use: --keep-open requires --watch, one test file, and --repeat 1.", file=sys.stderr)
        return SETUP_ERROR
    if getattr(args, "repeat", 1) < 1:
        print("qc-use: --repeat must be at least 1", file=sys.stderr)
        return SETUP_ERROR
    from .secrets import environment

    try:
        with environment():
            return args.handler(args)
    except KeyboardInterrupt:
        print("\nqc-use: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
