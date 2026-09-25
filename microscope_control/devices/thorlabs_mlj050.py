from __future__ import annotations

import os
import sys
import time
from ctypes import c_char_p, c_int, create_string_buffer
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from microscope_control.devices.base import Device, DeviceNotConnectedError


@dataclass(slots=True)
class LabJackConfig:
    """Settings for the Thorlabs MLJ050 LabJack.

    Keeping this config beside the device makes the MLJ050 module easier to
    copy to another computer without depending on config.py being updated first.
    """

    serial_number: str = "49871116"
    kinesis_dir: Path | None = None
    polling_interval_ms: int = 250
    connect_wait_seconds: float = 0.25
    home_timeout_ms: int = 120_000
    move_timeout_ms: int = 120_000


class KinesisDependencyError(RuntimeError):
    """Raised when pythonnet or Thorlabs Kinesis DLLs are not available."""


def _net_decimal_to_float(value) -> float:
    """Convert a .NET Decimal value to a Python float."""

    return float(str(value))


def _candidate_kinesis_dirs(configured_dir: Path | None) -> list[Path]:
    candidates: list[Path] = []
    if configured_dir is not None:
        candidates.append(configured_dir)
    candidates.append(Path(r"C:\Program Files\Thorlabs\Kinesis"))
    candidates.append(Path(r"C:\Program Files (x86)\Thorlabs\Kinesis"))
    return candidates


def find_kinesis_dir(configured_dir: Path | None = None) -> Path:
    for folder in _candidate_kinesis_dirs(configured_dir):
        if (folder / "Thorlabs.MotionControl.DeviceManagerCLI.dll").exists():
            return folder

    searched = "\n".join(str(path) for path in _candidate_kinesis_dirs(configured_dir))
    raise KinesisDependencyError(f"Could not find Thorlabs Kinesis DLLs. Searched:\n{searched}")


def _find_dll(kinesis_dir: Path, expected_name: str) -> Path:
    expected_lower = expected_name.lower()
    for path in kinesis_dir.glob("*.dll"):
        if path.name.lower() == expected_lower:
            return path
    raise KinesisDependencyError(f"Could not find {expected_name} in {kinesis_dir}")


def load_kinesis_assemblies(kinesis_dir: Path) -> Path:
    try:
        import clr
    except ImportError as exc:
        raise KinesisDependencyError("pythonnet is not installed. Run: python -m pip install pythonnet") from exc

    kinesis_text = str(kinesis_dir)
    if kinesis_text not in sys.path:
        sys.path.append(kinesis_text)
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(kinesis_text)

    device_manager = _find_dll(kinesis_dir, "Thorlabs.MotionControl.DeviceManagerCLI.dll")
    generic_motor = _find_dll(kinesis_dir, "Thorlabs.MotionControl.GenericMotorCLI.dll")
    integrated_stepper = _find_dll(kinesis_dir, "Thorlabs.MotionControl.IntegratedStepperMotorsCLI.dll")

    clr.AddReference(str(device_manager))
    clr.AddReference(str(generic_motor))
    clr.AddReference(str(integrated_stepper))
    return integrated_stepper


def list_integrated_stepper_types(configured_dir: Path | None = None) -> list[str]:
    kinesis_dir = find_kinesis_dir(configured_dir)
    integrated_stepper = load_kinesis_assemblies(kinesis_dir)

    from System.Reflection import Assembly

    assembly = Assembly.LoadFrom(str(integrated_stepper))
    return sorted(type_obj.FullName for type_obj in assembly.GetTypes())


def list_integrated_stepper_factories(configured_dir: Path | None = None) -> list[str]:
    """List public static Create... methods in the IntegratedStepperMotors assembly."""

    kinesis_dir = find_kinesis_dir(configured_dir)
    integrated_stepper = load_kinesis_assemblies(kinesis_dir)

    from System.Reflection import Assembly, BindingFlags

    assembly = Assembly.LoadFrom(str(integrated_stepper))
    flags = BindingFlags.Public | BindingFlags.Static
    factories: list[str] = []

    for type_obj in assembly.GetTypes():
        for method in type_obj.GetMethods(flags):
            if method.Name.startswith("Create"):
                factories.append(f"{type_obj.FullName}.{method.Name}")

    return sorted(factories)


