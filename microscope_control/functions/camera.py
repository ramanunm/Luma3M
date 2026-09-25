from __future__ import annotations

from pathlib import Path
from typing import Any

from microscope_control.config import CameraConfig
from microscope_control.devices.zwo_camera import ZwoCamera


def camera_information(camera: ZwoCamera) -> dict[str, Any]:
    """Return the connected camera identity, ROI, limits and model-specific controls."""

    return {
        "name": camera.name,
        "camera_id": camera.camera_id,
        "roi": camera.roi,
        "exposure_limits_us": camera.exposure_limits,
        "gain_limits": camera.gain_limits,
        "temperature_c": camera.temperature_c,
        "controls": camera.list_controls(),
    }


def apply_camera_config(camera: ZwoCamera, config: CameraConfig) -> None:
    camera.apply_config(config)


def apply_named_controls(camera: ZwoCamera, controls: dict[str, tuple[int, bool]]) -> None:
    """Apply model-specific ZWO controls after validating them against the SDK."""

    for name, (value, auto) in controls.items():
        camera.set_control(name, value, auto=auto)


def capture(camera: ZwoCamera, output: str | Path) -> Path:
    return camera.capture_to_file(output)

