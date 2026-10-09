"""Delete only unshared photo files owned by a packing-list reference."""

import json
import os
import stat
from pathlib import Path
from urllib.parse import unquote, urlsplit


PHOTO_URL_PREFIX = "/static/uploads/photos/"
DEFAULT_PHOTO_FOLDER = "static/uploads/photos"
DELETE_PHOTOS_PREFIX = "deleting:"
PHOTO_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp"}


class PackingPhotoCleanupError(RuntimeError):
    """The packing deletion committed, but photo cleanup needs a retry."""

    def __init__(self):
        super().__init__("装箱单已删除，部分照片清理尚未完成；请重试删除以完成清理")


def photo_urls(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return []
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def managed_photo_name(url):
    """Accept only a direct child of our upload URL, never an external path."""
    try:
        parsed = urlsplit(url)
    except (TypeError, ValueError):
        return None
    if parsed.scheme or parsed.netloc:
        return None
    path = unquote(parsed.path)
    if not path.startswith(PHOTO_URL_PREFIX):
        return None
    name = path[len(PHOTO_URL_PREFIX):]
    if not name or name in {".", ".."} or any(char in name for char in ("/", "\\", "\x00")):
        return None
    if "." not in name or name.rsplit(".", 1)[1].lower() not in PHOTO_EXTENSIONS:
        return None
    return name


def unshared_photo_names(session, uid, urls):
    from data.packing.PackingList import PackingListTable

    names = {name for url in photo_urls(urls) if (name := managed_photo_name(url))}
    if not names:
        return set()
    # Archived lists still own their referenced photos. Recheck after the
    # deletion commits, rather than relying on the old transaction snapshot.
    for (references,) in session.query(PackingListTable.photos).filter(PackingListTable.uid != uid):
        for url in photo_urls(references):
            names.discard(managed_photo_name(url))
    return names


def delete_photo_files(names, folder=None):
    """Missing files are already clean; unsafe paths and I/O errors are retryable.

    Open the directory without following links and unlink through its file
    descriptor, so no filename can redirect removal outside the upload folder.
    """
    if not names:
        return
    if any(not isinstance(name, str) or name in {"", ".", ".."}
           or any(char in name for char in ("/", "\\", "\x00")) for name in names):
        raise PackingPhotoCleanupError()
    root = Path(folder or DEFAULT_PHOTO_FOLDER).absolute()
    try:
        if root.resolve() != root:
            raise OSError("photo directory contains a symbolic link")
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    except FileNotFoundError:
        return
    except OSError as exc:
        raise PackingPhotoCleanupError() from exc
    try:
        for name in sorted(names):
            try:
                info = os.stat(name, dir_fd=directory, follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    raise OSError("photo is not a regular owned file")
                os.unlink(name, dir_fd=directory)
            except FileNotFoundError:
                # A prior cleanup attempt or another list deletion may have
                # removed it already. This keeps DELETE retries idempotent.
                continue
            except OSError as exc:
                raise PackingPhotoCleanupError() from exc
    finally:
        os.close(directory)
