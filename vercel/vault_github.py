"""Materialize the vault from its GitHub repo, for a host with no filesystem
of its own.

The Mac reads the vault straight off iCloud Drive. A serverless function has
neither iCloud nor a persistent disk, so it rebuilds the vault into /tmp from
the repo the Mac pushes to, and the helper scripts then run against it exactly
as they do locally -- same code, same output.

Reads: a cheap HEAD-sha probe decides whether the cached copy in /tmp is
current. Only when the repo has actually moved do we pay for a tarball.

Writes: the GitHub Contents API commits directly, so a note captured on the
iPhone is on GitHub the moment the tool returns, rather than waiting for
anything to sync.
"""
import base64
import fcntl
import json
import os
import shutil
import tarfile
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

REPO = os.environ.get("VAULT_REPO", "Dressi123/second-brain-vault")
BRANCH = os.environ.get("VAULT_BRANCH", "main")
TOKEN = os.environ.get("GITHUB_TOKEN", "")
API = "https://api.github.com"

# One stable path, never a per-commit one. The helper modules capture the
# vault path at import time, and a warm instance imports them once, so the
# location has to stay put even as its contents are refreshed underneath.
VAULT_DIR = Path(os.environ.get("SECOND_BRAIN_VAULT", "/tmp/vault"))
SHA_MARKER = VAULT_DIR.parent / f"{VAULT_DIR.name}.sha"
LOCK_FILE = VAULT_DIR.parent / f"{VAULT_DIR.name}.lock"


class VaultError(RuntimeError):
    pass


def _request(method: str, path: str, body: dict | None = None, raw: bool = False):
    url = path if path.startswith("http") else f"{API}{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = resp.read()
            return payload if raw else json.loads(payload or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:300]
        raise VaultError(f"GitHub {method} {path} -> {exc.code}: {detail}") from exc


def head_sha() -> str:
    return _request("GET", f"/repos/{REPO}/commits/{BRANCH}")["sha"]


def _cached_sha() -> str | None:
    try:
        return SHA_MARKER.read_text().strip() or None
    except OSError:
        return None


def ensure_vault(force: bool = False) -> Path:
    """Make VAULT_DIR reflect the repo's current head, then return it."""
    remote = head_sha()
    if not force and _cached_sha() == remote and VAULT_DIR.is_dir():
        return VAULT_DIR

    VAULT_DIR.parent.mkdir(parents=True, exist_ok=True)
    with open(LOCK_FILE, "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        # Another invocation on this instance may have refreshed it while we
        # waited for the lock.
        if not force and _cached_sha() == remote and VAULT_DIR.is_dir():
            return VAULT_DIR
        _extract_into(remote)
        SHA_MARKER.write_text(remote)
    return VAULT_DIR


def _extract_into(sha: str) -> None:
    """Replace VAULT_DIR's contents in place.

    In place, rather than renaming a freshly built tree over the old one: a
    concurrent request already reading VAULT_DIR would find the directory gone
    rather than merely stale, turning a soft problem into a hard failure.
    """
    blob = _request("GET", f"/repos/{REPO}/tarball/{sha}", raw=True)
    with tempfile.TemporaryDirectory(dir=VAULT_DIR.parent) as staging:
        archive = Path(staging) / "vault.tar.gz"
        archive.write_bytes(blob)
        unpacked = Path(staging) / "unpacked"
        with tarfile.open(archive) as tar:
            tar.extractall(unpacked, filter="data")
        # GitHub wraps everything in one <owner>-<repo>-<sha> directory.
        roots = [p for p in unpacked.iterdir() if p.is_dir()]
        if len(roots) != 1:
            raise VaultError(f"unexpected tarball layout: {[p.name for p in roots]}")
        root = roots[0]

        VAULT_DIR.mkdir(parents=True, exist_ok=True)
        for existing in VAULT_DIR.iterdir():
            shutil.rmtree(existing) if existing.is_dir() else existing.unlink()
        for item in root.iterdir():
            shutil.move(str(item), str(VAULT_DIR / item.name))


def _blob_sha(path: str) -> str | None:
    try:
        info = _request("GET", f"/repos/{REPO}/contents/{path}?ref={BRANCH}")
    except VaultError as exc:
        if "-> 404" in str(exc):
            return None
        raise
    return info.get("sha") if isinstance(info, dict) else None


def put_file(path: str, content: str, message: str) -> str:
    """Create or overwrite one file, committing it straight to the repo.

    An update needs the current blob sha; a create must not send one. If the
    file moves between our read and our write GitHub answers 409, so we take a
    fresh sha and try once more before giving up -- the write is small and the
    conflict window is milliseconds wide.
    """
    body = {
        "message": message,
        "content": base64.b64encode(content.encode()).decode(),
        "branch": BRANCH,
    }
    for attempt in (1, 2):
        sha = _blob_sha(path)
        payload = dict(body)
        if sha:
            payload["sha"] = sha
        try:
            result = _request("PUT", f"/repos/{REPO}/contents/{path}", payload)
        except VaultError as exc:
            if "-> 409" in str(exc) and attempt == 1:
                continue   # someone else wrote first; re-read and retry once
            raise
        # Keep this instance's copy usable without a full re-download.
        local = VAULT_DIR / path
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(content, encoding="utf-8")
        SHA_MARKER.write_text(result["commit"]["sha"])
        return result["commit"]["sha"]
    raise VaultError(f"could not write {path}: repeated conflicts")


def file_exists(path: str) -> bool:
    return _blob_sha(path) is not None
