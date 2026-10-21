"""
Make ``app.icns``, the macOS icon, from ``app.svg``.

    python packaging/make_icns.py

The result is committed, so a build never needs this; run it again only when
the SVG changes. Qt draws the SVG, Pillow writes the .icns, so it runs on any
OS — no ``iconutil`` needed.

macOS icons are not full-bleed. Since Big Sur every app icon is a rounded
square of 824 px on a 1024 px canvas, and an icon that fills the canvas
looks a size too big in the Dock beside everything else. So the plate is
drawn at that size in that shape, with the margin left clear, and the SVG
goes inside it far enough in that the corners do not cut its yellow frame.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QColor,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
)
from PySide6.QtSvg import QSvgRenderer  # noqa: E402

ICONS = Path(__file__).resolve().parent.parent / "src" / "evans" / "ui" / "icons"
CANVAS = 1024
PLATE = 824
RADIUS = 185
#: Clear of a corner's curve, which reaches RADIUS·(1 − 1/√2) ≈ 54 px in.
INSET = 64
#: The SVG's own ground, so plate and drawing are one surface.
GROUND = "#121314"


def render() -> Image.Image:
    image = QImage(CANVAS, CANVAS, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.Antialiasing)
    margin = (CANVAS - PLATE) / 2
    plate = QRectF(margin, margin, PLATE, PLATE)
    shape = QPainterPath()
    shape.addRoundedRect(plate, RADIUS, RADIUS)
    p.fillPath(shape, QColor(GROUND))
    QSvgRenderer(str(ICONS / "app.svg")).render(
        p, plate.adjusted(INSET, INSET, -INSET, -INSET))
    p.end()

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    from io import BytesIO
    return Image.open(BytesIO(bytes(data)))


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 (QPainter needs one)
    target = ICONS / "app.icns"
    # Pillow writes every standard size, 16 to 1024 with the @2x variants,
    # scaled down from this one image.
    render().save(target, format="ICNS")
    print(f"wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
