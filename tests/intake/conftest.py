"""Paper photo tests use temporary private storage, including worker threads."""

import pytest


@pytest.fixture(autouse=True)
def paper_photo_root(monkeypatch, tmp_path):
    root = tmp_path / "paper_intakes"
    monkeypatch.setenv("PAPER_PHOTO_ROOT", str(root))
    monkeypatch.delenv("PAPER_PHOTO_MANIFEST", raising=False)
    return root
