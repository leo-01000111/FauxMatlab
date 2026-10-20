"""
The Windows half of the integrated title bar: the caption goes, the frame stays.

A frameless window (``Qt.FramelessWindowHint``) would lose everything Windows
gives a window for free — the drop shadow, the rounded corners on Windows 11,
resizing from the edges, Aero Snap, the Snap Layouts flyout over maximise.
So the native frame is kept, and only its caption is taken away:

``WM_NCCALCSIZE``
    Windows computes the usual client rectangle (inside the left, right and
    bottom resize borders), and then its top is put back where the window's
    top is. The caption strip becomes client area, which the title bar
    widget paints. Qt (since 6.6, QTBUG-113736) works its frame margins out
    from the window and client rectangles, so it follows this shape and
    ``saveGeometry`` stays right. A maximised window hangs its frame off the
    screen edges by the frame thickness, so there the top moves down by that
    much, or the top of the title bar would be cut off.

``WM_NCHITTEST``
    The side and bottom borders are still non-client: Windows answers for
    them. Over the client area this module answers, in this order: the top
    resize band (gone with the caption, so it is put back by hand), our
    maximise button (``HTMAXBUTTON`` — what Windows 11 needs to open Snap
    Layouts on hover), the title bar's empty space (``HTCAPTION`` — dragging,
    snapping, double-click to maximise, right-click for the system menu),
    and everything else is ``HTCLIENT``, Qt's as usual.

An auto-hide taskbar appears when the mouse reaches the screen edge it hides
behind, but a maximised window with its caption gone covers that edge too.
So a maximised window leaves a 2-pixel gap on each edge of its monitor that
has an auto-hide bar (``ABM_GETAUTOHIDEBAREX``), as Windows Terminal and
Chromium do.

Because the maximise button answers ``HTMAXBUTTON``, Windows sends it
non-client mouse messages rather than client ones; :class:`NativeFrame`
turns those into hover, press and click on the Qt button.

Every Win32 function is declared with ``argtypes`` and ``restype`` before it
is called. Without them ctypes passes handles as 32-bit ints on 64-bit
Windows and calls fail silently — exactly what happened to
``TerminateProcess`` in ``tests/conftest.py``.

Anything that goes wrong turns the integration off and leaves the ordinary
title bar: :meth:`NativeFrame.install` returns False, and an exception while
handling a message calls the window's ``on_failure``.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PySide6.QtGui import QGuiApplication

# ── messages and hit-test codes ─────────────────────────────────

WM_NCCALCSIZE = 0x0083
WM_NCHITTEST = 0x0084
WM_NCMOUSEMOVE = 0x00A0
WM_NCLBUTTONDOWN = 0x00A1
WM_NCLBUTTONUP = 0x00A2
WM_NCLBUTTONDBLCLK = 0x00A3
WM_NCMOUSELEAVE = 0x02A2
WM_NCRBUTTONUP = 0x00A5
WM_SYSCOMMAND = 0x0112

SC_SIZE, SC_MOVE, SC_MINIMIZE = 0xF000, 0xF010, 0xF020
SC_MAXIMIZE, SC_CLOSE, SC_RESTORE = 0xF030, 0xF060, 0xF120
MF_BYCOMMAND, MF_ENABLED, MF_GRAYED = 0x0000, 0x0000, 0x0001
TPM_RIGHTBUTTON, TPM_RETURNCMD = 0x0002, 0x0100

HTCLIENT = 1
HTCAPTION = 2
HTMAXBUTTON = 9
HTLEFT, HTRIGHT, HTTOP = 10, 11, 12
HTTOPLEFT, HTTOPRIGHT = 13, 14
HTBOTTOM, HTBOTTOMLEFT, HTBOTTOMRIGHT = 15, 16, 17

SM_CXSIZEFRAME = 32
SM_CYSIZEFRAME = 33
SM_CXPADDEDBORDER = 92

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020

ABM_GETSTATE = 0x04
ABM_GETAUTOHIDEBAREX = 0x0B
ABS_AUTOHIDE = 0x01
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = 0, 1, 2, 3
MONITOR_DEFAULTTONEAREST = 2

#: How far a maximised window keeps off an auto-hide taskbar's edge, in
#: physical pixels: enough for the mouse to touch the edge and reveal it.
AUTOHIDE_GAP = 2

TME_LEAVE = 0x00000002
TME_NONCLIENT = 0x00000010

LRESULT = ctypes.c_ssize_t

#: The messages :meth:`NativeFrame.handle` looks at; everything else goes
#: straight back to Qt without leaving this set lookup.
HANDLED = frozenset((WM_NCCALCSIZE, WM_NCHITTEST, WM_NCMOUSEMOVE,
                     WM_NCLBUTTONDOWN, WM_NCLBUTTONUP, WM_NCLBUTTONDBLCLK,
                     WM_NCMOUSELEAVE, WM_NCRBUTTONUP))


def system_menu_states(maximized: bool) -> dict[int, bool]:
    """
    Which system-menu commands are on, as Windows itself would set them.

    The caption that used to show this menu on right-click is gone, so the
    menu is shown by hand, and its items have to be enabled by hand too.
    """
    return {SC_RESTORE: maximized, SC_MOVE: not maximized,
            SC_SIZE: not maximized, SC_MINIMIZE: True,
            SC_MAXIMIZE: not maximized, SC_CLOSE: True}


class NCCALCSIZE_PARAMS(ctypes.Structure):  # noqa: N801 (Win32 name)
    _fields_ = [("rgrc", wintypes.RECT * 3), ("lppos", ctypes.c_void_p)]


class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND),
                ("uCallbackMessage", wintypes.UINT), ("uEdge", wintypes.UINT),
                ("rc", wintypes.RECT), ("lParam", wintypes.LPARAM)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                ("hwndTrack", wintypes.HWND), ("dwHoverTime", wintypes.DWORD)]


def supported() -> bool:
    """Whether this process can integrate the title bar at all."""
    if sys.platform != "win32":
        return False
    app = QGuiApplication.instance()
    return app is not None and QGuiApplication.platformName() == "windows"


# ── the pure part: which code a point gets ──────────────────────

def client_hit(region: str, y: int, x: int, width: int, band: int,
               maximized: bool) -> int:
    """
    The hit-test code for a point Windows called client area.

    ``region`` is what the title bar says is under the point (``"caption"``,
    ``"maximize"`` or ``"client"``); ``x``, ``y`` and ``width`` are in the
    window's own physical pixels, ``band`` is the resize-border thickness.
    A maximised window has no resize band: it cannot be resized.
    """
    if not maximized and y < band:
        if x < band:
            return HTTOPLEFT
        if x >= width - band:
            return HTTOPRIGHT
        return HTTOP
    if region == "maximize":
        return HTMAXBUTTON
    if region == "caption":
        return HTCAPTION
    return HTCLIENT


def autohide_inset(rect, edges, gap: int = AUTOHIDE_GAP) -> None:
    """
    Pull a maximised client rectangle in by ``gap`` on each auto-hide edge.

    ``rect`` has ``left``/``top``/``right``/``bottom`` and is changed in place;
    ``edges`` holds ``ABE_*`` values.
    """
    if ABE_LEFT in edges:
        rect.left += gap
    if ABE_TOP in edges:
        rect.top += gap
    if ABE_RIGHT in edges:
        rect.right -= gap
    if ABE_BOTTOM in edges:
        rect.bottom -= gap


# ── the Win32 functions, declared ───────────────────────────────

class _Win32:
    """The handful of user32 calls this needs, each fully declared."""

    def __init__(self) -> None:
        user32 = ctypes.WinDLL("user32")

        self.DefWindowProcW = user32.DefWindowProcW
        self.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT,
                                        wintypes.WPARAM, wintypes.LPARAM]
        self.DefWindowProcW.restype = LRESULT

        self.ScreenToClient = user32.ScreenToClient
        self.ScreenToClient.argtypes = [wintypes.HWND,
                                        ctypes.POINTER(wintypes.POINT)]
        self.ScreenToClient.restype = wintypes.BOOL

        self.GetClientRect = user32.GetClientRect
        self.GetClientRect.argtypes = [wintypes.HWND,
                                       ctypes.POINTER(wintypes.RECT)]
        self.GetClientRect.restype = wintypes.BOOL

        self.IsZoomed = user32.IsZoomed
        self.IsZoomed.argtypes = [wintypes.HWND]
        self.IsZoomed.restype = wintypes.BOOL

        self.SetWindowPos = user32.SetWindowPos
        self.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND,
                                      ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int,
                                      wintypes.UINT]
        self.SetWindowPos.restype = wintypes.BOOL

        self.TrackMouseEvent = user32.TrackMouseEvent
        self.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
        self.TrackMouseEvent.restype = wintypes.BOOL

        self.GetSystemMetrics = user32.GetSystemMetrics
        self.GetSystemMetrics.argtypes = [ctypes.c_int]
        self.GetSystemMetrics.restype = ctypes.c_int

        self.GetSystemMenu = user32.GetSystemMenu
        self.GetSystemMenu.argtypes = [wintypes.HWND, wintypes.BOOL]
        self.GetSystemMenu.restype = wintypes.HMENU

        self.EnableMenuItem = user32.EnableMenuItem
        self.EnableMenuItem.argtypes = [wintypes.HMENU, wintypes.UINT,
                                        wintypes.UINT]
        self.EnableMenuItem.restype = wintypes.BOOL

        self.TrackPopupMenu = user32.TrackPopupMenu
        self.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT,
                                        ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, wintypes.HWND,
                                        ctypes.c_void_p]
        self.TrackPopupMenu.restype = wintypes.BOOL     # the command id here

        self.PostMessageW = user32.PostMessageW
        self.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                      wintypes.WPARAM, wintypes.LPARAM]
        self.PostMessageW.restype = wintypes.BOOL

        self.MonitorFromWindow = user32.MonitorFromWindow
        self.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        self.MonitorFromWindow.restype = wintypes.HMONITOR

        self.GetMonitorInfoW = user32.GetMonitorInfoW
        self.GetMonitorInfoW.argtypes = [wintypes.HMONITOR,
                                         ctypes.POINTER(MONITORINFO)]
        self.GetMonitorInfoW.restype = wintypes.BOOL

        shell32 = ctypes.WinDLL("shell32")
        self.SHAppBarMessage = shell32.SHAppBarMessage
        self.SHAppBarMessage.argtypes = [wintypes.DWORD,
                                         ctypes.POINTER(APPBARDATA)]
        self.SHAppBarMessage.restype = ctypes.c_size_t

        # Per-monitor DPI versions: Windows 10 1607 and later.
        self.GetDpiForWindow = getattr(user32, "GetDpiForWindow", None)
        self.GetSystemMetricsForDpi = getattr(user32, "GetSystemMetricsForDpi",
                                              None)
        if self.GetDpiForWindow is not None:
            self.GetDpiForWindow.argtypes = [wintypes.HWND]
            self.GetDpiForWindow.restype = wintypes.UINT
        if self.GetSystemMetricsForDpi is not None:
            self.GetSystemMetricsForDpi.argtypes = [ctypes.c_int,
                                                    wintypes.UINT]
            self.GetSystemMetricsForDpi.restype = ctypes.c_int

    def metric(self, index: int, hwnd: int) -> int:
        if self.GetDpiForWindow and self.GetSystemMetricsForDpi:
            dpi = self.GetDpiForWindow(hwnd)
            if dpi:
                return self.GetSystemMetricsForDpi(index, dpi)
        return self.GetSystemMetrics(index)

    def autohide_edges(self, hwnd: int) -> set[int]:
        """The edges of ``hwnd``'s monitor that have an auto-hide appbar."""
        bar = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA))
        if not self.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(bar)) \
                & ABS_AUTOHIDE:
            return set()
        monitor = self.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        if not monitor or not self.GetMonitorInfoW(monitor,
                                                   ctypes.byref(info)):
            return set()
        edges = set()
        for edge in (ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM):
            bar = APPBARDATA(cbSize=ctypes.sizeof(APPBARDATA), uEdge=edge,
                             rc=info.rcMonitor)
            if self.SHAppBarMessage(ABM_GETAUTOHIDEBAREX, ctypes.byref(bar)):
                edges.add(edge)
        return edges

    def frame_y(self, hwnd: int) -> int:
        """The resize border's height, padding included, in physical px."""
        return (self.metric(SM_CYSIZEFRAME, hwnd) +
                self.metric(SM_CXPADDEDBORDER, hwnd))


