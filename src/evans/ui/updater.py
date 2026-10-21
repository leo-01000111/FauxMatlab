"""
Help ▸ Check for updates, and the check Evans makes by itself.

A few seconds after start-up, at most once a day, Evans asks GitHub whether
there is a newer release (:mod:`evans.update`). If there is, one prompt:

* **Update now** — download with a progress bar, then hand over to the
  installer, which replaces Evans and opens it again.
* **Update when I close Evans** — download in the background; the installer
  runs silently once the window closes, and the next launch is the new
  version. If the download has not finished by then, nothing happens and the
  next check offers it again.
* **Later** — nothing; the next check asks again, unless *Don't remind me
  about this version* was ticked.

The network work runs on a plain thread, so a slow or absent connection
never holds the window. Results come back to the GUI thread through a
signal. An automatic check that fails says nothing; a check asked for from
the menu says what went wrong.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QMessageBox, QProgressDialog, QWidget

from .. import update
from ..update import Release, UpdateError
from . import persist, theme

#: How long after start-up the automatic check waits, so it never competes
#: with the window opening.
STARTUP_DELAY_MS = 5000
#: The automatic check runs at most this often.
CHECK_INTERVAL_S = 24 * 3600


class _Bridge(QObject):
    """Carries a worker thread's result to the GUI thread (a queued signal)."""

    done = Signal(object, object)


