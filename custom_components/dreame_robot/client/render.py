"""Render a parsed vector map to PNG with Pillow."""

from __future__ import annotations

import io
import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from PIL import Image, ImageDraw, ImageFont

from .models import MapScene, RuntimeTelemetry, VectorMap

CANVAS_MAX: Final[int] = 1600
PADDING: Final[int] = 36
MIN_EDGE: Final[int] = 320

BACKGROUND: Final[tuple[int, int, int, int]] = (28, 34, 30, 0)
LAWN_FILL: Final[tuple[int, int, int, int]] = (58, 122, 74, 255)
LAWN_EDGE: Final[tuple[int, int, int, int]] = (140, 214, 158, 255)
FORBIDDEN_FILL: Final[tuple[int, int, int, int]] = (168, 52, 52, 110)
FORBIDDEN_EDGE: Final[tuple[int, int, int, int]] = (226, 106, 106, 220)
SPOT_FILL: Final[tuple[int, int, int, int]] = (86, 132, 214, 90)
SPOT_EDGE: Final[tuple[int, int, int, int]] = (140, 180, 246, 200)
PATH_COLOR: Final[tuple[int, int, int, int]] = (232, 206, 120, 170)
CONTOUR_COLOR: Final[tuple[int, int, int, int]] = (236, 168, 84, 220)
TRAIL_COLOR: Final[tuple[int, int, int, int]] = (250, 240, 150, 190)
ROBOT_COLOR: Final[tuple[int, int, int, int]] = (250, 250, 250, 255)
ROBOT_RING: Final[tuple[int, int, int, int]] = (30, 36, 32, 255)
LABEL_COLOR: Final[tuple[int, int, int, int]] = (245, 250, 246, 255)


