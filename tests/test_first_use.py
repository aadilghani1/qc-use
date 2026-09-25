"""First-use commands expose evidence and diagnostics without changing report compatibility."""

import json
from unittest.mock import Mock

import pytest
from test_ci import report

from qc_use import cli, runner, scaffold, watch
from qc_use.report import CommandResult


def test_patterns_are_sorted_deduplicated_and_unmatched_patterns_reported(tmp_path, capsys):
    scaffold.init(tmp_path)
    first = tmp_path / "qa/onboarding.md"
    second = tmp_path / "qa/other.md"
    second.write_bytes(first.read_bytes())
    pattern = str(tmp_path / "qa/*.md")
    assert cli.test_files([pattern, str(first)]) == [str(first), str(second)]
    assert cli.main(["validate", pattern, str(tmp_path / "absent*.md"), "--json"]) == 4
    assert [item["valid"] for item in json.loads(capsys.readouterr().out)] == [True, True, False]


def test_command_result_includes_mixed_reports_and_setup_errors(tmp_path, monkeypatch, capsys):
    scaffold.init(tmp_path)
    monkeypatch.setattr(runner, "run", Mock(return_value=report("pass")))
    path = str(tmp_path / "qa/onboarding.md")
    assert cli.main(["run", path, str(tmp_path / "missing.md"), "--json-result"]) == 4
    result = CommandResult.model_validate_json(capsys.readouterr().out)
    assert result.exit_code == 4 and len(result.reports) == len(result.setup_errors) == 1
    assert "missing.md" in result.setup_errors[0].file
    assert result.schema_version == "qc-use.command/1"


def test_watched_json_exposes_live_url_and_reopen_command_on_stderr(tmp_path, monkeypatch, capsys):
    scaffold.init(tmp_path)
    live = Mock()

    def start(spec, echo):
        echo("Watching live at http://127.0.0.1:12345/?t=fixture")
        return live

    monkeypatch.setattr(watch.Watch, "start", start)
    monkeypatch.setattr(runner, "run", Mock(return_value=report("pass")))
    assert cli.main(["run", str(tmp_path / "qa/onboarding.md"), "--watch", "--json", "--keep-open"]) == 0
    output = capsys.readouterr()
    assert json.loads(output.out)["schema_version"] == "qc-use.report/2"
    assert "http://127.0.0.1:12345" in output.err and "qc-use report" in output.err
    live.finish.assert_called_once_with(runner.run.return_value, keep_open=True)
    live.hold.assert_called_once()
    live.close.assert_called_once()


@pytest.mark.parametrize("args", [["--keep-open"], ["--watch", "--keep-open", "--repeat", "2"]])
def test_keep_open_rejects_ambiguous_or_unwatched_runs(args, monkeypatch):
    run = Mock()
    monkeypatch.setattr(runner, "run", run)
    assert cli.main(["run", "missing.md", *args]) == 4
    run.assert_not_called()


def test_keep_open_finishes_state_and_closes_on_interrupt(monkeypatch):
    from types import SimpleNamespace

    live = watch.Watch(SimpleNamespace(title="Test", url="http://localhost", secrets=[], steps=[]))
    live.close = Mock()
    live.finish(keep_open=True)
    assert live.state["status"] == "stopped"
    live.close.assert_not_called()
    monkeypatch.setattr(watch.threading, "Event", lambda: Mock(wait=Mock(side_effect=KeyboardInterrupt)))
    live.hold(Mock())
    live.close.assert_not_called()


@pytest.mark.parametrize("failure", [False, OSError("no browser")])
def test_open_failure_keeps_a_usable_inspector_url(monkeypatch, failure):
    from types import SimpleNamespace

    live = watch.Watch(SimpleNamespace(title="Test", url="http://localhost", secrets=[], steps=[]))
    server = Mock(server_port=12345)
    monkeypatch.setattr(watch, "ThreadingHTTPServer", Mock(return_value=server))
    monkeypatch.setattr(watch.threading, "Thread", Mock())
    monkeypatch.setattr(watch.webbrowser, "open", Mock(side_effect=failure) if failure else Mock(return_value=False))
    echo = Mock()
    assert live.open(echo).startswith("http://127.0.0.1:12345/")
    assert "Open the printed URL" in echo.call_args.args[0]


def test_setup_failure_never_keeps_a_dead_inspector_open(tmp_path, monkeypatch, capsys):
    scaffold.init(tmp_path)
    live = Mock()
    monkeypatch.setattr(watch.Watch, "start", Mock(return_value=live))
    monkeypatch.setattr(runner, "run", Mock(side_effect=runner.SetupError("No key")))
    assert cli.main(["run", str(tmp_path / "qa/onboarding.md"), "--watch", "--keep-open", "--json-result"]) == 4
    result = json.loads(capsys.readouterr().out)
    assert not result["reports"] and result["setup_errors"][0]["error"] == "No key"
    live.finish.assert_called_once_with()
    live.hold.assert_not_called()


@pytest.mark.parametrize("error", [PermissionError("do-not-expose"), UnicodeError("do-not-expose")])
def test_unreadable_environment_is_reported_and_batch_continues(tmp_path, monkeypatch, capsys, error):
    from qc_use import secrets

    scaffold.init(tmp_path)
    path = tmp_path / "qa/onboarding.md"
    other = tmp_path / "qa/other.md"
    other.write_bytes(path.read_bytes())
    monkeypatch.setattr(secrets, "load_env", Mock(side_effect=[error, None, None]))
    run = Mock(return_value=report("pass"))
    monkeypatch.setattr(runner, "run", run)
    assert cli.main(["run", str(path), str(other), "--json-result"]) == 4
    result = json.loads(capsys.readouterr().out)
    assert len(result["reports"]) == len(result["setup_errors"]) == 1
    assert "Cannot read" in result["setup_errors"][0]["error"]
    assert "do-not-expose" not in result["setup_errors"][0]["error"]
    run.assert_called_once()


def test_output_failure_closes_kept_inspector(tmp_path, monkeypatch):
    scaffold.init(tmp_path)
    live = Mock()
    monkeypatch.setattr(watch.Watch, "start", Mock(return_value=live))
    monkeypatch.setattr(runner, "run", Mock(return_value=report("pass")))
    monkeypatch.setattr(cli, "write_summaries", Mock(side_effect=OSError("disk")))
    with pytest.raises(OSError, match="disk"):
        cli.main(["run", str(tmp_path / "qa/onboarding.md"), "--watch", "--keep-open"])
    live.close.assert_called_once()
    live.hold.assert_not_called()


def test_windows_reopen_command_quotes_powershell_literal_paths(tmp_path, monkeypatch, capsys):
    scaffold.init(tmp_path)
    live = Mock()
    monkeypatch.setattr(watch.Watch, "start", Mock(return_value=live))
    result = report("pass")
    result.artifacts["folder"] = str(tmp_path / "qa's $results")
    monkeypatch.setattr(runner, "run", Mock(return_value=result))
    monkeypatch.setattr(cli.sys, "platform", "win32")
    assert cli.main(["run", str(tmp_path / "qa/onboarding.md"), "--watch", "--json-result"]) == 0
    stderr = capsys.readouterr().err
    assert "qc-use report '" in stderr and "qa''s $results'" in stderr
