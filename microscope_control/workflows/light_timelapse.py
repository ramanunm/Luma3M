from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from microscope_control.config import CameraAutoSetting
from microscope_control.devices.aseq_spectrometer import save_spectrum_csv
from microscope_control.system import MicroscopeSystem
from microscope_control.workflows.autofocus import AutofocusConfig, run_laplacian_autofocus


@dataclass(slots=True)
class LightTimelapseConfig:
    """Settings for LED/Laser paired image acquisition."""

    output_dir: Path = Path("captures/light_timelapse")
    cycle_interval_seconds: float = 10.0
    duration_seconds: float = 3600.0
    light_settle_seconds: float = 0.1
    light_hold_seconds: float = 3.0
    light_off_wait_seconds: float = 2.0
    led_hold_seconds: float | None = None
    laser_hold_seconds: float | None = None
    led_off_wait_seconds: float | None = None
    laser_off_wait_seconds: float | None = None
    lights: tuple[str, ...] = ("led", "laser")
    camera_retries: int = 2
    camera_retry_seconds: float = 2.0
    led_exposure_us: CameraAutoSetting | None = None
    led_gain: CameraAutoSetting | None = None
    led_image_type: str | None = None
    led_white_balance_r: int | None = None
    led_white_balance_b: int | None = None
    laser_exposure_us: CameraAutoSetting | None = None
    laser_gain: CameraAutoSetting | None = None
    laser_image_type: str | None = None
    laser_white_balance_r: int | None = None
    laser_white_balance_b: int | None = None
    led_controls: dict[str, tuple[int, bool]] = field(default_factory=dict)
    laser_controls: dict[str, tuple[int, bool]] = field(default_factory=dict)
    laser_spectrum_enabled: bool = False
    spectrum_exposure_us: int = 10_000
    spectrum_averages: int = 1
    spectrum_blank_scans: int = 0
    spectrum_retries: int = 2
    spectrum_retry_seconds: float = 2.0
    spectrum_wavelengths_nm: Any | None = None
    autofocus_interval_seconds: float | None = 3600.0
    autofocus_interval_cycles: int | None = None
    autofocus_light: str = "led"
    autofocus_light_settle_seconds: float | None = None
    autofocus_lock_to_start: bool = False
    autofocus_config: AutofocusConfig = field(default_factory=AutofocusConfig)
    report_filename: str = "acquisition_report.csv"


@dataclass(slots=True)
class LightTimelapseResult:
    """Final result of a LED/Laser paired acquisition run."""

    run_dir: Path
    report_path: Path
    cycle_count: int
    autofocus_count: int


def run_light_timelapse(system: MicroscopeSystem, config: LightTimelapseConfig) -> LightTimelapseResult:
    """Run repeated LED/Laser paired capture with optional periodic autofocus."""

    _validate_config(config)
    _validate_system(system, config)

    run_dir = config.output_dir / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    run_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / config.report_filename

    base_autofocus_config = config.autofocus_config
    if config.autofocus_lock_to_start:
        reference_position = float(system.stage.get_position_mm())
        base_autofocus_config = replace(base_autofocus_config, reference_position_mm=reference_position)
        print(f"Autofocus reference locked to start position: {reference_position:.6f} mm")

    autofocus_config = replace(base_autofocus_config, output_dir=run_dir / "autofocus")
    start_time = time.monotonic()
    next_autofocus_elapsed = config.autofocus_interval_seconds
    cycle_index = 0
    autofocus_count = 0

    with report_path.open("w", newline="", encoding="utf-8-sig") as report_file:
        writer = csv.writer(report_file)
        _write_report_header(writer, config, run_dir)
        report_file.flush()

        try:
            while True:
                elapsed_seconds = time.monotonic() - start_time

                cycle_focus_due = (
                    config.autofocus_interval_cycles is not None
                    and cycle_index > 0
                    and cycle_index % config.autofocus_interval_cycles == 0
                )
                time_focus_due = next_autofocus_elapsed is not None and elapsed_seconds >= next_autofocus_elapsed
                if cycle_focus_due or time_focus_due:
                    autofocus_count += 1
                    _run_autofocus_event(
                        system,
                        writer,
                        report_file,
                        start_time,
                        autofocus_count,
                        config,
                        autofocus_config,
                    )
                    while next_autofocus_elapsed is not None and elapsed_seconds >= next_autofocus_elapsed:
                        next_autofocus_elapsed += config.autofocus_interval_seconds or 0

                if elapsed_seconds >= config.duration_seconds:
                    break

                cycle_index += 1
                _run_capture_cycle(system, writer, report_file, start_time, cycle_index, config, run_dir)

                if time.monotonic() - start_time < config.duration_seconds:
                    print(f"Cycle {cycle_index}: waiting {config.cycle_interval_seconds:.1f} s before next cycle")
                    time.sleep(config.cycle_interval_seconds)

        finally:
            if system.light is not None:
                system.light.off()

    return LightTimelapseResult(
        run_dir=run_dir,
        report_path=report_path,
        cycle_count=cycle_index,
        autofocus_count=autofocus_count,
    )


