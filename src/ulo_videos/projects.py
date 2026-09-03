"""Local project asset storage: uploads, collision-safe names, and manifests.

`store_upload` validates an uploaded filename, writes the file bytes under the
project's `assets/` directory with a collision-safe stored name, and records
the asset in `assets/manifest.json` using the repository's canonical JSON
convention. Manifest updates are read-modify-write, so entries survive
successive uploads, and they carry no wall-clock timestamps so project
directories stay deterministic. The whole store sequence runs under a module
lock, and manifest writes go through a temp file and `os.replace`, so threaded
servers cannot interleave two uploads or observe a partial manifest. Path
safety is delegated to `renderers.resolve_relative_path`; uploads never write
outside the project root.
"""

import hashlib
import json
import os
import threading
from pathlib import Path, PurePosixPath, PureWindowsPath

from .renderers import resolve_relative_path

MAX_UPLOAD_BYTES = 256 * 1024 * 1024
ASSETS_DIRNAME = "assets"
MANIFEST_NAME = "manifest.json"
ALLOWED_EXTENSIONS = frozenset(
    {
        ".mp4",
        ".mov",
        ".webm",
        ".mkv",
        ".png",
        ".jpg",
        ".jpeg",
        ".svg",
        ".blend",
        ".wav",
        ".mp3",
    }
)
# Serializes each upload's name selection, file write, and manifest update;
# projects is the only manifest writer, so a single lock is enough.
_UPLOAD_LOCK = threading.Lock()


class ProjectStorageError(Exception):
    """Base class for project asset storage errors."""


class InvalidFilenameError(ProjectStorageError):
    """Raised when an upload filename is not a safe bare filename."""


class UnsupportedExtensionError(ProjectStorageError):
    """Raised when an upload filename's extension is not an accepted media type."""


class UploadTooLargeError(ProjectStorageError):
    """Raised when an upload body exceeds `MAX_UPLOAD_BYTES`."""


class ManifestError(ProjectStorageError):
    """Raised when a stored asset manifest cannot be read."""


def validate_upload_filename(filename):
    """Return `filename` when it is a bare, allow-listed media filename.

    Empty values, path separators, `..`, drive or absolute forms, and control
    characters raise `InvalidFilenameError`; extensions outside
    `ALLOWED_EXTENSIONS` raise `UnsupportedExtensionError`. The extension
    check is case-insensitive and the caller's casing is preserved.
    """
    if not isinstance(filename, str) or not filename.strip():
        raise InvalidFilenameError(
            f"filename must be a non-empty name, got {filename!r}"
        )
    if (
        PurePosixPath(filename).name != filename
        or PureWindowsPath(filename).name != filename
    ):
        raise InvalidFilenameError(
            f"filename must be a bare name without path separators, got {filename!r}"
        )
    if PureWindowsPath(filename).drive:
        raise InvalidFilenameError(
            f"filename must not contain a drive or device prefix, got {filename!r}"
        )
    if filename in (".", ".."):
        raise InvalidFilenameError(f"filename must name a file, got {filename!r}")
    if any(ord(char) < 0x20 for char in filename):
        raise InvalidFilenameError("filename must not contain control characters")
    suffix = PurePosixPath(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        accepted = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise UnsupportedExtensionError(
            f"filename extension must be one of {accepted}, got {filename!r}"
        )
    return filename


def unique_asset_name(assets_dir, filename):
    """Return a collision-safe stored name for `filename` inside `assets_dir`.

    The base filename is kept when free; otherwise a `-2`, `-3`, ... suffix is
    inserted before the original extension (`house_leak.mp4` becomes
    `house_leak-2.mp4`).
    """
    pure = PurePosixPath(filename)
    candidate = filename
    number = 1
    while (Path(assets_dir) / candidate).exists():
        number += 1
        candidate = f"{pure.stem}-{number}{pure.suffix}"
    return candidate


def manifest_path(project_root):
    """Return the absolute path of the project's asset manifest."""
    return Path(project_root) / ASSETS_DIRNAME / MANIFEST_NAME


def read_manifest(project_root):
    """Return the project's stored manifest, or an empty one when absent."""
    path = manifest_path(project_root)
    if not path.is_file():
        return {"assets": []}
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ManifestError(f"manifest {path} is unreadable: {error}") from error
    if not isinstance(manifest, dict) or not isinstance(manifest.get("assets"), list):
        raise ManifestError(f"manifest {path} must be an object with an 'assets' list")
    return manifest


def store_upload(project_root, filename, content, *, max_bytes=None):
    """Store uploaded bytes as a project asset and record them in the manifest.

    Returns the stored relative path in repository form (for example
    `"assets/house_leak-2.mp4"`) and the JSON-safe manifest entry. The limit
    defaults to the module-level `MAX_UPLOAD_BYTES` and can be overridden with
    `max_bytes`. The manifest is read before anything is written, and the
    whole sequence runs under `_UPLOAD_LOCK`, so a failed upload leaves no
    file behind and concurrent uploads cannot lose manifest entries.
    """
    validate_upload_filename(filename)
    if not isinstance(content, (bytes, bytearray)):
        raise ProjectStorageError("upload content must be bytes")
    limit = MAX_UPLOAD_BYTES if max_bytes is None else max_bytes
    if len(content) > limit:
        raise UploadTooLargeError(
            f"upload is {len(content)} bytes; the limit is {limit} bytes"
        )
    content = bytes(content)
    assets_dir = Path(project_root) / ASSETS_DIRNAME
    with _UPLOAD_LOCK:
        manifest = read_manifest(project_root)
        stored_name = unique_asset_name(assets_dir, filename)
        relative = f"{ASSETS_DIRNAME}/{stored_name}"
        target = Path(resolve_relative_path(project_root, relative, "filename"))
        entry = {
            "filename": stored_name,
            "original_name": filename,
            "sha256": hashlib.sha256(content).hexdigest(),
            "bytes": len(content),
        }
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            manifest["assets"].append(entry)
            _write_manifest(project_root, manifest)
        except OSError as error:
            raise ProjectStorageError(
                f"could not store {relative}: {error}"
            ) from error
        return relative, entry


def _write_manifest(project_root, manifest):
    """Persist the manifest atomically with the repository's canonical JSON convention."""
    text = json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    path = manifest_path(project_root)
    temp = path.with_name(f".{MANIFEST_NAME}.tmp")
    temp.write_text(text, encoding="utf-8")
    os.replace(temp, path)
