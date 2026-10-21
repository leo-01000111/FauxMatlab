"""
Updates from GitHub Releases: reading the API, the checked download, and the
prompt's three answers.

Nothing here touches the network or runs an installer: ``urlopen`` is
replaced with canned bytes, and the updater's threads, dialogs and launcher
are its own methods, answered in line.
"""

from __future__ import annotations

import hashlib
import io
import json
import os

os.environ.setdefault("PYQTGRAPH_QT_LIB", "PySide6")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from evans import update
from evans.update import Release, UpdateError

PAYLOAD = b"MZ" + b"installer bytes " * 4096
SHA = hashlib.sha256(PAYLOAD).hexdigest()
URL = update.DOWNLOAD_PREFIX + "v9.0.0/Evans-Setup-9.0.0.exe"


def api_release(**overrides) -> dict:
    data = {
        "tag_name": "v9.0.0",
        "html_url": "https://github.com/leo-01000111/evans/releases/tag/v9.0.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "Evans-windows.zip", "size": 10, "digest": "sha256:00",
             "browser_download_url": update.DOWNLOAD_PREFIX + "v9.0.0/Evans-windows.zip"},
            {"name": "Evans-Setup-9.0.0.exe", "size": len(PAYLOAD),
             "digest": f"sha256:{SHA}", "browser_download_url": URL},
        ],
    }
    data.update(overrides)
    return data


def release(**overrides) -> Release:
    fields = dict(version=(9, 0, 0), tag="v9.0.0", notes_url="https://x",
                  asset_name="Evans-Setup-9.0.0.exe", asset_url=URL,
                  size=len(PAYLOAD), sha256=SHA)
    fields.update(overrides)
    return Release(**fields)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


# ── Reading the API ──────────────────────────────────────────


@pytest.mark.parametrize("text, expected", [
    ("v0.9.4", (0, 9, 4)), ("0.10.0", (0, 10, 0)), ("v1", (1,)),
    ("nightly", None), ("v1.0-beta", None), ("", None),
])
def test_versions_are_read_from_tags(text, expected):
    assert update.parse_version(text) == expected


def test_versions_compare_as_numbers_not_text():
    assert update.is_newer(release(version=(0, 10, 0)), than=(0, 9, 9))
    assert not update.is_newer(release(version=(0, 9, 3)), than=(0, 9, 3))
    assert not update.is_newer(release(version=(0, 9, 2)), than=(0, 9, 3))


def test_the_installer_is_picked_from_the_release():
    found = update.release_from_json(api_release())
    assert found == release(
        notes_url="https://github.com/leo-01000111/evans/releases/tag/v9.0.0")
    assert found.label == "9.0.0"


@pytest.mark.parametrize("overrides", [
    {"draft": True},
    {"prerelease": True},
    {"tag_name": "nightly"},
    {"assets": []},
    # An installer served from anywhere but this repository's releases.
    {"assets": [{"name": "Evans-Setup-9.0.0.exe", "size": 1,
                 "browser_download_url": "https://evil.example/Evans-Setup-9.0.0.exe"}]},
])
def test_nothing_is_offered_that_should_not_be(overrides):
    assert update.release_from_json(api_release(**overrides)) is None


def test_fetch_latest_reads_the_api(monkeypatch):
    seen = []

    def fake(request, timeout):
        seen.append(request.full_url)
        return FakeResponse(json.dumps(api_release()).encode())

    monkeypatch.setattr(update, "urlopen", fake)
    assert update.fetch_latest().tag == "v9.0.0"
    assert seen == [update.LATEST_URL]


def test_fetch_latest_turns_network_trouble_into_one_error(monkeypatch):
    def offline(request, timeout):
        raise OSError("no route to host")

    monkeypatch.setattr(update, "urlopen", offline)
    with pytest.raises(UpdateError, match="no route to host"):
        update.fetch_latest()

    monkeypatch.setattr(update, "urlopen",
                        lambda request, timeout: FakeResponse(b"<html>"))
    with pytest.raises(UpdateError):
        update.fetch_latest()


# ── Downloading ──────────────────────────────────────────────


def serve(monkeypatch, payload: bytes) -> None:
    monkeypatch.setattr(update, "urlopen",
                        lambda request, timeout: FakeResponse(payload))


