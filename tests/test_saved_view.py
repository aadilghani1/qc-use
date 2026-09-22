"""Saved evidence stays local, uses validated reports, and never executes a run."""

import io
import json

import pytest
from PIL import Image

from qc_use.saved_view import SavedView


def saved(tmp_path):
    image = io.BytesIO()
    Image.new("RGB", (2, 2)).save(image, format="JPEG")
    (tmp_path / "step.jpg").write_bytes(image.getvalue())
    path = tmp_path / "report.json"
    path.write_text(
        json.dumps(
            {
                "run_id": "saved",
                "test": {"title": "A saved run", "url": "http://localhost"},
                "started_at": "2026-09-22",
                "elapsed_ms": 12,
                "outcome": "fail",
                "exit_code": 1,
                "summary": "Step 2 failed",
                "steps": [
                    {"index": 1, "text": "Read", "outcome": "pass", "screenshot": "step.jpg"},
                    {
                        "index": 2,
                        "text": "Check",
                        "outcome": "fail",
                        "checks": [{"kind": "check", "text": "Expected result", "outcome": "fail"}],
                    },
                ],
                "cost": {"usd": 0, "estimated": False, "model_calls": 0, "unpriced_calls": 0, "cap": 1},
                "models": {},
                "artifacts": {},
            }
        )
    )
    return path


def test_saved_view_selects_evidence_without_browser(tmp_path):
    view = SavedView(saved(tmp_path))
    last, image = view.view()
    assert last["saved"] and last["current"] == 1 and not image
    first, image = view.view(0)
    assert first["current"] == 0 and first["has_screenshot"] and image.startswith(b"\xff\xd8\xff")
    assert last["steps"][1]["checks"][0]["outcome"] == "fail"
    for index in (-1, 2):
        with pytest.raises(IndexError):
            view.view(index)


@pytest.mark.parametrize("reference", ["../outside.jpg", "/tmp/outside.jpg", "https://example.com/image.jpg"])
def test_saved_view_never_reads_external_images(tmp_path, reference, monkeypatch):
    view = SavedView(saved(tmp_path))
    view.report.steps[0].screenshot = reference
    original = type(tmp_path).read_bytes

    def read(path):
        assert path.is_relative_to(tmp_path)
        return original(path)

    monkeypatch.setattr(type(tmp_path), "read_bytes", read)
    assert not view.view(0)[1]


def test_saved_view_rejects_unsupported_schema_and_bad_step_indices(tmp_path):
    path = saved(tmp_path)
    data = json.loads(path.read_text())
    data["schema_version"] = "qc-use.report/999"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="schema"):
        SavedView(path)
    data.pop("schema_version")
    data["steps"][1]["index"] = 1
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="numbered"):
        SavedView(path)


@pytest.mark.parametrize(
    ("path", "host", "expected"),
    [
        ("/api/state?t=wrong", "127.0.0.1:12345", 403),
        ("/api/state?t=TOKEN", "untrusted.example", 403),
        ("/api/state?t=TOKEN&step=-1", "127.0.0.1:12345", 400),
        ("/api/state?t=TOKEN&step=bad", "127.0.0.1:12345", 400),
        ("/api/state?t=TOKEN&step=0", "127.0.0.1:12345", 200),
        ("/api/screenshot?t=TOKEN&step=0", "127.0.0.1:12345", 200),
        ("/report.json?t=TOKEN", "127.0.0.1:12345", 404),
    ],
)
def test_saved_http_routes_require_token_host_and_valid_step(tmp_path, path, host, expected):
    from types import SimpleNamespace
    from unittest.mock import Mock

    view = SavedView(saved(tmp_path))
    view.server = SimpleNamespace(server_port=12345)
    handler_type = view.handler()
    handler = handler_type.__new__(handler_type)
    handler.path = path.replace("TOKEN", view.token)
    handler.headers = {"Host": host}
    handler.reply = Mock()
    handler.do_GET()
    assert handler.reply.call_args.args[0] == expected


def test_saved_screenshot_symlink_cannot_escape_run_folder(tmp_path):
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"\xff\xd8\xffprivate")
    run = tmp_path / "run"
    run.mkdir()
    view = SavedView(saved(run))
    (run / "link.jpg").symlink_to(outside)
    view.report.steps[0].screenshot = "link.jpg"
    assert not view.view(0)[1]
