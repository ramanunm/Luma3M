from __future__ import annotations

import platform
import struct
import sys
from pathlib import Path

from microscope_control.devices.zwo_camera import ZwoCamera
from microscope_control.settings import WorkComputerSettings


def work_computer_report(settings: WorkComputerSettings) -> list[tuple[str, bool, str]]:
    """Run non-actuating environment checks suitable for the work computer."""

    checks: list[tuple[str, bool, str]] = []
    version_ok = sys.version_info[:2] == (3, 11)
    checks.append(("Python 3.11", version_ok, platform.python_version()))
    bits = struct.calcsize("P") * 8
    checks.append(("64-bit Python", bits == 64, f"{bits}-bit"))
    checks.append(("Kinesis directory", settings.kinesis_dir.exists(), str(settings.kinesis_dir)))
    checks.append(("ASEQ DLL", settings.aseq_dll.exists(), str(settings.aseq_dll)))
    checks.append(("ASEQ wavelength calibration", settings.aseq_calibration.exists(), str(settings.aseq_calibration)))
    checks.append(("Output drive", settings.output_root.anchor != "" and Path(settings.output_root.anchor).exists(), str(settings.output_root)))

    try:
        import serial.tools.list_ports

        ports = [port.device for port in serial.tools.list_ports.comports()]
        checks.append(("Arduino serial port", settings.arduino_port in ports, f"configured={settings.arduino_port}; detected={ports}"))
    except ImportError:
        checks.append(("pyserial", False, "not installed"))

    try:
        cameras = ZwoCamera.available_cameras()
        checks.append(("ZWO camera", len(cameras) > settings.camera_index, str(cameras)))
    except Exception as exc:
        checks.append(("ZWO camera", False, str(exc)))

    return checks

