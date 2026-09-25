from __future__ import annotations

import time
from pathlib import Path

from microscope_control.devices.zwo_camera import save_frame
from microscope_control.reference_axes import add_reference_axes


def capture_light_image(
    system,
    output: str | Path,
    *,
    light: str,
    settle_seconds: float = 1.0,
    reference_axes: bool = False,
    axis_step: float = 0.1,
    axis_border_px: int = 70,
) -> Path:
    """Illuminate, capture once, and always switch the light off."""

    if system.light is None:
        raise RuntimeError("Image workflow requires a light controller.")
    if light == "led":
        system.light.select_led()
    elif light == "laser":
        system.light.select_laser()
    else:
        raise ValueError("light must be 'led' or 'laser'.")

    try:
        time.sleep(settle_seconds)
        if not reference_axes:
            return system.capture_image(output)
        frame = system.camera.capture()
        annotated = add_reference_axes(frame, tick_step=axis_step, border_px=axis_border_px)
        return save_frame(annotated, output)
    finally:
        system.light.off()

