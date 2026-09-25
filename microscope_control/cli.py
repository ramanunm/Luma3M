from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from microscope_control.config import CameraAutoSetting, CameraConfig
from microscope_control.devices.arduino_uno import ArduinoUnoConfig, ArduinoUnoLightController
from microscope_control.devices.aseq_spectrometer import AseqSpectrometer, AseqSpectrometerConfig, load_wavelengths
from microscope_control.devices.thorlabs_mlj050 import LabJackConfig, ThorlabsMLJ050
from microscope_control.devices.zwo_camera import ZwoCamera
from microscope_control.functions.camera import apply_named_controls, camera_information
from microscope_control.functions.doctor import work_computer_report
from microscope_control.functions.light import run_light_sequence, set_light, timed_light
from microscope_control.functions.spectrum import capture_spectrum
from microscope_control.functions.stage import home_stage, move_stage
from microscope_control.settings import SETTINGS
from microscope_control.system import MicroscopeSystem
from microscope_control.workflows.alternate import AlternateConfig, run_alternate
from microscope_control.workflows.autofocus import AutofocusConfig
from microscope_control.workflows.focus import run_autofocus
from microscope_control.workflows.image import capture_light_image


IMAGE_TYPES = ("raw8", "raw16", "rgb24", "y8")
LIGHTS = ("led", "laser")


def parse_auto_int(value: str) -> CameraAutoSetting:
    cleaned = value.strip().lower()
    if cleaned == "auto":
        return "auto"
    try:
        return int(cleaned)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("请输入整数或 auto。") from exc


def parse_auto_ms(value: str) -> CameraAutoSetting:
    cleaned = value.strip().lower()
    if cleaned == "auto":
        return "auto"
    try:
        milliseconds = float(cleaned)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("请输入毫秒数或 auto。") from exc
    if milliseconds <= 0:
        raise argparse.ArgumentTypeError("曝光时间必须大于 0。")
    return int(round(milliseconds * 1000))