class Updater(QObject):

    #: A status-bar line: (message, milliseconds; 0 keeps it).
    status = Signal(str, int)

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self._window = parent
        self._bridge = _Bridge(self)
        self._bridge.done.connect(lambda callback, result: callback(result))
        self._busy = False
        #: The installer to run when the window closes, once downloaded.
        self._pending: Path | None = None

    # ── Checking ──────────────────────────────────────────────

    def start(self) -> None:
        """The automatic check, if it is on and due. Call once at launch."""
        if not update.can_install() or not persist.update_auto_check():
            return
        if time.time() - persist.update_last_check() < CHECK_INTERVAL_S:
            return
        QTimer.singleShot(STARTUP_DELAY_MS, lambda: self.check(manual=False))

    def check(self, *, manual: bool = True) -> None:
        if self._busy:
            if manual:
                self.status.emit("Already checking for updates…", 4000)
            return
        self._busy = True
        if manual:
            self.status.emit("Checking for updates…", 0)
        self._in_background(update.fetch_latest,
                            lambda result: self._checked(result, manual))

    def _checked(self, result, manual: bool) -> None:
        self._busy = False
        if manual:
            self.status.emit("", 1)
        if isinstance(result, UpdateError):
            if manual:
                self._tell("Check for updates", str(result))
            return
        persist.set_update_last_check(time.time())
        release: Release | None = result
        if release is None or not update.is_newer(release):
            if manual:
                self._tell("Check for updates",
                           f"Evans {update.__version__} is the latest version.")
            return
        if not manual and persist.update_skipped() == release.tag:
            return
        self.offer(release)

    # ── The prompt ────────────────────────────────────────────

    NOW, ON_CLOSE, LATER = "now", "on_close", "later"

    def offer(self, release: Release) -> None:
        if not update.can_install():
            # From a checkout there is no installed copy to replace.
            if self._ask_open_page(release):
                QDesktopServices.openUrl(QUrl(release.notes_url))
            return
        choice, skip = self._ask(release)
        if skip:
            persist.set_update_skipped(release.tag)
        if choice == self.NOW:
            self._update_now(release)
        elif choice == self.ON_CLOSE:
            self._update_on_close(release)

    def _ask(self, release: Release) -> tuple[str, bool]:
        """(choice, don't remind me). A method so tests can answer it."""
        t = theme.tokens()
        box = QMessageBox(self._window)
        box.setWindowTitle("Update available")
        box.setTextFormat(Qt.RichText)
        box.setText(
            f"Evans {release.label} is available "
            f"(you have {update.__version__}). "
            f'<a href="{release.notes_url}">What\'s new</a>')
        box.setInformativeText(
            "Update now closes Evans: unsaved models, scripts and figures "
            "are not kept, so save anything you need first.")
        box.setTextInteractionFlags(Qt.TextBrowserInteraction)
        now = box.addButton("Update now", QMessageBox.AcceptRole)
        on_close = box.addButton("Update when I close Evans",
                                 QMessageBox.ActionRole)
        later = box.addButton("Later", QMessageBox.RejectRole)
        now.setStyleSheet(
            f"QPushButton {{ background: {t.lamp_go}; color: #ffffff; "
            f"border: none; padding: 6px 16px; font-weight: 600; }}")
        for button in (on_close, later):
            button.setStyleSheet(
                f"QPushButton {{ background: {t.hold}; color: {t.on_hold}; "
                f"border: none; padding: 6px 16px; font-weight: 600; }}")
        for button in (now, on_close, later):
            font = button.font()
            font.setWordSpacing(4)
            button.setFont(font)
        skip = QCheckBox("Don't remind me about this version")
        box.setCheckBox(skip)
        box.setDefaultButton(on_close)
        box.setEscapeButton(later)
        box.exec()
        clicked = box.clickedButton()
        choice = (self.NOW if clicked is now else
                  self.ON_CLOSE if clicked is on_close else self.LATER)
        return choice, skip.isChecked()

    def _ask_open_page(self, release: Release) -> bool:
        """True to open the release page. A method so tests can answer it."""
        answer = QMessageBox.question(
            self._window, "Update available",
            f"Evans {release.label} is available (you have "
            f"{update.__version__}). This copy runs from source, so it "
            "cannot update itself. Open the release page?")
        return answer == QMessageBox.Yes

    def _tell(self, title: str, text: str) -> None:
        """A method so tests can read it."""
        QMessageBox.information(self._window, title, text)

    # ── Now ───────────────────────────────────────────────────

    def _update_now(self, release: Release) -> None:
        if self._pending is not None:       # already fetched for "on close"
            self._install(self._pending, relaunch=True)
            return
        dialog = QProgressDialog(f"Downloading Evans {release.label}…",
                                 "Cancel", 0, 1000, self._window)
        dialog.setWindowTitle("Update")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        progress = _Progress()
        timer = QTimer(dialog, interval=100)
        timer.timeout.connect(lambda: dialog.setValue(progress.permille))
        timer.start()
        dialog.canceled.connect(progress.cancel)
        self._busy = True

        def finished(result) -> None:
            self._busy = False
            timer.stop()
            # Read first: closing a progress dialog emits `canceled` too.
            cancelled = progress.cancelled
            dialog.close()
            if isinstance(result, UpdateError):
                if not cancelled:
                    self._tell("Update", str(result))
                return
            self._install(result, relaunch=True)

        dialog.show()
        self._in_background(
            lambda: update.download(release, progress=progress.report,
                                    cancelled=lambda: progress.cancelled),
            finished)

    # ── On close ──────────────────────────────────────────────

    def _update_on_close(self, release: Release) -> None:
        if self._pending is not None:
            return
        self._busy = True
        self.status.emit(f"Downloading Evans {release.label}…", 0)

        def finished(result) -> None:
            self._busy = False
            if isinstance(result, UpdateError):
                self.status.emit(f"Update not downloaded: {result}", 8000)
                return
            self._pending = result
            self.status.emit(
                f"Evans {release.label} will install when you close Evans.",
                8000)

        self._in_background(lambda: update.download(release), finished)

    @property
    def pending(self) -> Path | None:
        return self._pending

    def install_pending(self) -> bool:
        """The window is closing: run a downloaded installer, if there is one."""
        if self._pending is None or not self._pending.is_file():
            return False
        return self._install(self._pending, relaunch=False, quit_app=False)

    # ── Handing over ──────────────────────────────────────────

    def _install(self, installer: Path, *, relaunch: bool,
                 quit_app: bool = True) -> bool:
        if not self._launch(str(installer),
                            update.installer_arguments(relaunch=relaunch)):
            self._tell("Update", "The installer could not be started. "
                       f"It is saved at {installer}.")
            return False
        self._pending = None
        if quit_app:
            self._window.close()
            from PySide6.QtWidgets import QApplication

            QApplication.instance().quit()
        return True

    @staticmethod
    def _launch(program: str, args: list[str]) -> bool:
        """A method so tests can stop the real installer."""
        ok = QProcess.startDetached(program, args, os.getcwd())
        return bool(ok[0] if isinstance(ok, tuple) else ok)

    def _in_background(self, work: Callable[[], object],
                       then: Callable[[object], None]) -> None:
        """
        Run ``work`` on a thread, then ``then(result)`` on the GUI thread.

        An :class:`UpdateError` raised by ``work`` is passed as the result.
        A method so tests can run it in line.
        """
        def run() -> None:
            try:
                result = work()
            except UpdateError as exc:
                result = exc
            except Exception as exc:        # noqa: BLE001 - never kill the thread silently
                result = UpdateError(str(exc))
            self._bridge.done.emit(then, result)

        threading.Thread(target=run, name="evans-update", daemon=True).start()


class _Progress:
    """Download progress, written by the worker and read by a GUI timer."""

    def __init__(self) -> None:
        self.permille = 0
        self.cancelled = False

    def report(self, received: int, total: int) -> None:
        if total:
            self.permille = min(1000, received * 1000 // total)

    def cancel(self) -> None:
        self.cancelled = True