def _run_capture_cycle(
    system: MicroscopeSystem,
    writer,
    report_file,
    start_time: float,
    cycle_index: int,
    config: LightTimelapseConfig,
    run_dir: Path,
) -> None:
    for light_name in config.lights:
        _apply_named_controls(system, config, light_name)
        exposure_us, gain, image_type, white_balance_r, white_balance_b = _camera_settings_for_light(config, light_name)
        hold_seconds, off_wait_seconds = _timing_for_light(config, light_name)
        print(f"Cycle {cycle_index}: {light_name.upper()} capture")
        image_path = _capture_light(
            system,
            light_name,
            run_dir,
            cycle_index,
            config.light_settle_seconds,
            hold_seconds,
            off_wait_seconds,
            exposure_us,
            gain,
            image_type,
            white_balance_r,
            white_balance_b,
            config.camera_retries,
            config.camera_retry_seconds,
            config,
        )
        _write_capture_row(
            writer,
            start_time,
            cycle_index,
            light_name,
            image_path[0],
            image_path[1],
            system,
            image_type,
            white_balance_r,
            white_balance_b,
            config,
        )
        report_file.flush()


def _capture_light(
    system: MicroscopeSystem,
    light_name: str,
    run_dir: Path,
    cycle_index: int,
    light_settle_seconds: float,
    light_hold_seconds: float,
    light_off_wait_seconds: float,
    exposure_us: CameraAutoSetting | None,
    gain: CameraAutoSetting | None,
    image_type: str | None,
    white_balance_r: int | None,
    white_balance_b: int | None,
    camera_retries: int,
    camera_retry_seconds: float,
    config: LightTimelapseConfig,
) -> tuple[Path, Path | None]:
    output_path = _capture_image_path(run_dir, cycle_index, light_name)
    spectrum_path: Path | None = None
    last_error: RuntimeError | TimeoutError | None = None

    for attempt in range(camera_retries + 1):
        if light_name == "led":
            system.light.select_led()
        elif light_name == "laser":
            system.light.select_laser()
        else:
            raise ValueError(f"Unsupported light name: {light_name!r}")

        time.sleep(light_settle_seconds)

        try:
            saved_path = system.capture_image(
                output_path,
                exposure_us=exposure_us,
                gain=gain,
                image_type=image_type,
                white_balance_r=white_balance_r,
                white_balance_b=white_balance_b,
            )
            if light_name == "laser" and config.laser_spectrum_enabled:
                spectrum_path = _capture_laser_spectrum(system, run_dir, cycle_index, config)
            if light_hold_seconds > 0:
                print(f"Cycle {cycle_index}: holding {light_name.upper()} for {light_hold_seconds:.1f} s after capture")
                time.sleep(light_hold_seconds)
            return saved_path, spectrum_path
        except (RuntimeError, TimeoutError) as exc:
            last_error = exc
            if attempt < camera_retries:
                print(
                    f"Cycle {cycle_index}: {light_name.upper()} capture failed; "
                    f"retrying {attempt + 1}/{camera_retries} after {camera_retry_seconds:.1f} s. "
                    f"Reason: {exc}"
                )
            else:
                print(f"Cycle {cycle_index}: {light_name.upper()} capture failed after retries.")
        finally:
            system.light.off()
            if light_off_wait_seconds > 0:
                print(f"Cycle {cycle_index}: waiting {light_off_wait_seconds:.1f} s after {light_name.upper()} off")
                time.sleep(light_off_wait_seconds)

        if attempt < camera_retries and camera_retry_seconds > 0:
            time.sleep(camera_retry_seconds)

    raise last_error or RuntimeError(f"{light_name.upper()} capture failed.")