def parse_control(value: str) -> tuple[str, tuple[int, bool]]:
    """Parse NAME=VALUE or NAME=auto for model-specific ZWO controls."""

    if "=" not in value:
        raise argparse.ArgumentTypeError("控制项格式应为 NAME=VALUE 或 NAME=auto。")
    name, raw_value = (part.strip() for part in value.split("=", 1))
    if not name:
        raise argparse.ArgumentTypeError("控制项名称不能为空。")
    if raw_value.lower() == "auto":
        return name, (0, True)
    try:
        return name, (int(raw_value), False)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("控制项的值必须是整数或 auto。") from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="microscopy",
        description="显微镜平台正式控制程序：设备功能与复合采集工作流的统一入口。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="检查工作电脑环境，不移动平台或切换光路")
    doctor.set_defaults(handler=_run_doctor)

    camera_info = subparsers.add_parser("camera-info", help="列出相机、ROI、范围和全部 SDK 控制项")
    _add_camera_connection_args(camera_info)
    camera_info.set_defaults(handler=_run_camera_info)

    stage = subparsers.add_parser("stage", help="移动或回零 MLJ050 平台")
    _add_stage_args(stage)
    action = stage.add_mutually_exclusive_group(required=True)
    action.add_argument("--move-mode", choices=("up", "down"))
    action.add_argument("--home", action="store_true")
    stage.add_argument("--move-range-mm", type=float, default=0.2)
    stage.set_defaults(handler=_run_stage)

    light = subparsers.add_parser("light", help="单独控制 LED/laser 或运行一次光路序列")
    _add_light_connection_args(light)
    light.add_argument("--led", choices=("on", "off"))
    light.add_argument("--laser", choices=("on", "off"))
    light.add_argument("--led-on-s", type=float)
    light.add_argument("--led-off-s", type=float, default=0.0)
    light.add_argument("--laser-on-s", type=float)
    light.add_argument("--laser-off-s", type=float, default=0.0)
    light.set_defaults(handler=_run_light)

    spectrum = subparsers.add_parser("spectrum", help="单独采集一次 ASEQ 光谱")
    _add_spectrometer_args(spectrum)
    spectrum.add_argument("--output", default=None)
    spectrum.set_defaults(handler=_run_spectrum)

    image = subparsers.add_parser("image", help="在指定光路下拍摄单张图像")
    _add_camera_args(image)
    _add_light_connection_args(image)
    image.add_argument("--light-image", required=True, choices=LIGHTS)
    image.add_argument("--light-settle-s", type=float, default=1.0)
    image.add_argument("--output", default=None)
    image.add_argument("--reference-axes", action="store_true", help="保存用于选择 focus ROI 的归一化坐标轴图")
    image.add_argument("--axis-step", type=float, default=0.1)
    image.add_argument("--axis-border-px", type=int, default=70)
    image.set_defaults(handler=_run_image)

    focus = subparsers.add_parser("focus", help="使用 MLJ050、相机和指定光路自动对焦")
    _add_camera_args(focus)
    _add_light_connection_args(focus)
    _add_stage_args(focus)
    _add_focus_args(focus)
    focus.set_defaults(handler=_run_focus)

    alternate = subparsers.add_parser("alternate", help="长时间光路轮换成像，可同步光谱和自动对焦")
    _add_camera_args(alternate, exposure_default=10_000, gain_default=None)
    _add_light_connection_args(alternate)
    _add_stage_args(alternate)
    _add_spectrometer_args(alternate)
    _add_focus_args(alternate, prefixed=True)
    alternate.add_argument("--lights", choices=("led", "laser", "both"), default="both")
    alternate.add_argument("--duration-m", type=float, default=SETTINGS.acquisition.get("duration_minutes", 60.0))
    alternate.add_argument("--cycle-interval-s", type=float, default=SETTINGS.acquisition.get("cycle_interval_seconds", 10.0))
    alternate.add_argument("--focus", choices=("on", "off"), default="on")
    alternate.add_argument("--focus-interval", type=int, default=SETTINGS.acquisition.get("autofocus_every_cycles", 100), help="每 N 个完整循环自动对焦一次")
    alternate.add_argument("--spectrum", choices=("on", "off"), default="on" if SETTINGS.acquisition.get("spectrum_enabled", True) else "off")
    alternate.add_argument("--light-led-on-s", type=float, default=SETTINGS.acquisition.get("led_hold_seconds", 3.0))
    alternate.add_argument("--light-led-off-s", type=float, default=SETTINGS.acquisition.get("led_off_wait_seconds", 2.0))
    alternate.add_argument("--light-laser-on-s", type=float, default=SETTINGS.acquisition.get("laser_hold_seconds", 3.0))
    alternate.add_argument("--light-laser-off-s", type=float, default=SETTINGS.acquisition.get("laser_off_wait_seconds", 2.0))
    alternate.add_argument("--output-dir", default=str(SETTINGS.output_root / "alternate"))
    _add_light_profile_args(alternate, "led")
    _add_light_profile_args(alternate, "laser")
    alternate.set_defaults(handler=_run_alternate)
    return parser


def _add_camera_connection_args(parser) -> None:
    parser.add_argument("--camera-index", type=int, default=SETTINGS.camera_index)


def _add_camera_args(
    parser,
    *,
    exposure_default: CameraAutoSetting | None = None,
    gain_default: CameraAutoSetting | None = None,
) -> None:
    if exposure_default is None:
        exposure_default = SETTINGS.camera.get("exposure_us", 10_000)
    if gain_default is None:
        gain_default = SETTINGS.camera.get("gain")
    _add_camera_connection_args(parser)
    exposure = parser.add_mutually_exclusive_group()
    exposure.add_argument("--exposure-us", type=parse_auto_int, default=exposure_default)
    exposure.add_argument("--exposure-ms", type=parse_auto_ms)
    parser.add_argument("--gain", type=parse_auto_int, default=gain_default)
    parser.add_argument("--wb-r", type=int)
    parser.add_argument("--wb-b", type=int)
    parser.add_argument("--image-type", choices=IMAGE_TYPES, default=SETTINGS.camera.get("image_type", "raw16"))
    parser.add_argument("--roi-width", type=int)
    parser.add_argument("--roi-height", type=int)
    parser.add_argument("--software-binning", type=int)
    parser.add_argument("--high-speed", choices=("on", "off"))
    parser.add_argument("--bandwidth", type=int)
    parser.add_argument("--cooler", choices=("on", "off"))
    parser.add_argument("--target-temperature-c", type=int)
    parser.add_argument("--camera-control", action="append", type=parse_control, default=[], metavar="NAME=VALUE")


