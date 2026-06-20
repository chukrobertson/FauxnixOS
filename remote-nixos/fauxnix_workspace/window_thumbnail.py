"""Capture live thumbnails of X11/XWayland windows using python-xlib.

The Fauxnix Workspace itself runs under XWayland (QT_QPA_PLATFORM=xcb), and the
apps we want to thumbnail (Chromium, Firefox, terminals, etc.) are also
XWayland clients by default. python-xlib lets us query the X server directly
for window pixels, bypassing the need for a Wayland screencopy protocol.
"""

from __future__ import annotations

import os
import struct

from Xlib import X, display


def _connect():
    dpy_name = os.environ.get("DISPLAY", ":1")
    return display.Display(dpy_name)


def _window_geometry(win):
    """Return (x, y, width, height) of a window relative to root."""
    geom = win.get_geometry()
    return geom.x, geom.y, geom.width, geom.height


def _is_target_window(win, app_id: str | None = None, title: str | None = None):
    """Check whether an X window matches the requested app_id/title."""
    try:
        wm_class = win.get_wm_class()
        wm_name = win.get_wm_name() or ""
        net_name = ""
        try:
            net_wm_name = win.get_full_property(
                win.display.intern_atom("_NET_WM_NAME"), 0
            )
            if net_wm_name and net_wm_name.value:
                net_name = net_wm_name.value
        except Exception:
            pass
    except Exception:
        return False

    classes = [c for c in (wm_class or ()) if c]
    if app_id:
        app_id_l = app_id.lower()
        if app_id_l in [c.lower() for c in classes]:
            return True
        if app_id_l in str(wm_name).lower() or app_id_l in str(net_name).lower():
            return True
    if title:
        title_l = title.lower()
        if title_l in str(wm_name).lower() or title_l in str(net_name).lower():
            return True
    return False


def _find_window(dpy, app_id: str | None = None, title: str | None = None):
    """Depth-first search of the X window tree for a matching toplevel."""
    root = dpy.screen().root

    def walk(win):
        try:
            children = win.query_tree().children
        except Exception:
            return None
        # Check children first (toplevels are usually deeper than root)
        for child in children:
            found = walk(child)
            if found:
                return found
        if _is_target_window(win, app_id=app_id, title=title):
            return win
        return None

    return walk(root)


def _capture_window_pixmap(win):
    """Capture a window to raw RGBA bytes and (width, height)."""
    geom = win.get_geometry()
    width, height = geom.width, geom.height
    if width <= 0 or height <= 0:
        return None, 0, 0

    try:
        raw = win.get_image(0, 0, width, height, X.ZPixmap, 0xFFFFFFFF)
    except Exception:
        return None, 0, 0

    data = raw.data
    depth = raw.depth

    # X11 ZPixmap is usually BGRA for 32-bit, but python-xlib gives us whatever
    # the server handed back. Try to detect format from depth/length.
    expected_len = width * height * 4
    if len(data) == expected_len:
        # Assume BGRA; we will convert below.
        fmt = "bgra"
    elif len(data) == width * height * 3:
        fmt = "bgr"
    else:
        # Unknown layout; can't convert safely.
        return None, 0, 0

    if fmt == "bgra":
        rgba = bytearray(len(data))
        # BGRA -> RGBA
        for i in range(0, len(data), 4):
            rgba[i] = data[i + 2]
            rgba[i + 1] = data[i + 1]
            rgba[i + 2] = data[i]
            rgba[i + 3] = data[i + 3]
        return bytes(rgba), width, height
    elif fmt == "bgr":
        rgba = bytearray(width * height * 4)
        for i in range(width * height):
            rgba[i * 4] = data[i * 3 + 2]
            rgba[i * 4 + 1] = data[i * 3 + 1]
            rgba[i * 4 + 2] = data[i * 3]
            rgba[i * 4 + 3] = 255
        return bytes(rgba), width, height

    return None, 0, 0


def capture_thumbnail(app_id: str | None = None, title: str | None = None,
                      max_size: int = 320) -> tuple[bytes, int, int] | None:
    """Capture a thumbnail of the first matching X11 window.

    Returns (rgba_bytes, width, height) or None on failure. The returned image
    is scaled so that its largest dimension does not exceed max_size, keeping
    aspect ratio. The pixel data is RGBA ordered, suitable for QImage.
    """
    try:
        dpy = _connect()
        win = _find_window(dpy, app_id=app_id, title=title)
        if win is None:
            return None

        data, w, h = _capture_window_pixmap(win)
        dpy.close()
        if data is None:
            return None

        if w <= 0 or h <= 0:
            return None

        # Scale down while keeping aspect ratio.
        if w > max_size or h > max_size:
            scale = min(max_size / w, max_size / h)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            data = _scale_rgba(data, w, h, new_w, new_h)
            w, h = new_w, new_h

        return data, w, h
    except Exception:
        return None