def _run_autofocus_event(
    system: MicroscopeSystem,
    writer,
    report_file,
    start_time: float,
    autofocus_index: int,
    config: LightTimelapseConfig,
    autofocus_config: AutofocusConfig,
) -> None:
    print(f"Autofocus {autofocus_index}: starting with {config.autofocus_light.upper()} illumination")

    if config.autofocus_light == "led":
        system.light.select_led()
    elif config.autofocus_light == "laser":
        system.light.select_laser()
    else:
        raise ValueError(f"Unsupported autofocus_light: {config.autofocus_light!r}")

    autofocus_settle = (
        config.autofocus_light_settle_seconds
        if config.autofocus_light_settle_seconds is not None
        else config.light_settle_seconds
    )
    time.sleep(autofocus_settle)

    try:
        _apply_named_controls(system, config, config.autofocus_light)
        exposure_us, gain, image_type, white_balance_r, white_balance_b = _camera_settings_for_light(config, config.autofocus_light)
        _apply_camera_settings(system, exposure_us, gain, image_type, white_balance_r, white_balance_b)
        result = run_laplacian_autofocus(system, autofocus_config)
    finally:
        system.light.off()

    writer.writerow(
        [
            "autofocus",
            "",
            f"{time.monotonic() - start_time:.3f}",
            "",
            "",
            _stage_position_text(system),
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            "",
            datetime.now().isoformat(timespec="seconds"),
            str(result.report_path),
            f"{result.best_position_mm:.9f}",
            f"{result.best_score:.9f}",
            "",
            "",
            "",
        ]
    )
    report_file.flush()
    print(f"Autofocus {autofocus_index}: best position {result.best_position_mm:.6f} mm")


def _write_report_header(writer, config: LightTimelapseConfig, run_dir: Path) -> None:
    writer.writerow(["run_dir", str(run_dir)])
    writer.writerow(["post_cycle_wait_seconds", config.cycle_interval_seconds])
    writer.writerow(["duration_seconds", config.duration_seconds])
    writer.writerow(["light_settle_seconds", config.light_settle_seconds])
    writer.writerow(["light_hold_seconds", config.light_hold_seconds])
    writer.writerow(["light_off_wait_seconds", config.light_off_wait_seconds])
    writer.writerow(["led_hold_seconds", _optional_setting_text(config.led_hold_seconds)])
    writer.writerow(["laser_hold_seconds", _optional_setting_text(config.laser_hold_seconds)])
    writer.writerow(["led_off_wait_seconds", _optional_setting_text(config.led_off_wait_seconds)])
    writer.writerow(["laser_off_wait_seconds", _optional_setting_text(config.laser_off_wait_seconds)])
    writer.writerow(["lights", ",".join(config.lights)])
    writer.writerow(["camera_retries", config.camera_retries])
    writer.writerow(["camera_retry_seconds", config.camera_retry_seconds])
    writer.writerow(["led_exposure_us", _setting_text(config.led_exposure_us)])
    writer.writerow(["led_gain", _setting_text(config.led_gain)])
    writer.writerow(["led_image_type", _setting_text(config.led_image_type)])
    writer.writerow(["led_white_balance_r", _setting_text(config.led_white_balance_r)])
    writer.writerow(["led_white_balance_b", _setting_text(config.led_white_balance_b)])
    writer.writerow(["laser_exposure_us", _setting_text(config.laser_exposure_us)])
    writer.writerow(["laser_gain", _setting_text(config.laser_gain)])
    writer.writerow(["laser_image_type", _setting_text(config.laser_image_type)])
    writer.writerow(["laser_white_balance_r", _setting_text(config.laser_white_balance_r)])
    writer.writerow(["laser_white_balance_b", _setting_text(config.laser_white_balance_b)])
    writer.writerow(["laser_spectrum_enabled", config.laser_spectrum_enabled])
    writer.writerow(["spectrum_exposure_us", config.spectrum_exposure_us])
    writer.writerow(["spectrum_averages", config.spectrum_averages])
    writer.writerow(["spectrum_blank_scans", config.spectrum_blank_scans])
    writer.writerow(["spectrum_retries", config.spectrum_retries])
    writer.writerow(["spectrum_retry_seconds", config.spectrum_retry_seconds])
    writer.writerow(["autofocus_interval_seconds", config.autofocus_interval_seconds or "disabled"])
    writer.writerow(["autofocus_light", config.autofocus_light])
    writer.writerow(["autofocus_lock_to_start", config.autofocus_lock_to_start])
    writer.writerow([])
    writer.writerow(
        [
            "event",
            "cycle_index",
            "elapsed_seconds",
            "light",
            "image_path",
            "stage_position_mm",
            "camera_exposure_us",
            "camera_exposure_auto",
            "camera_gain",
            "camera_gain_auto",
            "camera_wb_r",
            "camera_wb_b",
            "requested_image_type",
            "requested_wb_r",
            "requested_wb_b",
            "timestamp",
            "autofocus_report_path",
            "autofocus_best_position_mm",
            "autofocus_best_score",
            "spectrum_path",
            "spectrum_exposure_us",
            "spectrum_averages",
        ]
    )