def _add_light_profile_args(parser, prefix: str) -> None:
    profile = SETTINGS.led if prefix == "led" else SETTINGS.laser
    exposure = parser.add_mutually_exclusive_group()
    exposure.add_argument(f"--{prefix}-exposure-us", type=parse_auto_int, default=profile.get("exposure_us"))
    exposure.add_argument(f"--{prefix}-exposure-ms", type=parse_auto_ms)
    parser.add_argument(f"--{prefix}-gain", type=parse_auto_int, default=profile.get("gain"))
    parser.add_argument(f"--{prefix}-wb-r", type=int, default=profile.get("wb_r"))
    parser.add_argument(f"--{prefix}-wb-b", type=int, default=profile.get("wb_b"))
    parser.add_argument(f"--{prefix}-image-type", choices=IMAGE_TYPES, default=profile.get("image_type"))
    parser.add_argument(f"--{prefix}-control", action="append", type=parse_control, default=[], metavar="NAME=VALUE")


def _add_stage_args(parser) -> None:
    parser.add_argument("--stage-serial", default=SETTINGS.stage_serial)
    parser.add_argument("--kinesis-dir", type=Path, default=SETTINGS.kinesis_dir)


def _add_light_connection_args(parser) -> None:
    parser.add_argument("--port", default=SETTINGS.arduino_port)
    parser.add_argument("--baud-rate", type=int, default=SETTINGS.arduino_baud_rate)


def _add_spectrometer_args(parser) -> None:
    parser.add_argument("--spectrum-dll-path", type=Path, default=SETTINGS.aseq_dll)
    parser.add_argument("--spectrum-device-index", type=int, default=SETTINGS.spectrum_device_index)
    parser.add_argument("--spectrum-exposure-us", type=int, default=10_000)
    parser.add_argument("--spectrum-averages", type=int, default=1)
    parser.add_argument("--spectrum-blank-scans", type=int, default=0)
    parser.add_argument("--spectrum-timeout-s", type=float, default=10.0)
    parser.add_argument("--spectrum-calibration-file", type=Path, default=SETTINGS.aseq_calibration)
    parser.add_argument("--no-spectrum-calibration", action="store_true")


def _add_focus_args(parser, *, prefixed: bool = False) -> None:
    prefix = "af-" if prefixed else ""
    parser.add_argument(f"--{prefix}focus-light", choices=LIGHTS, default="led")
    parser.add_argument(f"--{prefix}focus-metric", choices=("tenengrad", "laplacian"), default="tenengrad")
    parser.add_argument(f"--{prefix}scan-mode", choices=("up", "down", "centered", "plus-minus", "absolute"), default="plus-minus")
    parser.add_argument(f"--{prefix}scan-range-mm", type=float, default=0.05)
    parser.add_argument(f"--{prefix}step-mm", type=float, default=0.005)
    parser.add_argument(f"--{prefix}min-position-mm", type=float, default=0.0)
    parser.add_argument(f"--{prefix}max-position-mm", type=float)
    parser.add_argument(f"--{prefix}settle-s", type=float, default=0.2)
    parser.add_argument(f"--{prefix}light-settle-s", type=float, default=1.0)
    parser.add_argument(f"--{prefix}focus-roi", nargs=4, type=float, metavar=("X", "Y", "W", "H"))
    save = parser.add_mutually_exclusive_group()
    save.add_argument(f"--{prefix}save-frames", choices=("all", "clear"), default="clear")
    save.add_argument(f"--{prefix}no-save-frames", action="store_true")
    if not prefixed:
        parser.add_argument("--output-dir", default=str(SETTINGS.output_root / "focus"))


def _camera_config(args) -> CameraConfig:
    exposure = args.exposure_ms if args.exposure_ms is not None else args.exposure_us
    return CameraConfig(
        camera_index=args.camera_index,
        exposure_us=exposure,
        gain=args.gain,
        white_balance_r=args.wb_r,
        white_balance_b=args.wb_b,
        image_type=args.image_type,
        roi_width=args.roi_width,
        roi_height=args.roi_height,
        software_binning=args.software_binning,
        high_speed_mode=_on_off(args.high_speed),
        bandwidth=args.bandwidth,
        cooler=_on_off(args.cooler),
        target_temperature_c=args.target_temperature_c,
    )


def _stage_config(args) -> LabJackConfig:
    return LabJackConfig(serial_number=args.stage_serial, kinesis_dir=args.kinesis_dir)


def _light_config(args) -> ArduinoUnoConfig:
    return ArduinoUnoConfig(port=args.port, baud_rate=args.baud_rate)


