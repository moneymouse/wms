"""Private file access and retry safety, independent of the real application."""

from types import SimpleNamespace

import pytest

from services import paper_photo_storage as storage


def test_migration_retry_preserves_existing_original_and_refuses_conflicting_bytes(paper_photo_root):
    original = b"source photograph bytes"
    metadata = storage.save_bytes("source", "photo", "image/png", original)
    photo = SimpleNamespace(**metadata)
    path = paper_photo_root / metadata["storage_path"]
    assert storage.save_bytes("source", "photo", "image/png", original) == metadata
    assert path.read_bytes() == original
    with pytest.raises(storage.PhotoStorageError, match="differs"):
        storage.save_bytes("source", "photo", "image/png", b"different photograph")
    assert storage.read_bytes(photo) == original


def test_corrupted_photo_is_not_served_as_the_original(paper_photo_root):
    metadata = storage.save_bytes("source", "photo", "image/png", b"original")
    (paper_photo_root / metadata["storage_path"]).write_bytes(b"modified")
    with pytest.raises(storage.PhotoStorageError, match="integrity"):
        storage.read_bytes(SimpleNamespace(**metadata))


def test_photo_symlink_never_reads_overwrites_or_deletes_unrelated_file(paper_photo_root, tmp_path):
    metadata = storage.save_bytes("source", "photo", "image/png", b"original")
    path = paper_photo_root / metadata["storage_path"]
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"unrelated")
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(OSError):
        storage.read_bytes(SimpleNamespace(**metadata))
    with pytest.raises(OSError):
        storage.save_bytes("source", "photo", "image/png", b"replacement")
    with pytest.raises(OSError):
        storage.delete_file(metadata["storage_path"])
    assert storage.file_size(metadata["storage_path"]) is None
    assert list(storage.iter_files()) == []
    assert path.is_symlink()
    assert outside.read_bytes() == b"unrelated"


@pytest.mark.parametrize("reference", ["../outside.png", "/tmp/outside.png", "source/../outside.png", "source/%2e%2e.png"])
def test_untrusted_storage_path_cannot_escape_private_directory(reference, tmp_path):
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"unrelated")
    with pytest.raises(storage.PhotoStorageError):
        storage.delete_file(reference)
    with pytest.raises(storage.PhotoStorageError):
        storage.read_bytes(SimpleNamespace(storage_path=reference, size_bytes=9, sha256=""))
    assert outside.read_bytes() == b"unrelated"