def _write_capture_row(
    writer,
    start_time: float,
    cycle_index: int,
    light_name: str,
    image_path: Path,
    spectrum_path: Path | None,
    system,
    image_type: str | None,
    white_balance_r: int | None,
    white_balance_b: int | None,
    config: LightTimelapseConfig,
) -> None:
    exposure_value, exposure_auto = _camera_control_text(system, "Exposure")
    gain_value, gain_auto = _camera_control_text(system, "Gain")
    white_balance_r_value, _ = _camera_control_text(system, "WB_R")
    white_balance_b_value, _ = _camera_control_text(system, "WB_B")
    writer.writerow(
        [
            "capture",
            cycle_index,
            f"{time.monotonic() - start_time:.3f}",
            light_name,
            str(image_path),
            _stage_position_text(system),
            exposure_value,
            exposure_auto,
            gain_value,
            gain_auto,
            white_balance_r_value,
            white_balance_b_value,
            _setting_text(image_type),
            _setting_text(white_balance_r),
            _setting_text(white_balance_b),
            datetime.now().isoformat(timespec="seconds"),
            "",
            "",
            "",
            str(spectrum_path) if spectrum_path else "",
            config.spectrum_exposure_us if spectrum_path else "",
            config.spectrum_averages if spectrum_path else "",
        ]
    )