@dataclass(frozen=True, slots=True)
class Projection:
    """Maps native centimetres onto canvas pixels.

    The vendor's own canvas mirrors X so that the map reads north-up, so the
    same mirror is used here.
    """

    max_x: float
    min_y: float
    scale: float
    native_width: int
    native_height: int
    rotation: int = 0

    @property
    def width(self) -> int:
        """Return the canvas width after display rotation."""
        return self.native_height if self.rotation in (90, 270) else self.native_width

    @property
    def height(self) -> int:
        """Return the canvas height after display rotation."""
        return self.native_width if self.rotation in (90, 270) else self.native_height

    def point(self, x: float, y: float) -> tuple[int, int]:
        """Project one native point to a canvas pixel."""
        px = (self.max_x - x) * self.scale + PADDING
        py = (y - self.min_y) * self.scale + PADDING
        if self.rotation == 90:
            px, py = self.native_height - 1 - py, px
        elif self.rotation == 180:
            px, py = self.native_width - 1 - px, self.native_height - 1 - py
        elif self.rotation == 270:
            px, py = py, self.native_width - 1 - px
        return round(px), round(py)

    def polygon(self, points: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
        """Project a whole polyline."""
        return [self.point(x, y) for x, y in points]

    def inverse(self, px: float, py: float) -> tuple[float, float]:
        """Map a canvas pixel back to native centimetres.

        The map card needs this so a tap on the rendered map can be turned into
        a native map coordinate to send to the mower.
        """
        if self.rotation == 90:
            px, py = py, self.native_height - 1 - px
        elif self.rotation == 180:
            px, py = self.native_width - 1 - px, self.native_height - 1 - py
        elif self.rotation == 270:
            px, py = self.native_width - 1 - py, px
        return (
            self.max_x - (px - PADDING) / self.scale,
            self.min_y + (py - PADDING) / self.scale,
        )

    def as_dict(self) -> dict[str, float | int]:
        """Return the parameters a client needs to invert the projection."""
        return {
            "max_x": self.max_x,
            "min_y": self.min_y,
            "scale": self.scale,
            "padding": PADDING,
            "native_width": self.native_width,
            "native_height": self.native_height,
            "rotation": self.rotation,
        }


def build_projection(vector_map: VectorMap, rotation: int = 0) -> Projection:
    """Return the projection that fits ``vector_map`` on the canvas."""
    x1, y1, x2, y2 = vector_map.boundary
    width = max(x2 - x1, 1)
    height = max(y2 - y1, 1)
    scale = min(
        (CANVAS_MAX - 2 * PADDING) / width,
        (CANVAS_MAX - 2 * PADDING) / height,
    )
    scale = max(scale, MIN_EDGE / max(width, height))
    return Projection(
        max_x=x2,
        min_y=y1,
        scale=scale,
        native_width=round(width * scale) + 2 * PADDING,
        native_height=round(height * scale) + 2 * PADDING,
        rotation=rotation,
    )


_FONT_CANDIDATES: Final[tuple[str, ...]] = (
    "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def _label_font(size: int) -> ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_label(
    draw: ImageDraw.ImageDraw,
    position: tuple[int, int],
    text: str,
    font: ImageFont.ImageFont,
    anchor: str = "mm",
) -> None:
    if not text:
        return
    x, y = position
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        draw.text((x + dx, y + dy), text, font=font, fill=LAWN_EDGE, anchor=anchor)
    draw.text((x, y), text, font=font, fill=LABEL_COLOR, anchor=anchor)


def render_scene(scene: MapScene) -> bytes | None:
    """Render ``scene`` to PNG bytes, or ``None`` when there is nothing to draw."""
    vector_map = scene.vector_map
    if not vector_map.usable:
        return None

    projection = build_projection(vector_map, scene.rotation)
    ratio = max(projection.width, projection.height) / 900
    stroke = max(2, round(2 * ratio))
    label_size = max(11, round(15 * ratio))
    font = _label_font(label_size)

    image = Image.new("RGBA", (projection.width, projection.height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    for path in vector_map.paths:
        _stroke(draw, projection, path.points, PATH_COLOR, stroke)

    for poly in vector_map.spots:
        _fill_polygon(draw, projection, poly.points, SPOT_FILL, SPOT_EDGE, stroke)

    for poly in vector_map.zones:
        _fill_polygon(draw, projection, poly.points, LAWN_FILL, LAWN_EDGE, stroke)

    # No-go areas sit inside a mowing zone, so they must be drawn over it.
    for poly in vector_map.forbidden:
        _fill_polygon(draw, projection, poly.points, FORBIDDEN_FILL, FORBIDDEN_EDGE, stroke)

    for poly in vector_map.contours:
        _stroke(draw, projection, poly.points, CONTOUR_COLOR, stroke)

    for poly in (*vector_map.zones, *vector_map.forbidden, *vector_map.spots):
        cx, cy = projection.point(*poly.center)
        _draw_label(draw, (cx, cy), poly.name or str(poly.id), font)

    for point in vector_map.points:
        cx, cy = projection.point(*point)
        draw.ellipse(
            (cx - stroke * 2, cy - stroke * 2, cx + stroke * 2, cy + stroke * 2),
            fill=(220, 220, 220, 160),
        )

    for segment in scene.trail:
        _stroke(draw, projection, segment, TRAIL_COLOR, stroke)

    if scene.runtime:
        _draw_robot(draw, projection, scene.runtime, ratio)

    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def _stroke(
    draw: ImageDraw.ImageDraw,
    projection: Projection,
    points: Sequence[tuple[int, int]],
    color: tuple[int, int, int, int],
    stroke: int,
) -> None:
    if len(points) > 1:
        draw.line(projection.polygon(points), fill=color, width=stroke, joint="curve")


def _fill_polygon(
    draw: ImageDraw.ImageDraw,
    projection: Projection,
    points: Sequence[tuple[int, int]],
    fill: tuple[int, int, int, int],
    edge: tuple[int, int, int, int],
    stroke: int,
) -> None:
    if len(points) < 2:
        return
    if len(points) == 2:
        _stroke(draw, projection, points, edge, stroke)
        return
    draw.polygon(projection.polygon(points), fill=fill, outline=edge, width=stroke)


def _draw_robot(
    draw: ImageDraw.ImageDraw,
    projection: Projection,
    runtime: RuntimeTelemetry,
    ratio: float,
) -> None:
    px, py = projection.point(runtime.x, runtime.y)
    radius = max(8, round(11 * ratio))
    # The X mirror reverses yaw, so a clockwise-from-north heading on the map
    # becomes clockwise-from-up on screen after this flip.
    angle = (270 - runtime.heading + projection.rotation) % 360
    tip = (
        px + radius * math.sin(math.radians(angle)),
        py - radius * math.cos(math.radians(angle)),
    )
    left = (
        px + radius * math.sin(math.radians(angle + 140)),
        py - radius * math.cos(math.radians(angle + 140)),
    )
    right = (
        px + radius * math.sin(math.radians(angle - 140)),
        py - radius * math.cos(math.radians(angle - 140)),
    )
    draw.polygon([tip, left, right], fill=ROBOT_COLOR, outline=ROBOT_RING)