def _spectrum_config(args) -> AseqSpectrometerConfig:
    return AseqSpectrometerConfig(
        dll_path=args.spectrum_dll_path,
        device_index=args.spectrum_device_index,
        acquisition_timeout_seconds=args.spectrum_timeout_s,
    )


def _focus_config(args, *, prefixed: bool = False, output_dir: Path | None = None) -> AutofocusConfig:
    p = "af_" if prefixed else ""
    no_save = getattr(args, f"{p}no_save_frames")
    save_mode = getattr(args, f"{p}save_frames")
    return AutofocusConfig(
        scan_range_mm=getattr(args, f"{p}scan_range_mm"),
        step_mm=getattr(args, f"{p}step_mm"),
        scan_mode=getattr(args, f"{p}scan_mode"),
        min_position_mm=getattr(args, f"{p}min_position_mm"),
        max_position_mm=getattr(args, f"{p}max_position_mm"),
        settle_seconds=getattr(args, f"{p}settle_s"),
        focus_roi=tuple(getattr(args, f"{p}focus_roi")) if getattr(args, f"{p}focus_roi") else None,
        focus_metric=getattr(args, f"{p}focus_metric"),
        output_dir=output_dir or Path(args.output_dir),
        save_frames=not no_save,
        save_best_only=save_mode == "clear",
    )


def _run_doctor(args) -> None:
    print(f"Configuration: {SETTINGS.config_path}")
    failures = 0
    for name, passed, detail in work_computer_report(SETTINGS):
        label = "PASS" if passed else "CHECK"
        failures += not passed
        print(f"[{label}] {name}: {detail}")
    if failures:
        print(f"Environment checks needing attention: {failures}")
    else:
        print("All non-actuating work-computer checks passed.")


def _run_camera_info(args) -> None:
    with ZwoCamera(CameraConfig(camera_index=args.camera_index)) as camera:
        info = camera_information(camera)
    print(f"Camera: {info['name']} (index {info['camera_id']})")
    print(f"ROI: {info['roi']}")
    print(f"Exposure limits (us): {info['exposure_limits_us']}")
    print(f"Gain limits: {info['gain_limits']}")
    print(f"Temperature (C): {info['temperature_c']}")
    print("Controls supported by this camera:")
    for control in info["controls"]:
        print(f"  {control}")


def _run_stage(args) -> None:
    with ThorlabsMLJ050(_stage_config(args)) as stage:
        position = home_stage(stage) if args.home else move_stage(stage, args.move_mode, args.move_range_mm)
    print(f"Stage position: {position:.6f} mm")


def _run_light(args) -> None:
    specified = [args.led, args.laser, args.led_on_s, args.laser_on_s]
    if all(value is None for value in specified):
        raise ValueError("请指定 --led/--laser 或定时参数。")
    with ArduinoUnoLightController(_light_config(args)) as light:
        try:
            if args.led is not None:
                set_light(light, "led", args.led == "on")
                if args.led == "on" and args.led_on_s is None:
                    input("LED 已开启；按 Enter 关闭。")
            if args.laser is not None:
                set_light(light, "laser", args.laser == "on")
                if args.laser == "on" and args.laser_on_s is None:
                    input("Laser 已开启；按 Enter 关闭。")
            if args.led_on_s is not None and args.laser_on_s is not None:
                run_light_sequence(
                    light,
                    led_on_seconds=args.led_on_s,
                    led_off_seconds=args.led_off_s,
                    laser_on_seconds=args.laser_on_s,
                    laser_off_seconds=args.laser_off_s,
                )
            elif args.led_on_s is not None:
                timed_light(light, "led", args.led_on_s, args.led_off_s)
            elif args.laser_on_s is not None:
                timed_light(light, "laser", args.laser_on_s, args.laser_off_s)
        finally:
            light.off()


def _run_spectrum(args) -> None:
    output = Path(args.output) if args.output else _timestamped(SETTINGS.output_root / "spectra", "spectrum", ".csv")
    wavelengths = _load_calibration(args)
    with AseqSpectrometer(_spectrum_config(args)) as spectrometer:
        saved = capture_spectrum(
            spectrometer,
            output,
            exposure_us=args.spectrum_exposure_us,
            averages=args.spectrum_averages,
            blank_scans=args.spectrum_blank_scans,
            wavelengths_nm=wavelengths,
        )
    print(f"Saved spectrum: {saved}")