def test_a_good_download_is_kept(monkeypatch, tmp_path):
    serve(monkeypatch, PAYLOAD)
    reports = []
    path = update.download(release(), tmp_path,
                           progress=lambda got, total: reports.append(got))
    assert path == tmp_path / "Evans-Setup-9.0.0.exe"
    assert path.read_bytes() == PAYLOAD
    assert reports[-1] == len(PAYLOAD)
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("payload, message", [
    (PAYLOAD[:-1], "incomplete"),
    (PAYLOAD[:-1] + b"!", "checksum"),
], ids=["short", "altered"])
def test_a_bad_download_is_thrown_away(monkeypatch, tmp_path, payload, message):
    serve(monkeypatch, payload)
    with pytest.raises(UpdateError, match=message):
        update.download(release(), tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_cancelled_download_leaves_nothing(monkeypatch, tmp_path):
    serve(monkeypatch, PAYLOAD)
    with pytest.raises(UpdateError, match="cancelled"):
        update.download(release(), tmp_path, cancelled=lambda: True)
    assert list(tmp_path.iterdir()) == []


def test_the_installer_reopens_evans_only_for_update_now():
    now = update.installer_arguments(relaunch=True)
    on_close = update.installer_arguments(relaunch=False)
    assert "/SILENT" in now and "/relaunch=1" in now
    assert "/VERYSILENT" in on_close and "/relaunch=1" not in on_close
    for args in (now, on_close):
        assert "/SUPPRESSMSGBOXES" in args and "/CLOSEAPPLICATIONS" in args


def test_the_installer_script_honours_relaunch():
    from pathlib import Path

    script = (Path(__file__).parents[1] / "packaging" / "evans.iss").read_text(
        encoding="utf-8")
    assert "Check: RelaunchRequested" in script
    assert "{param:relaunch|0}" in script


# ── The prompt ───────────────────────────────────────────────


@pytest.fixture
def updater(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication, QWidget

    from evans.ui import persist
    from evans.ui.updater import Updater

    QApplication.instance() or QApplication([])
    persist.settings().remove("updates")
    parent = QWidget()
    up = Updater(parent)
    up.launched, up.told, up.messages = [], [], []
    up._in_background = lambda work, then: then(_call(work))
    up._launch = lambda program, args: up.launched.append((program, args)) or True
    up._tell = lambda title, text: up.told.append(text)
    up.status.connect(lambda text, ms: up.messages.append(text))
    parent.close = lambda: True
    monkeypatch.setattr(QApplication, "quit", lambda *a: None)
    monkeypatch.setattr(update, "can_install", lambda: True)
    monkeypatch.setattr(update, "current_version", lambda: (0, 9, 3))
    monkeypatch.setattr(update, "download",
                        lambda rel, *a, **k: tmp_path / rel.asset_name)
    (tmp_path / "Evans-Setup-9.0.0.exe").write_bytes(PAYLOAD)
    yield up
    persist.settings().remove("updates")
    parent.deleteLater()


def _call(work):
    try:
        return work()
    except UpdateError as exc:
        return exc


def answer(up, choice, skip=False):
    asked = []
    up._ask = lambda rel: asked.append(rel) or (choice, skip)
    return asked


def test_update_now_runs_the_installer_and_reopens(updater, monkeypatch):
    monkeypatch.setattr(update, "fetch_latest", lambda: release())
    answer(updater, updater.NOW)
    updater.check()
    (program, args), = updater.launched
    assert program.endswith("Evans-Setup-9.0.0.exe")
    assert "/relaunch=1" in args


def test_update_on_close_waits_for_the_window_to_close(updater, monkeypatch):
    monkeypatch.setattr(update, "fetch_latest", lambda: release())
    answer(updater, updater.ON_CLOSE)
    updater.check()
    assert updater.pending is not None and updater.launched == []
    assert any("when you close" in m for m in updater.messages)

    assert updater.install_pending()
    (program, args), = updater.launched
    assert "/VERYSILENT" in args and "/relaunch=1" not in args
    assert updater.pending is None
    assert not updater.install_pending()        # once only


def test_later_does_nothing_and_asks_again(updater, monkeypatch):
    monkeypatch.setattr(update, "fetch_latest", lambda: release())
    asked = answer(updater, updater.LATER)
    updater.check(manual=False)
    updater.check(manual=False)
    assert len(asked) == 2 and updater.launched == []
    assert not updater.install_pending()


def test_a_skipped_version_is_not_offered_again_by_itself(updater, monkeypatch):
    monkeypatch.setattr(update, "fetch_latest", lambda: release())
    asked = answer(updater, updater.LATER, skip=True)
    updater.check(manual=False)
    updater.check(manual=False)
    assert len(asked) == 1
    updater.check(manual=True)                  # asked for: shown anyway
    assert len(asked) == 2


def test_up_to_date_is_said_only_when_asked(updater, monkeypatch):
    monkeypatch.setattr(update, "fetch_latest",
                        lambda: release(version=(0, 9, 3), tag="v0.9.3"))
    asked = answer(updater, updater.NOW)
    updater.check(manual=False)
    assert updater.told == []
    updater.check(manual=True)
    assert asked == [] and "latest version" in updater.told[0]


def test_a_failed_check_is_quiet_unless_asked(updater, monkeypatch):
    def offline():
        raise UpdateError("Could not reach GitHub (offline).")

    monkeypatch.setattr(update, "fetch_latest", offline)
    updater.check(manual=False)
    assert updater.told == []
    updater.check(manual=True)
    assert "Could not reach GitHub" in updater.told[0]


def test_a_failed_download_is_reported_and_nothing_runs(updater, monkeypatch):
    def broken(*a, **k):
        raise UpdateError("The download failed (reset).")

    monkeypatch.setattr(update, "fetch_latest", lambda: release())
    monkeypatch.setattr(update, "download", broken)
    answer(updater, updater.NOW)
    updater.check()
    assert updater.launched == [] and "download failed" in updater.told[0]

    answer(updater, updater.ON_CLOSE)
    updater.check()
    assert updater.pending is None
    assert any("not downloaded" in m for m in updater.messages)


def test_the_automatic_check_waits_a_day_and_respects_the_switch(
        updater, monkeypatch):
    import time

    from PySide6.QtCore import QTimer

    from evans.ui import persist

    scheduled = []
    monkeypatch.setattr(QTimer, "singleShot",
                        lambda ms, fn: scheduled.append(ms))
    updater.start()
    assert len(scheduled) == 1                  # never checked: due

    persist.set_update_last_check(time.time())
    updater.start()
    assert len(scheduled) == 1                  # checked just now

    persist.set_update_last_check(0)
    persist.set_update_auto_check(False)
    updater.start()
    assert len(scheduled) == 1                  # switched off

    persist.set_update_auto_check(True)
    monkeypatch.setattr(update, "can_install", lambda: False)
    updater.start()
    assert len(scheduled) == 1                  # running from source


def test_a_copy_from_source_only_points_at_the_release(updater, monkeypatch):
    monkeypatch.setattr(update, "can_install", lambda: False)
    monkeypatch.setattr(update, "fetch_latest", lambda: release())
    pages = []
    updater._ask_open_page = lambda rel: pages.append(rel) or False
    asked = answer(updater, updater.NOW)
    updater.check()
    assert len(pages) == 1 and asked == [] and updater.launched == []


def test_the_help_menu_offers_updates():
    from PySide6.QtWidgets import QApplication, QMenu

    from evans.ui.mainwindow import MainWindow

    QApplication.instance() or QApplication([])
    win = MainWindow()
    try:
        texts = [action.text() for menu in win.findChildren(QMenu)
                 for action in menu.actions()]
        assert "Check for &updates…" in texts
        assert "Check for updates &automatically" in texts
    finally:
        win.close()
        win.deleteLater()


def test_background_work_reports_back_on_the_gui_thread():
    import threading
    import time

    from PySide6.QtWidgets import QApplication, QWidget

    from evans.ui.updater import Updater

    app = QApplication.instance() or QApplication([])
    parent = QWidget()
    up = Updater(parent)
    results = []

    def failing():
        raise UpdateError("offline")

    up._in_background(lambda: threading.current_thread().name,
                      lambda r: results.append((r, threading.current_thread())))
    up._in_background(failing, lambda r: results.append((r, None)))
    deadline = time.monotonic() + 5
    while len(results) < 2 and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    parent.deleteLater()

    worker = next(r for r in results if r[1] is not None)
    assert worker == ("evans-update", threading.main_thread())
    assert any(isinstance(r, UpdateError) for r, _ in results)
