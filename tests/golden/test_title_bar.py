"""
The integrated title bar: what can be checked without a real Windows frame.

The suite runs on the offscreen platform, where :func:`winframe.supported` is
False, so the window here is always in its fallback: the system's caption
and a plain menu bar. Tests that need the integrated strip turn its chrome on
directly (what the Windows path does once Windows has accepted the frame).
The Win32 side — drag, snap, resize, Snap Layouts — can only be checked by
hand on Windows; ``client_hit`` and the message handling are checked here
with made-up messages.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

import pytest

pytest.importorskip("PySide6", reason="Qt not available")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from evans.core.architecture import CourseArchitecture
from evans.ui import persist, theme, winframe
from evans.ui.mainwindow import MainWindow
from evans.ui.titlebar import BAR_HEIGHT, TitleBar

TARGET_W, TARGET_H = 1280, 720


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture(scope="module")
def win(app):
    window = MainWindow(CourseArchitecture())
    window.resize(1400, 850)
    window.show()
    _settle(app)
    yield window
    window.hide()


@pytest.fixture
def chrome(app, win):
    """The strip as Windows shows it: plate, title and buttons."""
    win.title_bar.set_chrome_visible(True)
    _settle(app)
    yield win.title_bar
    win.title_bar.set_chrome_visible(False)
    _settle(app)


def _settle(app, rounds: int = 10) -> None:
    for _ in range(rounds):
        app.processEvents()


def _centre(widget, win) -> QPoint:
    return widget.mapTo(win, widget.rect().center())


# ── structure ───────────────────────────────────────────────────

def test_the_title_bar_is_the_menu_widget_and_holds_the_menus(win):
    bar = win.menuWidget()
    assert isinstance(bar, TitleBar)
    assert win.menuBar() is bar.menu_bar
    assert bar.menu_bar.parentWidget() is bar
    titles = [a.text().replace("&", "") for a in win.menuBar().actions()]
    assert titles == ["File", "Export", "View", "Apps", "Presets",
                      "Help"]


def test_menu_bar_does_not_replace_the_title_bar(win):
    """QMainWindow.menuBar() would make a new bar in its place."""
    win.menuBar()
    win.menuBar()
    assert isinstance(win.menuWidget(), TitleBar)


def test_the_bar_shows_the_plate_and_follows_the_title(app, win, chrome):
    assert not chrome.plate.pixmap().isNull()
    assert chrome.plate.pixmap().width() == 16
    win.setWindowTitle("Evans — test")
    _settle(app)
    assert chrome.title.text() == "Evans — test"
    win.setWindowTitle(MainWindow.APP_TITLE)


def test_the_strip_has_the_caption_height(chrome):
    assert chrome.height() == BAR_HEIGHT
    for button in (chrome.minimize_button, chrome.maximize_button,
                   chrome.close_button):
        assert button.isVisible()
        assert button.height() == BAR_HEIGHT


def test_the_window_still_fits_1280x720_with_the_strip(app, win, chrome):
    hint = win.minimumSizeHint()
    assert hint.width() <= TARGET_W
    assert hint.height() <= TARGET_H
    win.resize(TARGET_W, TARGET_H)
    _settle(app)
    assert (win.width(), win.height()) == (TARGET_W, TARGET_H)
    win.resize(1400, 850)


# ── the buttons ─────────────────────────────────────────────────

def _calls(monkeypatch, win, *names):
    seen = []
    for name in names:
        monkeypatch.setattr(win, name, lambda n=name: seen.append(n))
    return seen


def test_minimize_calls_show_minimized(win, chrome, monkeypatch):
    seen = _calls(monkeypatch, win, "showMinimized")
    chrome.minimize_button.click()
    assert seen == ["showMinimized"]


def test_maximize_toggles_between_maximized_and_normal(win, chrome,
                                                       monkeypatch):
    seen = _calls(monkeypatch, win, "showMaximized", "showNormal")
    monkeypatch.setattr(win, "isMaximized", lambda: False)
    chrome.maximize_button.click()
    monkeypatch.setattr(win, "isMaximized", lambda: True)
    chrome.maximize_button.click()
    assert seen == ["showMaximized", "showNormal"]


def test_close_calls_close(win, chrome, monkeypatch):
    seen = _calls(monkeypatch, win, "close")
    chrome.close_button.click()
    assert seen == ["close"]


def test_the_maximize_glyph_becomes_restore(win, chrome, monkeypatch):
    monkeypatch.setattr(win, "isMaximized", lambda: True)
    chrome.sync_window_state()
    assert chrome.maximize_button.glyph == "window-restore"
    monkeypatch.setattr(win, "isMaximized", lambda: False)
    chrome.sync_window_state()
    assert chrome.maximize_button.glyph == "window-maximize"


def test_double_click_on_the_bar_maximizes(app, win, chrome, monkeypatch):
    seen = _calls(monkeypatch, win, "toggle_maximized")
    QTest.mouseDClick(chrome.title, Qt.LeftButton, Qt.NoModifier,
                      chrome.title.rect().center())
    _settle(app)
    assert seen == ["toggle_maximized"]


def _colours(widget) -> set[str]:
    image = widget.grab().toImage()
    return {image.pixelColor(x, y).name()
            for x in range(0, image.width(), 2)
            for y in range(0, image.height(), 2)}


def test_close_turns_red_on_hover(app, chrome):
    button = chrome.close_button
    assert theme.tokens().hold not in _colours(button)
    button.set_native_hover(True)
    try:
        assert theme.tokens().hold in _colours(button)
    finally:
        button.set_native_hover(False)


def test_every_button_draws_its_glyph(app, chrome):
    for button in (chrome.minimize_button, chrome.maximize_button,
                   chrome.close_button):
        assert len(_colours(button)) > 1, f"{button.kind} drew nothing"


def test_the_window_glyphs_are_in_the_icon_set():
    from evans.ui import iconset

    for name in ("minimize", "maximize", "restore", "close"):
        assert f"window-{name}" in iconset.names()


# ── what is under the mouse ─────────────────────────────────────

def test_region_at_tells_caption_from_controls(win, chrome):
    bar = chrome
    assert bar.region_at(win, _centre(bar.maximize_button, win)) == "maximize"
    assert bar.region_at(win, _centre(bar.minimize_button, win)) == "client"
    assert bar.region_at(win, _centre(bar.close_button, win)) == "client"
    assert bar.region_at(win, _centre(bar.title, win)) == "caption"
    assert bar.region_at(win, _centre(bar.plate, win)) == "caption"
    menus = bar.menu_bar
    first = menus.mapTo(win, menus.actionGeometry(menus.actions()[0]).center())
    assert bar.region_at(win, first) == "client"
    # Below the strip is the application.
    assert bar.region_at(win, QPoint(win.width() // 2, BAR_HEIGHT + 40)) \
        == "client"


def test_without_chrome_nothing_is_caption(win):
    assert not win.title_bar.chrome_visible
    centre = _centre(win.title_bar, win)
    assert win.title_bar.region_at(win, centre) == "client"


@pytest.mark.parametrize("region, y, x, maximized, code", [
    ("caption", 2, 300, False, winframe.HTTOP),
    ("caption", 2, 3, False, winframe.HTTOPLEFT),
    ("maximize", 2, 995, False, winframe.HTTOPRIGHT),
    ("maximize", 2, 900, True, winframe.HTMAXBUTTON),
    ("caption", 2, 300, True, winframe.HTCAPTION),
    ("maximize", 20, 900, False, winframe.HTMAXBUTTON),
    ("caption", 20, 300, False, winframe.HTCAPTION),
    ("client", 20, 300, False, winframe.HTCLIENT),
    ("client", 400, 300, False, winframe.HTCLIENT),
])
def test_client_hit_codes(region, y, x, maximized, code):
    assert winframe.client_hit(region, y, x, 1000, 8, maximized) == code


# ── the native messages, made up ────────────────────────────────

def _message(kind: int, wparam: int = 0, lparam: int = 0):
    msg = wintypes.MSG()
    msg.message = kind
    msg.wParam = wparam
    msg.lParam = lparam
    return msg


def test_a_click_on_htmaxbutton_clicks_our_button(win, chrome, monkeypatch):
    seen = _calls(monkeypatch, win, "toggle_maximized")
    frame = winframe.NativeFrame(win, chrome)
    frame.enabled = True
    down = _message(winframe.WM_NCLBUTTONDOWN, winframe.HTMAXBUTTON)
    up = _message(winframe.WM_NCLBUTTONUP, winframe.HTMAXBUTTON)
    assert frame.handle(ctypes.addressof(down)) == (True, 0)
    assert frame.handle(ctypes.addressof(up)) == (True, 0)
    assert seen == ["toggle_maximized"]


def test_other_messages_go_back_to_qt(win, chrome):
    frame = winframe.NativeFrame(win, chrome)
    frame.enabled = True
    paint = _message(0x000F)                         # WM_PAINT
    assert frame.handle(ctypes.addressof(paint)) == (False, 0)
    caption_click = _message(winframe.WM_NCLBUTTONDOWN, winframe.HTCAPTION)
    assert frame.handle(ctypes.addressof(caption_click)) == (False, 0)
    frame.enabled = False
    down = _message(winframe.WM_NCLBUTTONDOWN, winframe.HTMAXBUTTON)
    assert frame.handle(ctypes.addressof(down)) == (False, 0)


def test_a_failing_handler_falls_back_to_the_system_caption(app, win,
                                                            monkeypatch):
    frame = win._native_frame

    def broken(_message):
        raise RuntimeError("boom")

    monkeypatch.setattr(frame, "enabled", True)
    monkeypatch.setattr(frame, "handle", broken)
    msg = _message(winframe.WM_NCHITTEST)
    assert win.nativeEvent(b"windows_generic_MSG",
                           ctypes.addressof(msg)) == (False, 0)
    assert frame.enabled is False
    _settle(app)
    assert not win.title_bar.chrome_visible


# ── the toggle and the fallback ─────────────────────────────────

def test_offscreen_is_the_fallback(win):
    assert not winframe.supported()
    assert not win.integrated_title_bar
    assert not win.title_bar.close_button.isVisible()
    assert win.title_bar.isVisible(), "the menus must stay reachable"
    assert not win._act_title_bar.isEnabled()


def test_the_view_menu_has_the_toggle(win):
    from PySide6.QtWidgets import QMenu

    view = next(m for m in win.menuBar().findChildren(QMenu)
                if m.title().replace("&", "") == "View")
    texts = [a.text().replace("&", "") for a in view.actions()]
    assert "Integrated title bar" in texts


def test_the_toggle_persists(win):
    try:
        win.set_integrated_title_bar(False)
        assert persist.integrated_title_bar(default=True) is False
        assert not win._act_title_bar.isChecked()
        win.set_integrated_title_bar(True)
        assert persist.integrated_title_bar(default=False) is True
        assert win._act_title_bar.isChecked()
    finally:
        persist.settings().remove(persist.INTEGRATED_TITLE_BAR_KEY)


def test_the_default_is_on_only_where_it_works():
    persist.settings().remove(persist.INTEGRATED_TITLE_BAR_KEY)
    assert persist.integrated_title_bar(default=True) is True
    assert persist.integrated_title_bar(default=False) is False


def test_the_saved_choice_survives_reset_layout(app, win, monkeypatch):
    monkeypatch.setattr(MainWindow, "SETTINGS_ORG", "EvansTest")
    monkeypatch.setattr(MainWindow, "SETTINGS_APP", "TitleBarTest")
    try:
        win.set_integrated_title_bar(False)
        win.reset_layout()
        assert persist.integrated_title_bar(default=True) is False
    finally:
        persist.settings().remove(persist.INTEGRATED_TITLE_BAR_KEY)


def test_a_refused_frame_falls_back(win, monkeypatch):
    """Windows says yes to supported() but the Win32 calls fail."""
    monkeypatch.setattr(winframe, "supported", lambda: True)

    def refuse():
        raise OSError("no user32 here")

    monkeypatch.setattr(winframe, "_Win32", refuse)
    frame = winframe.NativeFrame(win, win.title_bar)
    monkeypatch.setattr(win, "_native_frame", frame)
    try:
        assert win.set_integrated_title_bar(True, remember=False) is False
        assert not frame.enabled
        assert not win.title_bar.chrome_visible
    finally:
        win.set_integrated_title_bar(False, remember=False)


# ── auto-hide taskbars, the Windows 10 border, the title ────────

@pytest.mark.parametrize("edges, expected", [
    (set(), (0, 0, 1920, 1080)),
    ({winframe.ABE_BOTTOM}, (0, 0, 1920, 1078)),
    ({winframe.ABE_TOP}, (0, 2, 1920, 1080)),
    ({winframe.ABE_LEFT, winframe.ABE_RIGHT}, (2, 0, 1918, 1080)),
])
def test_a_maximised_window_leaves_auto_hide_edges_uncovered(edges, expected):
    rect = wintypes.RECT(0, 0, 1920, 1080)
    winframe.autohide_inset(rect, edges)
    assert (rect.left, rect.top, rect.right, rect.bottom) == expected


@pytest.mark.skipif(not winframe.supported(), reason="needs real Windows")
def test_the_auto_hide_query_answers_on_real_windows(win):
    api = winframe._Win32()
    edges = api.autohide_edges(int(win.winId()))
    assert edges <= {winframe.ABE_LEFT, winframe.ABE_TOP,
                     winframe.ABE_RIGHT, winframe.ABE_BOTTOM}


def test_the_top_border_is_drawn_only_on_windows_10(monkeypatch):
    from evans.ui import titlebar

    class Version:
        def __init__(self, build):
            self.build = build

    monkeypatch.setattr(titlebar.sys, "platform", "win32")
    monkeypatch.setattr(titlebar.sys, "getwindowsversion",
                        lambda: Version(19045), raising=False)
    assert titlebar.draws_own_top_border()           # Windows 10 22H2
    monkeypatch.setattr(titlebar.sys, "getwindowsversion",
                        lambda: Version(22631), raising=False)
    assert not titlebar.draws_own_top_border()       # Windows 11
    monkeypatch.setattr(titlebar.sys, "platform", "linux")
    assert not titlebar.draws_own_top_border()


def test_the_window_title_is_said_once(win):
    """Qt appends an application display name to every native caption."""
    assert QApplication.applicationDisplayName() in ("", "python", "pytest",
                                                     QApplication.applicationName())
    assert win.windowTitle() == "Evans — Classical & Modern Control"
    assert win.windowTitle().count("Evans") == 1


def test_the_system_menu_is_enabled_like_windows_does():
    normal = winframe.system_menu_states(maximized=False)
    assert normal[winframe.SC_MOVE] and normal[winframe.SC_SIZE]
    assert normal[winframe.SC_MAXIMIZE] and not normal[winframe.SC_RESTORE]
    full = winframe.system_menu_states(maximized=True)
    assert full[winframe.SC_RESTORE] and not full[winframe.SC_MAXIMIZE]
    assert not full[winframe.SC_MOVE] and not full[winframe.SC_SIZE]
    assert full[winframe.SC_CLOSE] and full[winframe.SC_MINIMIZE]


def test_right_click_on_the_caption_opens_the_system_menu(win, monkeypatch):
    frame = winframe.NativeFrame(win, win.title_bar)
    frame.enabled = True
    shown = []
    monkeypatch.setattr(frame, "_system_menu",
                        lambda api, hwnd, x, y: shown.append((x, y)))
    frame._api = object()
    msg = wintypes.MSG()
    msg.message = winframe.WM_NCRBUTTONUP
    msg.wParam = winframe.HTCAPTION
    msg.lParam = (200 << 16) | 120
    assert frame.handle(ctypes.addressof(msg)) == (True, 0)
    assert shown == [(120, 200)]
    msg.wParam = winframe.HTCLIENT                 # a menu, a button: not ours
    assert frame.handle(ctypes.addressof(msg)) == (False, 0)
    assert len(shown) == 1