def _run_image(args) -> None:
    output = Path(args.output) if args.output else _timestamped(SETTINGS.output_root / "image", args.light_image, ".tiff")
    system = MicroscopeSystem(
        camera_config=_camera_config(args),
        light=ArduinoUnoLightController(_light_config(args)),
    )
    with system:
        apply_named_controls(system.camera, dict(args.camera_control))
        saved = capture_light_image(
            system,
            output,
            light=args.light_image,
            settle_seconds=args.light_settle_s,
            reference_axes=args.reference_axes,
            axis_step=args.axis_step,
            axis_border_px=args.axis_border_px,
        )
    print(f"Saved image: {saved}")


def _run_focus(args) -> None:
    system = MicroscopeSystem(
        camera_config=_camera_config(args),
        stage=ThorlabsMLJ050(_stage_config(args)),
        light=ArduinoUnoLightController(_light_config(args)),
    )
    with system:
        apply_named_controls(system.camera, dict(args.camera_control))
        result = run_autofocus(
            system,
            _focus_config(args),
            light=args.focus_light,
            light_settle_seconds=args.light_settle_s,
        )
    print(f"Best focus: {result.best_position_mm:.6f} mm; score={result.best_score:.6f}")
    print(f"Report: {result.report_path}")


def _run_alternate(args) -> None:
    camera_config = _camera_config(args)
    spectrometer = AseqSpectrometer(_spectrum_config(args)) if args.spectrum == "on" else None
    system = MicroscopeSystem(
        camera_config=camera_config,
        stage=ThorlabsMLJ050(_stage_config(args)),
        light=ArduinoUnoLightController(_light_config(args)),
        spectrometer=spectrometer,
    )
    lights = ("led", "laser") if args.lights == "both" else (args.lights,)
    focus_enabled = args.focus == "on"
    config = AlternateConfig(
        output_dir=Path(args.output_dir),
        cycle_interval_seconds=args.cycle_interval_s,
        duration_seconds=args.duration_m * 60.0,
        light_settle_seconds=SETTINGS.acquisition.get("light_settle_seconds", 0.1),
        autofocus_light_settle_seconds=args.af_light_settle_s,
        lights=lights,
        led_hold_seconds=args.light_led_on_s,
        led_off_wait_seconds=args.light_led_off_s,
        laser_hold_seconds=args.light_laser_on_s,
        laser_off_wait_seconds=args.light_laser_off_s,
        led_exposure_us=args.led_exposure_ms if args.led_exposure_ms is not None else args.led_exposure_us,
        led_gain=args.led_gain,
        led_white_balance_r=args.led_wb_r,
        led_white_balance_b=args.led_wb_b,
        led_image_type=args.led_image_type,
        laser_exposure_us=args.laser_exposure_ms if args.laser_exposure_ms is not None else args.laser_exposure_us,
        laser_gain=args.laser_gain,
        laser_white_balance_r=args.laser_wb_r,
        laser_white_balance_b=args.laser_wb_b,
        laser_image_type=args.laser_image_type,
        led_controls=dict(args.led_control),
        laser_controls=dict(args.laser_control),
        laser_spectrum_enabled=args.spectrum == "on",
        spectrum_exposure_us=args.spectrum_exposure_us,
        spectrum_averages=args.spectrum_averages,
        spectrum_blank_scans=args.spectrum_blank_scans,
        spectrum_wavelengths_nm=_load_calibration(args),
        autofocus_interval_seconds=None,
        autofocus_interval_cycles=args.focus_interval if focus_enabled else None,
        autofocus_light=args.af_focus_light,
        autofocus_config=_focus_config(args, prefixed=True, output_dir=Path(args.output_dir) / "autofocus"),
    )
    with system:
        apply_named_controls(system.camera, dict(args.camera_control))
        result = run_alternate(system, config)
    print(f"Cycles: {result.cycle_count}; autofocus events: {result.autofocus_count}")
    print(f"Run directory: {result.run_dir}")


def _on_off(value: str | None) -> bool | None:
    if value is None:
        return None
    return value == "on"


def _load_calibration(args):
    if args.no_spectrum_calibration:
        return None
    path = Path(args.spectrum_calibration_file)
    if not path.exists():
        return None
    return load_wavelengths(path)


def _timestamped(folder: str | Path, prefix: str, suffix: str) -> Path:
    return Path(folder) / f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}{suffix}"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.handler(args)
    except KeyboardInterrupt:
        print("\n已由用户中止；设备清理逻辑已执行。")
        return 130
    except (RuntimeError, ValueError, OSError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