def _signed_point(lparam: int) -> tuple[int, int]:
    """GET_X_LPARAM / GET_Y_LPARAM: screen coordinates can be negative."""
    x = ctypes.c_short(lparam & 0xFFFF).value
    y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
    return x, y


# ── the window's side ───────────────────────────────────────────

class NativeFrame:
    """
    Handles a top-level window's non-client messages for the title bar.

    ``window`` is the QMainWindow; ``bar`` answers ``region_at(QPoint)`` in
    the window's logical coordinates and owns the maximise button
    (``bar.maximize_button`` with ``set_native_hover`` / ``set_native_down``
    and ``click``).
    """

    def __init__(self, window, bar) -> None:
        self._window = window
        self._bar = bar
        self._api: _Win32 | None = None
        self.enabled = False
        self._max_down = False
        self._tracking = False

    # ── turning it on and off ──

    def install(self) -> bool:
        """Take the caption away. Returns whether it worked."""
        if not supported():
            return False
        try:
            if self._api is None:
                self._api = _Win32()
            self.enabled = True
            self._frame_changed()
        except (OSError, AttributeError, ValueError):
            self.enabled = False
            return False
        return True

    def uninstall(self) -> None:
        """Give the caption back."""
        was = self.enabled
        self.enabled = False
        self._bar.maximize_button.set_native_hover(False)
        if was and self._api is not None:
            try:
                self._frame_changed()
            except OSError:
                pass

    def _frame_changed(self) -> None:
        """Make Windows send WM_NCCALCSIZE again, with the new rules."""
        hwnd = int(self._window.winId())
        self._api.SetWindowPos(hwnd, None, 0, 0, 0, 0,
                               SWP_FRAMECHANGED | SWP_NOMOVE | SWP_NOSIZE |
                               SWP_NOZORDER | SWP_NOACTIVATE)

    # ── messages ──

    def handle(self, message: int) -> tuple[bool, int]:
        """``nativeEvent``'s answer for one ``MSG*``."""
        msg = wintypes.MSG.from_address(message)
        kind = msg.message
        if not self.enabled or kind not in HANDLED:
            return False, 0
        if self._window.isFullScreen():
            return False, 0
        hwnd = msg.hWnd
        api = self._api
        if kind == WM_NCCALCSIZE:
            return self._calc_size(api, hwnd, msg.wParam, msg.lParam)
        if kind == WM_NCHITTEST:
            return self._hit_test(api, hwnd, msg.wParam, msg.lParam)

        if kind == WM_NCRBUTTONUP:
            if msg.wParam != HTCAPTION:
                return False, 0
            self._system_menu(api, hwnd, *_signed_point(msg.lParam))
            return True, 0

        button = self._bar.maximize_button
        on_max = msg.wParam == HTMAXBUTTON
        if kind == WM_NCMOUSEMOVE:
            button.set_native_hover(on_max)
            if not on_max:
                self._max_down = False
                button.set_native_down(False)
            self._track_leave(api, hwnd)
            return False, 0
        if kind == WM_NCMOUSELEAVE:
            self._tracking = False
            self._max_down = False
            button.set_native_hover(False)
            button.set_native_down(False)
            return False, 0
        if not on_max:
            return False, 0
        # Ours from here: left to DefWindowProc, a press on HTMAXBUTTON draws
        # the classic Windows 95 maximise button over ours.
        if kind in (WM_NCLBUTTONDOWN, WM_NCLBUTTONDBLCLK):
            self._max_down = True
            button.set_native_down(True)
        elif kind == WM_NCLBUTTONUP:
            clicked = self._max_down
            self._max_down = False
            button.set_native_down(False)
            if clicked:
                button.click()
        return True, 0

    def _system_menu(self, api: _Win32, hwnd, x: int, y: int) -> None:
        """
        Right-click on the bar: the window's own system menu, at the cursor.

        Windows shows it for a right-click on a caption, and this bar is a
        caption to Windows (HTCAPTION), but with the real caption gone the
        menu no longer appeared. Shown and carried out by hand, as Chromium
        and Windows Terminal do.
        """
        menu = api.GetSystemMenu(hwnd, False)
        if not menu:
            return
        for command, on in system_menu_states(
                bool(api.IsZoomed(hwnd))).items():
            api.EnableMenuItem(menu, command,
                               MF_BYCOMMAND | (MF_ENABLED if on
                                               else MF_GRAYED))
        command = api.TrackPopupMenu(menu, TPM_RETURNCMD | TPM_RIGHTBUTTON,
                                     x, y, 0, hwnd, None)
        if command:
            api.PostMessageW(hwnd, WM_SYSCOMMAND, command, 0)

    def _calc_size(self, api: _Win32, hwnd, wparam, lparam):
        if not wparam:
            return False, 0
        params = NCCALCSIZE_PARAMS.from_address(lparam)
        top = params.rgrc[0].top
        api.DefWindowProcW(hwnd, WM_NCCALCSIZE, wparam, lparam)
        # Windows has taken the borders off all four sides; the top goes
        # back, which removes the caption with it.
        params.rgrc[0].top = top
        if api.IsZoomed(hwnd):
            params.rgrc[0].top += api.frame_y(hwnd)
            autohide_inset(params.rgrc[0], api.autohide_edges(hwnd))
        return True, 0

    def _hit_test(self, api: _Win32, hwnd, wparam, lparam):
        code = api.DefWindowProcW(hwnd, WM_NCHITTEST, wparam, lparam)
        if code != HTCLIENT:
            self._bar.maximize_button.set_native_hover(False)
            return True, code
        sx, sy = _signed_point(lparam)
        point = wintypes.POINT(sx, sy)
        api.ScreenToClient(hwnd, ctypes.byref(point))
        rect = wintypes.RECT()
        api.GetClientRect(hwnd, ctypes.byref(rect))

        from PySide6.QtCore import QPoint

        ratio = self._window.devicePixelRatioF() or 1.0
        logical = QPoint(round(point.x / ratio), round(point.y / ratio))
        region = self._bar.region_at(self._window, logical)
        code = client_hit(region, point.y, point.x, rect.right,
                          api.frame_y(hwnd), bool(api.IsZoomed(hwnd)))
        self._bar.maximize_button.set_native_hover(code == HTMAXBUTTON)
        return True, code

    def _track_leave(self, api: _Win32, hwnd) -> None:
        """Ask for WM_NCMOUSELEAVE, so hover ends when the mouse leaves."""
        if self._tracking:
            return
        event = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT),
                                TME_LEAVE | TME_NONCLIENT, hwnd, 0)
        self._tracking = bool(api.TrackMouseEvent(ctypes.byref(event)))
