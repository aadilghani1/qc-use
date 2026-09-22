"""qc-use: critical-path QA in plain words. Powered by TypeSafe Jev."""

import argparse
import json
import sys
from functools import partial
from pathlib import Path

from . import __version__

MARK = {"pass": "✅", "fail": "❌", "inconclusive": "❔", "blocked": "⛔", "needs_approval": "✋"}


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
    from .secrets import load_env
    from .spec import SpecError, load

    interactive = sys.stdin.isatty() and sys.stdout.isatty() and not args.json
    echo = partial(print, flush=True) if not args.json else (lambda *_: None)
    codes, reports = [], []
    for file in args.files:
        try:
            spec = load(file)
        except (SpecError, OSError) as error:
            print(f"qc-use: {error}", file=sys.stderr)
            codes.append(SETUP_ERROR)
            continue
        load_env(spec.path.parent)
        load_env(Path.cwd())
        for attempt in range(args.repeat):
            label = f" (run {attempt + 1}/{args.repeat})" if args.repeat > 1 else ""
            echo(f"qc-use · {spec.title}{label} · {spec.url}")
            live = None
            if args.watch:
                from .watch import Watch

                live = Watch.start(spec, echo)
            try:
                report = run(
                    spec, allow=args.allow, allow_production=args.allow_production,
                    approve=ask_person if interactive else None, profile=args.profile, headless=args.headless,
                    results_dir=args.results, live=live, screenshots=not args.no_screenshots, echo=echo,
                )
            except (SetupError, RuntimeError) as error:
                print(f"qc-use: {error}", file=sys.stderr)
                codes.append(SETUP_ERROR)
                if live:
                    live.finish()
                break
            if live:
                live.finish(report)
            reports.append(report)
            codes.append(report.exit_code)
            cost = f"${report.cost.usd:.4f}{' est.' if report.cost.estimated else ''}"
            seconds = report.elapsed_ms / 1000
            echo(f"{MARK[report.outcome]} {report.outcome} · {report.summary} ({seconds:.1f} s, {cost})")
            echo(f"   {Path(report.artifacts['folder']) / 'report.md'}\n")
        if args.repeat > 1:
            runs = [r for r in reports if r.test["file"] == str(spec.path)]
            passed = sum(r.outcome == "pass" for r in runs)
            echo(f"Pass rate for {spec.title}: {passed}/{len(runs)}")
    if args.json:
        payload = [r.model_dump(mode="json") for r in reports]
        print(json.dumps(payload[0] if len(payload) == 1 else payload, indent=2))
    return max(codes, default=SETUP_ERROR)


def init_command(args):
    from .scaffold import init

    for line in init(Path(args.directory)):
        print(line)
    return 0


def demo_command(args):
    from .demo import main

    return main(port=args.port, serve_only=args.serve, headless=args.headless)


def skill_command(args):
    from .report import SETUP_ERROR
    from .skill import TARGETS, install, text

    if args.action == "print":
        print(text(), end="")
        return 0
    targets = list(TARGETS) if args.target == "all" else [args.target] if args.target else None
    try:
        lines = install(targets=targets, path=args.path)
    except ValueError as error:
        print(f"qc-use: {error}", file=sys.stderr)
        return SETUP_ERROR
    for line in lines:
        print(line)
    return 0


def doctor_command(args):
    from .doctor import doctor

    return doctor(args.file)


def schema_command(args):
    from .report import Report
    from .spec import TestSpec

    model = {"report": Report, "test": TestSpec}[args.kind]
    print(json.dumps(model.model_json_schema(), indent=2))
    return 0


def parser():
    root = argparse.ArgumentParser(prog="qc-use", description=__doc__)
    root.add_argument("--version", action="version", version=f"qc-use {__version__}")
    commands = root.add_subparsers(dest="command", required=True)

    run = commands.add_parser("run", help="Run one or more test files, e.g. qa/onboarding.md")
    run.add_argument("files", nargs="+")
    run.add_argument("--allow", action="append", default=[], metavar="RULE",
                     help="Allow a never-do rule for this run (exact rule text, or '*' for all).")
    run.add_argument("--allow-production", action="store_true", help="Run against a URL that looks like production.")
    run.add_argument("--profile", help="Reuse a Chrome profile folder instead of a fresh one (e.g. to stay logged in).")
    run.add_argument("--headless", action="store_true", help="Run Chrome without a window.")
    run.add_argument("--watch", action="store_true", help="Open the live inspector while the test runs.")
    run.add_argument("--repeat", type=int, default=1, metavar="N",
                     help="Run N times in fresh profiles and report a pass rate.")
    run.add_argument("--results", default="qa-results", help="Where run folders are written (default qa-results).")
    run.add_argument("--no-screenshots", action="store_true", help="Do not save step screenshots.")
    run.add_argument("--json", action="store_true", help="Print report.json to stdout instead of progress.")
    run.set_defaults(handler=run_command)

    init = commands.add_parser("init", help="Create qa/ with an example test and ignore rules.")
    init.add_argument("directory", nargs="?", default=".")
    init.set_defaults(handler=init_command)

    demo = commands.add_parser("demo", help="Run the bundled demo app and its example test.")
    demo.add_argument("--serve", action="store_true", help="Only serve the demo app.")
    demo.add_argument("--port", type=int, default=3100)
    demo.add_argument("--headless", action="store_true")
    demo.set_defaults(handler=demo_command)

    skill = commands.add_parser("skill", help="Print or install the coding-agent skill.")
    skill.add_argument("action", nargs="?", choices=["print", "install"], default="print")
    skill.add_argument("--target", help="One agent (claude, codex, cursor, gemini, copilot, opencode, agents) or all.")
    skill.add_argument("--path", help="Write SKILL.md to this exact path instead.")
    skill.set_defaults(handler=skill_command)

    doctor = commands.add_parser("doctor", help="Check Chrome, inference keys, and optionally a test file.")
    doctor.add_argument("file", nargs="?")
    doctor.set_defaults(handler=doctor_command)

    schema = commands.add_parser("schema", help="Print the JSON schema of report.json or of a test file.")
    schema.add_argument("kind", choices=["report", "test"])
    schema.set_defaults(handler=schema_command)
    return root


def main(argv=None):
    from .report import SETUP_ERROR

    args = parser().parse_args(argv)
    if getattr(args, "repeat", 1) < 1:
        print("qc-use: --repeat must be at least 1", file=sys.stderr)
        return SETUP_ERROR
    try:
        return args.handler(args)
    except KeyboardInterrupt:
        print("\nqc-use: interrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