def _scale_rgba(data: bytes, src_w: int, src_h: int, dst_w: int, dst_h: int) -> bytes:
    """Fast nearest-neighbor downscale of RGBA image data."""
    out = bytearray(dst_w * dst_h * 4)
    x_ratio = src_w / dst_w
    y_ratio = src_h / dst_h
    for y in range(dst_h):
        src_y = min(int(y * y_ratio), src_h - 1)
        for x in range(dst_w):
            src_x = min(int(x * x_ratio), src_w - 1)
            src_i = (src_y * src_w + src_x) * 4
            dst_i = (y * dst_w + x) * 4
            out[dst_i:dst_i + 4] = data[src_i:src_i + 4]
    return bytes(out)


def find_window_geometry(app_id: str | None = None, title: str | None = None) -> dict | None:
    """Return the screen geometry of the first matching X11 window."""
    try:
        dpy = _connect()
        win = _find_window(dpy, app_id=app_id, title=title)
        if win is None:
            return None
        x, y, w, h = _window_geometry(win)
        dpy.close()
        return {"x": x, "y": y, "width": w, "height": h}
    except Exception:
        return None


def raise_window(app_id: str | None = None, title: str | None = None) -> bool:
    """Raise an X11/XWayland window above other windows."""
    try:
        dpy = _connect()
        win = _find_window(dpy, app_id=app_id, title=title)
        if win is None:
            return False
        # Raise and ask the compositor to keep it active.
        win.configure(stack_mode=X.Above)
        # Send a client message requesting _NET_ACTIVE_WINDOW.
        root = dpy.screen().root
        net_active = dpy.intern_atom("_NET_ACTIVE_WINDOW")
        event = struct.pack(
            "BBH" + "I" * 8,
            33,  # response_type: ClientMessage
            32,  # format
            0,   # sequence
            win.id,
            net_active,
            2,  # data0: source indication (pager)
            0,  # data1
            0,  # data2
            0,  # data3
            0,  # data4
        )
        root.send_event(event, X.SubstructureRedirectMask | X.SubstructureNotifyMask)
        dpy.sync()
        dpy.close()
        return True
    except Exception:
        return False


def move_resize_window(app_id: str | None = None, title: str | None = None,
                       x: int = 0, y: int = 0,
                       width: int = 800, height: int = 600) -> bool:
    """Move and resize an X11/XWayland window."""
    try:
        dpy = _connect()
        win = _find_window(dpy, app_id=app_id, title=title)
        if win is None:
            return False
        win.configure(x=x, y=y, width=width, height=height)
        dpy.sync()
        dpy.close()
        return True
    except Exception:
        return False


def _window_pid(win) -> int | None:
    """Return the _NET_WM_PID of an X window, or None."""
    try:
        prop = win.get_full_property(win.display.intern_atom("_NET_WM_PID"), 0)
        if prop and prop.value:
            return int(prop.value[0])
    except Exception:
        pass
    return None


def _find_window_by_pid(dpy, pid: int):
    """Depth-first search for an X window whose _NET_WM_PID matches."""
    root = dpy.screen().root

    def walk(win):
        try:
            children = win.query_tree().children
        except Exception:
            return None
        for child in children:
            found = walk(child)
            if found:
                return found
        if _window_pid(win) == pid:
            return win
        return None

    return walk(root)


def find_window_for_pid(pid: int) -> dict | None:
    """Return geometry and names of the X window belonging to a PID."""
    try:
        dpy = _connect()
        win = _find_window_by_pid(dpy, pid)
        if win is None:
            return None
        x, y, w, h = _window_geometry(win)
        wm_class = win.get_wm_class() or ()
        wm_name = win.get_wm_name() or ""
        dpy.close()
        return {
            "x": x, "y": y, "width": w, "height": h,
            "app_id": (wm_class[1] if len(wm_class) >= 2 else ""),
            "title": str(wm_name),
        }
    except Exception:
        return None


def capture_thumbnail_for_pid(pid: int, max_size: int = 320) -> tuple[bytes, int, int] | None:
    """Capture a thumbnail of the X11 window belonging to a PID."""
    try:
        dpy = _connect()
        win = _find_window_by_pid(dpy, pid)
        if win is None:
            return None
        data, w, h = _capture_window_pixmap(win)
        dpy.close()
        if data is None:
            return None
        if w <= 0 or h <= 0:
            return None
        if w > max_size or h > max_size:
            scale = min(max_size / w, max_size / h)
            new_w = max(1, int(w * scale))
            new_h = max(1, int(h * scale))
            data = _scale_rgba(data, w, h, new_w, new_h)
            w, h = new_w, new_h
        return data, w, h
    except Exception:
        return None
