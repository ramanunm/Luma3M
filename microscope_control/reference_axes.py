from __future__ import annotations

import numpy as np


_FONT_5X7 = {
    "0": ("01110", "10001", "10011", "10101", "11001", "10001", "01110"),
    "1": ("00100", "01100", "00100", "00100", "00100", "00100", "01110"),
    "2": ("01110", "10001", "00001", "00010", "00100", "01000", "11111"),
    "3": ("11110", "00001", "00001", "01110", "00001", "00001", "11110"),
    "4": ("00010", "00110", "01010", "10010", "11111", "00010", "00010"),
    "5": ("11111", "10000", "11110", "00001", "00001", "10001", "01110"),
    "6": ("00110", "01000", "10000", "11110", "10001", "10001", "01110"),
    "7": ("11111", "00001", "00010", "00100", "01000", "01000", "01000"),
    "8": ("01110", "10001", "10001", "01110", "10001", "10001", "01110"),
    "9": ("01110", "10001", "10001", "01111", "00001", "00010", "01100"),
    ".": ("00000", "00000", "00000", "00000", "00000", "01100", "01100"),
    " ": ("00000", "00000", "00000", "00000", "00000", "00000", "00000"),
}


def add_reference_axes(
    frame,
    *,
    tick_step: float = 0.1,
    border_px: int = 70,
    text_scale: int = 2,
):
    """Return a copy of frame with reference axes around the image.

    Axis values are normalized image coordinates from 0 to 1. The origin is the
    top-left corner, which matches the autofocus --focus-roi convention.
    """

    _validate_axis_options(tick_step, border_px, text_scale)

    image = np.asarray(frame)
    if image.ndim not in {2, 3}:
        raise ValueError(f"Reference axes need a 2D or 3D image, got shape {image.shape}.")
    if image.ndim == 3 and image.shape[2] < 3:
        raise ValueError(f"Reference axes need RGB-like images with at least 3 channels, got shape {image.shape}.")

    height, width = image.shape[:2]
    if height < 3 or width < 3:
        raise ValueError("Image is too small for reference axes.")

    background, foreground = _axis_colors(image)
    canvas = _new_canvas(image, border_px, background)
    canvas[border_px : border_px + height, border_px : border_px + width, ...] = image

    left = border_px
    top = border_px
    right = border_px + width - 1
    bottom = border_px + height - 1

    _draw_rect(canvas, left - 1, top - 1, right + 1, bottom + 1, foreground)

    tick_length = max(8, border_px // 5)
    label_gap = max(4, border_px // 12)

    for value in _tick_values(tick_step):
        x = left + int(round(value * (width - 1)))
        y = top + int(round(value * (height - 1)))
        label = _format_fraction_label(value)

        _draw_line(canvas, x, top - tick_length, x, top - 1, foreground)
        _draw_line(canvas, x, bottom + 1, x, bottom + tick_length, foreground)
        text_width = _text_width(label, text_scale)
        _draw_text(canvas, label, x - text_width // 2, label_gap, foreground, text_scale)
        _draw_text(canvas, label, x - text_width // 2, bottom + tick_length + label_gap, foreground, text_scale)

        _draw_line(canvas, left - tick_length, y, left - 1, y, foreground)
        _draw_line(canvas, right + 1, y, right + tick_length, y, foreground)
        text_height = _text_height(text_scale)
        _draw_text(canvas, label, label_gap, y - text_height // 2, foreground, text_scale)
        _draw_text(canvas, label, right + tick_length + label_gap, y - text_height // 2, foreground, text_scale)

    return canvas


def _validate_axis_options(tick_step: float, border_px: int, text_scale: int) -> None:
    if tick_step <= 0 or tick_step > 1:
        raise ValueError("reference axis step must be > 0 and <= 1.")
    if border_px < 35:
        raise ValueError("reference axis border must be at least 35 px.")
    if text_scale < 1:
        raise ValueError("reference axis text scale must be at least 1.")


def _axis_colors(image: np.ndarray):
    if np.issubdtype(image.dtype, np.integer):
        maximum = np.iinfo(image.dtype).max
    else:
        maximum = 1.0

    if image.ndim == 3:
        background = tuple([maximum] * image.shape[2])
        foreground = tuple([0] * image.shape[2])
    else:
        background = maximum
        foreground = 0

    return background, foreground


def _new_canvas(image: np.ndarray, border_px: int, background):
    height, width = image.shape[:2]
    shape = (height + 2 * border_px, width + 2 * border_px, *image.shape[2:])
    canvas = np.empty(shape, dtype=image.dtype)
    canvas[...] = background
    return canvas


def _tick_values(tick_step: float) -> list[float]:
    values: list[float] = []
    value = 0.0
    while value < 1.0:
        values.append(round(value, 10))
        value += tick_step

    if not values or values[-1] != 1.0:
        values.append(1.0)
    return values


def _format_fraction_label(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _draw_rect(canvas: np.ndarray, x0: int, y0: int, x1: int, y1: int, color) -> None:
    _draw_line(canvas, x0, y0, x1, y0, color)
    _draw_line(canvas, x0, y1, x1, y1, color)
    _draw_line(canvas, x0, y0, x0, y1, color)
    _draw_line(canvas, x1, y0, x1, y1, color)


def _draw_line(canvas: np.ndarray, x0: int, y0: int, x1: int, y1: int, color) -> None:
    if x0 == x1:
        y_start, y_stop = sorted((y0, y1))
        _fill_rect(canvas, x0, y_start, x0 + 1, y_stop + 1, color)
        return
    if y0 == y1:
        x_start, x_stop = sorted((x0, x1))
        _fill_rect(canvas, x_start, y0, x_stop + 1, y0 + 1, color)
        return
    raise ValueError("Only horizontal and vertical reference-axis lines are supported.")


def _draw_text(canvas: np.ndarray, text: str, x: int, y: int, color, scale: int) -> None:
    cursor_x = x
    for char in text:
        glyph = _FONT_5X7.get(char, _FONT_5X7[" "])
        for row_index, row in enumerate(glyph):
            for column_index, pixel in enumerate(row):
                if pixel == "1":
                    px = cursor_x + column_index * scale
                    py = y + row_index * scale
                    _fill_rect(canvas, px, py, px + scale, py + scale, color)
        cursor_x += (5 + 1) * scale


def _text_width(text: str, scale: int) -> int:
    if not text:
        return 0
    return len(text) * 5 * scale + max(0, len(text) - 1) * scale


def _text_height(scale: int) -> int:
    return 7 * scale


def _fill_rect(canvas: np.ndarray, x0: int, y0: int, x1: int, y1: int, color) -> None:
    height, width = canvas.shape[:2]
    x0 = max(0, min(width, x0))
    x1 = max(0, min(width, x1))
    y0 = max(0, min(height, y0))
    y1 = max(0, min(height, y1))
    if x0 >= x1 or y0 >= y1:
        return

    canvas[y0:y1, x0:x1, ...] = color