def list_connected_kinesis_serials(configured_dir: Path | None = None) -> tuple[int, list[str]]:
    """Return the serial numbers that Kinesis can currently see."""

    kinesis_dir = find_kinesis_dir(configured_dir)
    load_kinesis_assemblies(kinesis_dir)

    from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI

    DeviceManagerCLI.BuildDeviceList()
    size = int(DeviceManagerCLI.GetDeviceListSize())
    devices = DeviceManagerCLI.GetDeviceList()
    serials = [str(item) for item in devices]
    return size, serials


def list_connected_kinesis_serials_native(configured_dir: Path | None = None) -> tuple[int, list[str], list[str]]:
    """Use the lower-level DeviceManager.dll API to list connected serials.

    This is useful when DeviceManagerCLI returns an empty list. The MLJ050 device
    type ID is 49, so this function also asks specifically for LabJack 050 devices.
    """

    import ctypes

    kinesis_dir = find_kinesis_dir(configured_dir)
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(kinesis_dir))

    device_manager = _find_dll(kinesis_dir, "Thorlabs.MotionControl.DeviceManager.dll")
    lib = ctypes.WinDLL(str(device_manager))

    lib.TLI_BuildDeviceList.restype = c_int
    build_result = lib.TLI_BuildDeviceList()
    if build_result != 0:
        raise KinesisDependencyError(f"TLI_BuildDeviceList failed with code {build_result}")

    lib.TLI_GetDeviceListSize.restype = c_int
    size = int(lib.TLI_GetDeviceListSize())

    buffer_size = 500
    all_buffer = create_string_buffer(buffer_size)
    labjack_buffer = create_string_buffer(buffer_size)

    lib.TLI_GetDeviceListExt.argtypes = [c_char_p, c_int]
    lib.TLI_GetDeviceListExt.restype = c_int
    all_result = lib.TLI_GetDeviceListExt(all_buffer, buffer_size)
    if all_result != 0:
        raise KinesisDependencyError(f"TLI_GetDeviceListExt failed with code {all_result}")

    labjack_050_id = 49
    device_ids = (c_int * 1)(labjack_050_id)
    lib.TLI_GetDeviceListByTypesExt.argtypes = [c_char_p, c_int, ctypes.POINTER(c_int), c_int]
    lib.TLI_GetDeviceListByTypesExt.restype = c_int
    labjack_result = lib.TLI_GetDeviceListByTypesExt(labjack_buffer, buffer_size, device_ids, 1)
    if labjack_result != 0:
        raise KinesisDependencyError(f"TLI_GetDeviceListByTypesExt failed with code {labjack_result}")

    all_serials = [item for item in all_buffer.value.decode().split(",") if item]
    labjack_serials = [item for item in labjack_buffer.value.decode().split(",") if item]
    return size, all_serials, labjack_serials


