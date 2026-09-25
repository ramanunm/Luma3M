from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from microscope_control.devices.base import Device, DeviceNotConnectedError


@dataclass(slots=True)
class ArduinoUnoConfig:
    """Serial settings for the Arduino Uno light-path controller."""

    port: str = "COM3"
    baud_rate: int = 9600
    timeout_seconds: float = 2.0
    startup_wait_seconds: float = 2.0
    turn_off_on_disconnect: bool = True


class ArduinoDependencyError(RuntimeError):
    """Raised when pyserial is not available."""


class ArduinoUnoLightController(Device):
    """Control the LED/Laser light paths through an Arduino Uno.

    Expected Arduino serial commands:
    PING  -> OK
    LED   -> OK LED
    LASER -> OK LASER
    OFF   -> OK OFF
    """

    def __init__(self, config: ArduinoUnoConfig | None = None):
        self.config = config or ArduinoUnoConfig()
        self._serial: Any | None = None

    def connect(self) -> "ArduinoUnoLightController":
        if self._serial is not None:
            return self

        try:
            import serial
        except ImportError as exc:
            raise ArduinoDependencyError("pyserial is not installed. Run: python -m pip install pyserial") from exc

        self._serial = serial.Serial(
            self.config.port,
            self.config.baud_rate,
            timeout=self.config.timeout_seconds,
            write_timeout=self.config.timeout_seconds,
        )

        # Opening the serial port often resets an Arduino Uno.
        time.sleep(self.config.startup_wait_seconds)
        self._reset_input_buffer()
        self.ping()
        return self

    def disconnect(self) -> None:
        if self._serial is None:
            return

        try:
            if self.config.turn_off_on_disconnect:
                self.off()
        finally:
            self._serial.close()
            self._serial = None

    def __enter__(self) -> "ArduinoUnoLightController":
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()

    @property
    def serial_connection(self):
        if self._serial is None:
            raise DeviceNotConnectedError("Arduino Uno is not connected.")
        return self._serial

    def ping(self) -> str:
        return self.send_command("PING")

    def select_led(self) -> str:
        return self.send_command("LED")

    def select_laser(self) -> str:
        return self.send_command("LASER")

    def off(self) -> str:
        return self.send_command("OFF")

    def send_command(self, command: str) -> str:
        serial_connection = self.serial_connection
        command_text = command.strip().upper()
        if not command_text:
            raise ValueError("Arduino command cannot be empty.")

        self._reset_input_buffer()
        serial_connection.write(f"{command_text}\n".encode("ascii"))
        serial_connection.flush()

        response = serial_connection.readline().decode("ascii", errors="replace").strip()
        if not response:
            raise TimeoutError(f"Arduino did not respond to command {command_text!r}.")
        if not response.startswith("OK"):
            raise RuntimeError(f"Arduino rejected command {command_text!r}: {response}")

        return response

    def _reset_input_buffer(self) -> None:
        serial_connection = self.serial_connection
        if hasattr(serial_connection, "reset_input_buffer"):
            serial_connection.reset_input_buffer()
