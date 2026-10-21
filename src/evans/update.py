"""
Updates from GitHub Releases: is there a newer Evans, and fetch its installer.

No Qt in here, so it can be tested without a window. The prompt, the
background threads and the hand-over to the installer are
:mod:`evans.ui.updater`.

Every tagged release carries ``Evans-Setup-<version>.exe`` (the CI job builds
it). The installer is per user and upgrades in place, so updating is: run
the new installer, silently, and let it replace the running copy. The
download is checked against the SHA-256 GitHub lists for the file, which is
what makes running it safe while the installer itself is unsigned.
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.request import Request, urlopen

from evans import __version__

REPO = "leo-01000111/evans"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
#: Where a release's files are served from. A download URL anywhere else is
#: refused, whatever the API answered.
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
SETUP_ASSET = re.compile(r"^Evans-Setup-[\w.+-]+\.exe$")


class UpdateError(Exception):
    """A check or download that failed. The message is fit to show."""


@dataclass(frozen=True)
class Release:
    version: tuple[int, ...]
    tag: str
    notes_url: str
    asset_name: str
    asset_url: str
    size: int
    sha256: str | None

    @property
    def label(self) -> str:
        """``0.9.4``: the tag without its ``v``."""
        return self.tag.removeprefix("v")


def parse_version(text: str) -> tuple[int, ...] | None:
    """``v0.9.4`` or ``0.9.4`` → ``(0, 9, 4)``; anything else → None."""
    match = re.fullmatch(r"v?(\d+(?:\.\d+)*)", text.strip())
    if not match:
        return None
    return tuple(int(part) for part in match.group(1).split("."))


def current_version() -> tuple[int, ...]:
    return parse_version(__version__) or (0,)


def release_from_json(data: dict) -> Release | None:
    """
    The release the API described, or None if there is nothing to install.

    Drafts, pre-releases, a tag that is not a version and a release without
    an installer all come back as None rather than as an error: none of them
    is something to offer.
    """
    if data.get("draft") or data.get("prerelease"):
        return None
    tag = str(data.get("tag_name", ""))
    version = parse_version(tag)
    if version is None:
        return None
    for asset in data.get("assets") or ():
        name = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if not SETUP_ASSET.match(name) or not url.startswith(DOWNLOAD_PREFIX):
            continue
        digest = str(asset.get("digest") or "")
        return Release(
            version=version,
            tag=tag,
            notes_url=str(data.get("html_url") or
                          f"https://github.com/{REPO}/releases/tag/{tag}"),
            asset_name=name,
            asset_url=url,
            size=int(asset.get("size") or 0),
            sha256=digest.removeprefix("sha256:").lower() or None,
        )
    return None


def is_newer(release: Release, than: tuple[int, ...] | None = None) -> bool:
    return release.version > (than or current_version())


def _request(url: str) -> Request:
    return Request(url, headers={
        "User-Agent": f"Evans/{__version__}",
        "Accept": "application/vnd.github+json",
    })


def fetch_latest(timeout: float = 10.0) -> Release | None:
    """Ask GitHub for the latest release. Raises :class:`UpdateError`."""
    try:
        with urlopen(_request(LATEST_URL), timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Could not reach GitHub ({exc}).") from exc
    if not isinstance(data, dict):
        raise UpdateError("GitHub sent something that is not a release.")
    return release_from_json(data)


def download_dir() -> Path:
    return Path(tempfile.gettempdir()) / "Evans-update"


def download(release: Release, dest: Path | None = None, *,
             progress: Callable[[int, int], None] | None = None,
             cancelled: Callable[[], bool] | None = None,
             timeout: float = 30.0) -> Path:
    """
    Fetch the installer and check it. Returns its path.

    Written to a ``.part`` file and renamed only once the size and the
    SHA-256 agree with what GitHub listed, so a half-finished or tampered
    download is never left where it could be run. ``progress`` gets
    (bytes so far, total); ``cancelled`` is polled between chunks.
    """
    dest = dest or download_dir()
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / release.asset_name
    part = target.with_name(target.name + ".part")
    digest = hashlib.sha256()
    received = 0
    try:
        with urlopen(_request(release.asset_url), timeout=timeout) as response, \
                open(part, "wb") as out:
            while chunk := response.read(256 * 1024):
                if cancelled and cancelled():
                    raise UpdateError("Download cancelled.")
                out.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress:
                    progress(received, release.size)
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise UpdateError(f"The download failed ({exc}).") from exc
    except UpdateError:
        part.unlink(missing_ok=True)
        raise

    if release.size and received != release.size:
        part.unlink(missing_ok=True)
        raise UpdateError("The download was incomplete.")
    if release.sha256 and digest.hexdigest() != release.sha256:
        part.unlink(missing_ok=True)
        raise UpdateError("The download did not match its checksum, "
                          "so it was thrown away.")
    part.replace(target)
    return target


def can_install() -> bool:
    """Only an installed Evans.exe on Windows replaces itself."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def is_packaged() -> bool:
    """
    A built app rather than a checkout. The Mac app is one that cannot
    replace itself yet, so it checks all the same and points at the release.
    """
    return bool(getattr(sys, "frozen", False))


def installer_arguments(*, relaunch: bool) -> list[str]:
    """
    How the installer is run.

    Silent, with no questions: it upgrades the existing install where it is
    and closes a running Evans. ``relaunch`` (*Update now*) shows its
    progress window and opens Evans again at the end (``/relaunch=1`` is
    read by ``packaging/evans.iss``); otherwise (*on close*) nothing shows.
    """
    args = ["/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS"]
    if relaunch:
        return ["/SILENT", *args, "/relaunch=1"]
    return ["/VERYSILENT", *args]
