from __future__ import annotations

from pathlib import Path
from typing import Any

from microscope_control.config import CameraAutoSetting, CameraConfig
from microscope_control.devices.zwo_camera import ZwoCamera


class MicroscopeSystem:
    """Central object that connects the devices in the microscope platform.

    Keep hardware-specific code inside devices/.
    Keep experiment order and automation inside workflows/.
    This class only ties the devices together.
    """

    def __init__(
        self,
        camera_config: CameraConfig | None = None,
        stage: Any | None = None,
        light: Any | None = None,
        spectrometer: Any | None = None,
    ):
        self.camera = ZwoCamera(camera_config)
        self.stage = stage
        self.light = light
        self.spectrometer = spectrometer

    def connect(self) -> "MicroscopeSystem":
        try:
            self.camera.connect()
            if self.stage is not None:
                self.stage.connect()
            if self.light is not None:
                self.light.connect()
            if self.spectrometer is not None:
                self.spectrometer.connect()
            return self
        except Exception:
            self.disconnect()
            raise

    def disconnect(self) -> None:
        try:
            if self.spectrometer is not None:
                self.spectrometer.disconnect()
        finally:
            try:
                if self.light is not None:
                    self.light.disconnect()
            finally:
                try:
                    if self.stage is not None:
                        self.stage.disconnect()
                finally:
                    self.camera.disconnect()

    def __enter__(self) -> "MicroscopeSystem":
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()

    def capture_image(
        self,
        output_path: str | Path,
        exposure_us: CameraAutoSetting | None = None,
        gain: CameraAutoSetting | None = None,
        image_type: str | int | None = None,
        white_balance_r: int | None = None,
        white_balance_b: int | None = None,
    ):
        return self.camera.capture_to_file(
            output_path,
            exposure_us=exposure_us,
            gain=gain,
            image_type=image_type,
            white_balance_r=white_balance_r,
            white_balance_b=white_balance_b,
        )

    def capture_spectrum(
        self,
        exposure_us: int = 10_000,
        averages: int = 1,
        blank_scans: int = 0,
    ):
        if self.spectrometer is None:
            raise RuntimeError("This MicroscopeSystem has no spectrometer.")
        return self.spectrometer.capture_spectrum(
            exposure_us=exposure_us,
            averages=averages,
            blank_scans=blank_scans,
        )

    @classmethod
    def with_mlj050_labjack(
        cls,
        camera_config: CameraConfig | None = None,
        labjack_config: Any | None = None,
    ) -> "MicroscopeSystem":
        from microscope_control.devices.thorlabs_mlj050 import ThorlabsMLJ050

        return cls(camera_config=camera_config, stage=ThorlabsMLJ050(labjack_config))

    @classmethod
    def with_arduino_light(
        cls,
        camera_config: CameraConfig | None = None,
        arduino_config: Any | None = None,
    ) -> "MicroscopeSystem":
        from microscope_control.devices.arduino_uno import ArduinoUnoLightController

        return cls(camera_config=camera_config, light=ArduinoUnoLightController(arduino_config))

    @classmethod
    def with_mlj050_labjack_and_arduino_light(
        cls,
        camera_config: CameraConfig | None = None,
        labjack_config: Any | None = None,
        arduino_config: Any | None = None,
    ) -> "MicroscopeSystem":
        from microscope_control.devices.arduino_uno import ArduinoUnoLightController
        from microscope_control.devices.thorlabs_mlj050 import ThorlabsMLJ050

        return cls(
            camera_config=camera_config,
            stage=ThorlabsMLJ050(labjack_config),
            light=ArduinoUnoLightController(arduino_config),
        )

    @classmethod
    def with_mlj050_labjack_arduino_light_and_aseq_spectrometer(
        cls,
        camera_config: CameraConfig | None = None,
        labjack_config: Any | None = None,
        arduino_config: Any | None = None,
        spectrometer_config: Any | None = None,
    ) -> "MicroscopeSystem":
        from microscope_control.devices.arduino_uno import ArduinoUnoLightController
        from microscope_control.devices.aseq_spectrometer import AseqSpectrometer
        from microscope_control.devices.thorlabs_mlj050 import ThorlabsMLJ050

        return cls(
            camera_config=camera_config,
            stage=ThorlabsMLJ050(labjack_config),
            light=ArduinoUnoLightController(arduino_config),
            spectrometer=AseqSpectrometer(spectrometer_config),
        )

