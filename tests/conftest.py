"""Shared test guards."""

import pytest

from qc_use.engine import model


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    """Tests run offline: a test that reaches a real model API fails."""

    def refuse(*_args, **_kwargs):
        raise AssertionError("A test tried to call a real model API. Mock post_json or judge instead.")

    monkeypatch.setattr(model.CLIENT, "post", refuse)