def _capture_image_path(run_dir: Path, cycle_index: int, light_name: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return run_dir / light_name / f"cycle_{cycle_index:05d}_{light_name}_{timestamp}.tiff"


def _capture_spectrum_path(run_dir: Path, cycle_index: int) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    return run_dir / "spectra" / f"cycle_{cycle_index:05d}_laser_spectrum_{timestamp}.csv"


def _capture_laser_spectrum(
    system: MicroscopeSystem,
    run_dir: Path,
    cycle_index: int,
    config: LightTimelapseConfig,
) -> Path:
    output_path = _capture_spectrum_path(run_dir, cycle_index)
    last_error: RuntimeError | TimeoutError | None = None

    for attempt in range(config.spectrum_retries + 1):
        try:
            spectrum = system.capture_spectrum(
                exposure_us=config.spectrum_exposure_us,
                averages=config.spectrum_averages,
                blank_scans=config.spectrum_blank_scans,
            )
            saved_path = save_spectrum_csv(spectrum, output_path, config.spectrum_wavelengths_nm)
            print(f"Cycle {cycle_index}: saved LASER spectrum -> {saved_path}")
            return saved_path
        except (RuntimeError, TimeoutError) as exc:
            last_error = exc
            if attempt < config.spectrum_retries:
                print(
                    f"Cycle {cycle_index}: LASER spectrum failed; "
                    f"retrying {attempt + 1}/{config.spectrum_retries} after {config.spectrum_retry_seconds:.1f} s. "
                    f"Reason: {exc}"
                )
                if config.spectrum_retry_seconds > 0:
                    time.sleep(config.spectrum_retry_seconds)
            else:
                print(f"Cycle {cycle_index}: LASER spectrum failed after retries.")

    raise last_error or RuntimeError("LASER spectrum capture failed.")


def _camera_settings_for_light(
    config: LightTimelapseConfig,
    light_name: str,
) -> tuple[CameraAutoSetting | None, CameraAutoSetting | None, str | None, int | None, int | None]:
    if light_name == "led":
        return (
            config.led_exposure_us,
            config.led_gain,
            config.led_image_type,
            config.led_white_balance_r,
            config.led_white_balance_b,
        )
    if light_name == "laser":
        return (
            config.laser_exposure_us,
            config.laser_gain,
            config.laser_image_type,
            config.laser_white_balance_r,
            config.laser_white_balance_b,
        )
    raise ValueError(f"Unsupported light name: {light_name!r}")


def _apply_named_controls(system: MicroscopeSystem, config: LightTimelapseConfig, light_name: str) -> None:
    controls = config.led_controls if light_name == "led" else config.laser_controls
    for name, (value, auto) in controls.items():
        system.camera.set_control(name, value, auto=auto)


def _timing_for_light(config: LightTimelapseConfig, light_name: str) -> tuple[float, float]:
    if light_name == "led":
        return (
            config.led_hold_seconds if config.led_hold_seconds is not None else config.light_hold_seconds,
            config.led_off_wait_seconds if config.led_off_wait_seconds is not None else config.light_off_wait_seconds,
        )
    if light_name == "laser":
        return (
            config.laser_hold_seconds if config.laser_hold_seconds is not None else config.light_hold_seconds,
            config.laser_off_wait_seconds if config.laser_off_wait_seconds is not None else config.light_off_wait_seconds,
        )
    raise ValueError(f"Unsupported light name: {light_name!r}")


def _apply_camera_settings(
    system: MicroscopeSystem,
    exposure_us: CameraAutoSetting | None,
    gain: CameraAutoSetting | None,
    image_type: str | None,
    white_balance_r: int | None,
    white_balance_b: int | None,
) -> None:
    camera = getattr(system, "camera", None)
    if camera is None:
        return

    if exposure_us is not None:
        if _is_auto_setting(exposure_us):
            camera.set_exposure_auto()
        else:
            camera.set_exposure_us(exposure_us)
    if gain is not None:
        if _is_auto_setting(gain):
            camera.set_gain_auto()
        else:
            camera.set_gain(gain)
    if white_balance_r is not None:
        camera.set_white_balance_r(white_balance_r)
    if white_balance_b is not None:
        camera.set_white_balance_b(white_balance_b)
    if image_type is not None:
        camera.set_image_type(image_type)


def _stage_position_text(system) -> str:
    if system.stage is None or not hasattr(system.stage, "get_position_mm"):
        return ""

    try:
        return f"{float(system.stage.get_position_mm()):.9f}"
    except Exception:
        return ""


def _camera_control_text(system, name: str) -> tuple[str, str]:
    camera = getattr(system, "camera", None)
    if camera is None or not hasattr(camera, "get_control"):
        return "", ""

    try:
        value, is_auto = camera.get_control(name)
        return str(value), str(bool(is_auto))
    except Exception:
        return "", ""


def _setting_text(value: CameraAutoSetting | None) -> str:
    if value is None:
        return "unchanged"
    return str(value)


def _optional_setting_text(value: float | None) -> str:
    if value is None:
        return "same as shared"
    return str(value)


def _is_auto_setting(value: CameraAutoSetting | None) -> bool:
    return isinstance(value, str) and value.strip().lower() == "auto"


def _validate_system(system: MicroscopeSystem, config: LightTimelapseConfig) -> None:
    if system.light is None:
        raise RuntimeError("Light timelapse needs system.light, but system.light is None.")
    if config.laser_spectrum_enabled and "laser" in config.lights and system.spectrometer is None:
        raise RuntimeError("Laser spectrum capture needs system.spectrometer, but system.spectrometer is None.")
    if config.autofocus_lock_to_start and system.stage is None:
        raise RuntimeError("autofocus_lock_to_start needs system.stage, but system.stage is None.")
    autofocus_enabled = config.autofocus_interval_seconds is not None or config.autofocus_interval_cycles is not None
    if autofocus_enabled and system.stage is None:
        raise RuntimeError("Periodic autofocus needs system.stage, but system.stage is None.")


def _validate_config(config: LightTimelapseConfig) -> None:
    if config.cycle_interval_seconds <= 0:
        raise ValueError("cycle_interval_seconds must be positive.")
    if config.duration_seconds <= 0:
        raise ValueError("duration_seconds must be positive.")
    if config.light_settle_seconds < 0:
        raise ValueError("light_settle_seconds cannot be negative.")
    if config.light_hold_seconds < 0:
        raise ValueError("light_hold_seconds cannot be negative.")
    if config.light_off_wait_seconds < 0:
        raise ValueError("light_off_wait_seconds cannot be negative.")
    _validate_optional_seconds("led_hold_seconds", config.led_hold_seconds)
    _validate_optional_seconds("laser_hold_seconds", config.laser_hold_seconds)
    _validate_optional_seconds("led_off_wait_seconds", config.led_off_wait_seconds)
    _validate_optional_seconds("laser_off_wait_seconds", config.laser_off_wait_seconds)
    if not config.lights:
        raise ValueError("lights must contain at least one light.")
    for light_name in config.lights:
        if light_name not in {"led", "laser"}:
            raise ValueError('lights must contain only "led" and/or "laser".')
    if config.camera_retries < 0:
        raise ValueError("camera_retries cannot be negative.")
    if config.camera_retry_seconds < 0:
        raise ValueError("camera_retry_seconds cannot be negative.")
    if config.spectrum_exposure_us <= 0:
        raise ValueError("spectrum_exposure_us must be positive.")
    if config.spectrum_averages <= 0:
        raise ValueError("spectrum_averages must be positive.")
    if config.spectrum_blank_scans < 0:
        raise ValueError("spectrum_blank_scans cannot be negative.")
    if config.spectrum_retries < 0:
        raise ValueError("spectrum_retries cannot be negative.")
    if config.spectrum_retry_seconds < 0:
        raise ValueError("spectrum_retry_seconds cannot be negative.")
    if config.autofocus_lock_to_start and config.autofocus_config.reference_position_mm is not None:
        raise ValueError("Use either autofocus_lock_to_start or autofocus_config.reference_position_mm, not both.")
    if config.autofocus_lock_to_start and config.autofocus_config.scan_mode == "absolute":
        raise ValueError("autofocus_lock_to_start is not used with absolute autofocus scan mode.")
    _validate_camera_setting("led_exposure_us", config.led_exposure_us, must_be_positive=True)
    _validate_camera_setting("laser_exposure_us", config.laser_exposure_us, must_be_positive=True)
    _validate_camera_setting("led_gain", config.led_gain, must_be_positive=False)
    _validate_camera_setting("laser_gain", config.laser_gain, must_be_positive=False)
    _validate_image_type("led_image_type", config.led_image_type)
    _validate_image_type("laser_image_type", config.laser_image_type)
    _validate_camera_setting("led_white_balance_r", config.led_white_balance_r, must_be_positive=True)
    _validate_camera_setting("led_white_balance_b", config.led_white_balance_b, must_be_positive=True)
    _validate_camera_setting("laser_white_balance_r", config.laser_white_balance_r, must_be_positive=True)
    _validate_camera_setting("laser_white_balance_b", config.laser_white_balance_b, must_be_positive=True)
    if config.autofocus_interval_seconds is not None and config.autofocus_interval_seconds <= 0:
        raise ValueError("autofocus_interval_seconds must be positive or None.")
    if config.autofocus_interval_cycles is not None and config.autofocus_interval_cycles <= 0:
        raise ValueError("autofocus_interval_cycles must be positive or None.")
    _validate_optional_seconds("autofocus_light_settle_seconds", config.autofocus_light_settle_seconds)
    if config.autofocus_light not in {"led", "laser"}:
        raise ValueError('autofocus_light must be "led" or "laser".')


def _validate_camera_setting(name: str, value: CameraAutoSetting | None, *, must_be_positive: bool) -> None:
    if value is None:
        return
    if isinstance(value, str):
        if value.strip().lower() == "auto":
            return
        raise ValueError(f"{name} must be an integer, 'auto', or None.")
    if must_be_positive and value <= 0:
        raise ValueError(f"{name} must be positive.")
    if not must_be_positive and value < 0:
        raise ValueError(f"{name} cannot be negative.")


def _validate_image_type(name: str, value: str | None) -> None:
    if value is None:
        return
    if value not in {"raw8", "raw16", "rgb24", "y8"}:
        raise ValueError(f"{name} must be one of raw8, raw16, rgb24, y8.")


def _validate_optional_seconds(name: str, value: float | None) -> None:
    if value is not None and value < 0:
        raise ValueError(f"{name} cannot be negative.")