class ThorlabsMLJ050(Device):
    """Thorlabs MLJ050 Motorized Lab Jack.

    Beginner-friendly methods:
    connect, disconnect, home, get_position_mm, move_to_mm, move_relative_mm.
    """

    def __init__(self, config: LabJackConfig | None = None):
        self.config = config or LabJackConfig()
        self._device: Any | None = None
        self._connected = False
        self._kinesis_dir: Path | None = None

    def connect(self) -> "ThorlabsMLJ050":
        if self._connected:
            return self

        self._kinesis_dir = find_kinesis_dir(self.config.kinesis_dir)
        load_kinesis_assemblies(self._kinesis_dir)

        from Thorlabs.MotionControl.DeviceManagerCLI import DeviceManagerCLI

        DeviceManagerCLI.BuildDeviceList()
        _, serials = list_connected_kinesis_serials(self._kinesis_dir)
        if self.config.serial_number not in serials:
            raise RuntimeError(
                f"Kinesis does not currently list serial {self.config.serial_number}. "
                f"Detected serials: {serials}. Close Kinesis, check USB/power, and confirm the serial number."
            )

        device = self._create_device(self.config.serial_number)
        try:
            device.Connect(self.config.serial_number)
        except Exception as exc:
            raise RuntimeError(
                "Kinesis saw the serial number, but the Python wrapper could not connect to it. "
                "This usually means the selected .NET device class is wrong for this MLJ050, "
                "or another program is occupying the device. Run scripts\\05_mlj050_diagnostics.py "
                "and send me the output."
            ) from exc

        if not device.IsSettingsInitialized():
            device.WaitForSettingsInitialized(10_000)
            if not device.IsSettingsInitialized():
                raise RuntimeError("Kinesis device settings were not initialized within 10 seconds.")

        device.StartPolling(self.config.polling_interval_ms)
        time.sleep(self.config.connect_wait_seconds)
        device.EnableDevice()
        time.sleep(self.config.connect_wait_seconds)

        if hasattr(device, "LoadMotorConfiguration"):
            device.LoadMotorConfiguration(self.config.serial_number)

        self._device = device
        self._connected = True
        return self

    def disconnect(self) -> None:
        if self._device is not None:
            try:
                self._device.StopPolling()
            finally:
                self._device.Disconnect()

        self._device = None
        self._connected = False

    def __enter__(self) -> "ThorlabsMLJ050":
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()

    @property
    def device(self):
        if self._device is None:
            raise DeviceNotConnectedError("MLJ050 is not connected.")
        return self._device

    def get_device_description(self) -> str:
        info = self.device.GetDeviceInfo()
        return str(info.Description)

    def identify(self) -> None:
        self.device.IdentifyDevice()

    def home(self) -> None:
        self.device.Home(self.config.home_timeout_ms)

    def get_position_mm(self) -> float:
        return _net_decimal_to_float(self.device.Position)

    def move_to_mm(self, position_mm: float) -> float:
        from System import Decimal

        self.device.MoveTo(Decimal(float(position_mm)), self.config.move_timeout_ms)
        return self.get_position_mm()

    def move_relative_mm(self, distance_mm: float) -> float:
        current = self.get_position_mm()
        return self.move_to_mm(current + float(distance_mm))

    def move_relative_steps(self, steps: int) -> int:
        # For compatibility with the existing demo workflow:
        # one workflow "step" is treated as 0.001 mm.
        self.move_relative_mm(int(steps) * 0.001)
        return int(round(self.get_position_mm() * 1000))

    def stop(self) -> None:
        if hasattr(self.device, "Stop"):
            self.device.Stop(self.config.move_timeout_ms)

    def _create_device(self, serial_number: str):
        try:
            from Thorlabs.MotionControl.IntegratedStepperMotorsCLI import LabJack

            return LabJack.CreateLabJack(serial_number)
        except Exception:
            return self._create_device_by_reflection(serial_number)

    def _create_device_by_reflection(self, serial_number: str):
        from System.Reflection import Assembly, BindingFlags

        if self._kinesis_dir is None:
            raise RuntimeError("Kinesis directory has not been loaded.")

        integrated_stepper = _find_dll(self._kinesis_dir, "Thorlabs.MotionControl.IntegratedStepperMotorsCLI.dll")
        assembly = Assembly.LoadFrom(str(integrated_stepper))
        flags = BindingFlags.Public | BindingFlags.Static
        errors: list[str] = []

        for type_obj in assembly.GetTypes():
            type_name = str(type_obj.FullName)
            # Be strict here. MLJ050 is a LabJack; using a generic Stage factory
            # can create the wrong object and lead to DeviceNotReadyException.
            if not any(keyword in type_name.lower() for keyword in ["lab", "jack", "mlj"]):
                continue

            for method in type_obj.GetMethods(flags):
                if not method.Name.startswith("Create"):
                    continue
                try:
                    return method.Invoke(None, [serial_number])
                except Exception as exc:
                    errors.append(f"{type_name}.{method.Name}: {exc}")

        details = "\n".join(errors[:10])
        raise RuntimeError(
            "Could not create an MLJ050 Kinesis device object. "
            "Run scripts\\05_mlj050_diagnostics.py and send me the output.\n"
            f"Factory attempts:\n{details}"
        )
