from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "work_computer.toml"


@dataclass(frozen=True, slots=True)
class WorkComputerSettings:
    config_path: Path
    output_root: Path
    kinesis_dir: Path
    aseq_dll: Path
    aseq_calibration: Path
    camera_index: int
    stage_serial: str
    arduino_port: str
    arduino_baud_rate: int
    spectrum_device_index: int
    camera: dict[str, Any]
    led: dict[str, Any]
    laser: dict[str, Any]
    acquisition: dict[str, Any]


def load_work_computer_settings(config_path: str | Path | None = None) -> WorkComputerSettings:
    selected = Path(
        config_path
        or os.environ.get("MICROSCOPY_CONFIG", "")
        or DEFAULT_CONFIG_PATH
    ).expanduser().resolve()
    with selected.open("rb") as file:
        raw = tomllib.load(file)

    paths = raw.get("paths", {})
    devices = raw.get("devices", {})
    return WorkComputerSettings(
        config_path=selected,
        output_root=_resolve_project_path(paths.get("output_root", r"D:\captures\microscope")),
        kinesis_dir=_resolve_project_path(paths.get("kinesis_dir", r"C:\Program Files\Thorlabs\Kinesis")),
        aseq_dll=_resolve_project_path(paths.get("aseq_dll", r"drivers\aseq\spectrlib_shared_64bits.dll")),
        aseq_calibration=_resolve_project_path(paths.get("aseq_calibration", r"drivers\aseq\aseq_wavelengths_latest.txt")),
        camera_index=int(devices.get("camera_index", 0)),
        stage_serial=str(devices.get("stage_serial", "49871116")),
        arduino_port=str(devices.get("arduino_port", "COM3")),
        arduino_baud_rate=int(devices.get("arduino_baud_rate", 9600)),
        spectrum_device_index=int(devices.get("spectrum_device_index", 0)),
        camera=dict(raw.get("camera", {})),
        led=dict(raw.get("led", {})),
        laser=dict(raw.get("laser", {})),
        acquisition=dict(raw.get("acquisition", {})),
    )


def _resolve_project_path(value: str | Path) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else (PROJECT_ROOT / path).resolve()


SETTINGS = load_work_computer_settings()

