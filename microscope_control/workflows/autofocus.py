from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from microscope_control.devices.zwo_camera import save_frame
from microscope_control.system import MicroscopeSystem


@dataclass(slots=True)
class AutofocusConfig:
    """Settings for an autofocus scan."""

    scan_range_mm: float = 0.05
    step_mm: float = 0.005
    scan_mode: str = "up"
    reference_position_mm: float | None = None
    min_position_mm: float | None = 0.0
    max_position_mm: float | None = None
    settle_seconds: float = 0.2
    center_crop_fraction: float = 1.0
    focus_roi: tuple[float, float, float, float] | None = None
    focus_metric: str = "tenengrad"
    camera_retries: int = 2
    camera_retry_seconds: float = 2.0
    output_dir: Path = Path("captures/autofocus")
    save_frames: bool = True
    save_best_only: bool = True
    report_filename: str = "autofocus_report.csv"


@dataclass(slots=True)
class FocusPoint:
    """One autofocus measurement at one LabJack position."""

    index: int
    position_mm: float
    score: float
    mean_intensity: float
    max_intensity: float
    saturated_fraction: float
    image_path: Path | None


@dataclass(slots=True)
class AutofocusResult:
    """Final autofocus result."""

    start_position_mm: float
    best_position_mm: float
    best_score: float
    points: list[FocusPoint]
    report_path: Path


def laplacian_variance(
    frame,
    center_crop_fraction: float = 1.0,
    focus_roi: tuple[float, float, float, float] | None = None,
) -> float:
    """Return a focus score using Laplacian variance.

    A sharper image usually has stronger edges. The Laplacian highlights edges,
    and the variance measures how strong and varied those edges are. Higher is
    usually better focused.
    """

    gray = _to_grayscale_float(frame)
    gray = _crop_focus_region(gray, center_crop_fraction, focus_roi)

    if gray.shape[0] < 3 or gray.shape[1] < 3:
        raise ValueError("Image is too small to calculate Laplacian variance.")

    center = gray[1:-1, 1:-1]
    up = gray[:-2, 1:-1]
    down = gray[2:, 1:-1]
    left = gray[1:-1, :-2]
    right = gray[1:-1, 2:]

    laplacian = up + down + left + right - 4.0 * center
    return float(np.var(laplacian))


def tenengrad_score(
    frame,
    center_crop_fraction: float = 1.0,
    focus_roi: tuple[float, float, float, float] | None = None,
) -> float:
    """Return a focus score using Sobel gradient energy.

    Tenengrad is often less jumpy than Laplacian variance on noisy camera
    frames. Higher usually means sharper edges.
    """

    gray = _to_grayscale_float(frame)
    gray = _crop_focus_region(gray, center_crop_fraction, focus_roi)

    if gray.shape[0] < 3 or gray.shape[1] < 3:
        raise ValueError("Image is too small to calculate Tenengrad score.")

    top_left = gray[:-2, :-2]
    top = gray[:-2, 1:-1]
    top_right = gray[:-2, 2:]
    left = gray[1:-1, :-2]
    right = gray[1:-1, 2:]
    bottom_left = gray[2:, :-2]
    bottom = gray[2:, 1:-1]
    bottom_right = gray[2:, 2:]

    sobel_x = -top_left - 2.0 * left - bottom_left + top_right + 2.0 * right + bottom_right
    sobel_y = top_left + 2.0 * top + top_right - bottom_left - 2.0 * bottom - bottom_right
    gradient_energy = sobel_x * sobel_x + sobel_y * sobel_y
    return float(np.mean(gradient_energy))


def focus_score(
    frame,
    metric: str = "tenengrad",
    center_crop_fraction: float = 1.0,
    focus_roi: tuple[float, float, float, float] | None = None,
) -> float:
    """Calculate a focus score using the selected metric."""

    if metric == "tenengrad":
        return tenengrad_score(frame, center_crop_fraction, focus_roi)
    if metric == "laplacian":
        return laplacian_variance(frame, center_crop_fraction, focus_roi)
    raise ValueError(f"Unsupported focus metric: {metric!r}")


def run_laplacian_autofocus(system: MicroscopeSystem, config: AutofocusConfig) -> AutofocusResult:
    """Scan LabJack positions, score each image, and return to the best focus.

    The system must already be connected. The stage must support:
    get_position_mm() and move_to_mm(...).
    """

    _validate_config(config)

    if system.stage is None:
        raise RuntimeError("Autofocus needs a stage, but system.stage is None.")
    if not hasattr(system.stage, "get_position_mm") or not hasattr(system.stage, "move_to_mm"):
        raise RuntimeError("Autofocus stage must provide get_position_mm() and move_to_mm(...).")

    config.output_dir.mkdir(parents=True, exist_ok=True)

    start_position = float(system.stage.get_position_mm())
    scan_reference_position = config.reference_position_mm if config.reference_position_mm is not None else start_position
    positions = build_scan_positions(
        scan_reference_position,
        config.scan_range_mm,
        config.step_mm,
        scan_mode=config.scan_mode,
        min_position_mm=config.min_position_mm,
        max_position_mm=config.max_position_mm,
    )
    points: list[FocusPoint] = []
    best_frame = None
    best_score = None

    try:
        for index, position in enumerate(positions, start=1):
            system.stage.move_to_mm(position)
            time.sleep(config.settle_seconds)

            frame = _capture_with_retries(system.camera, config.camera_retries, config.camera_retry_seconds)
            score = focus_score(frame, config.focus_metric, config.center_crop_fraction, config.focus_roi)
            mean_intensity, max_intensity, saturated_fraction = _image_stats(
                frame,
                config.center_crop_fraction,
                config.focus_roi,
            )

            image_path = None
            if config.save_frames and not config.save_best_only:
                image_path = _focus_image_path(config.output_dir, index, position)
                save_frame(frame, image_path)

            point = FocusPoint(
                index=index,
                position_mm=position,
                score=score,
                mean_intensity=mean_intensity,
                max_intensity=max_intensity,
                saturated_fraction=saturated_fraction,
                image_path=image_path,
            )
            points.append(point)
            if best_score is None or score > best_score:
                best_score = score
                if config.save_frames and config.save_best_only:
                    best_frame = np.array(frame, copy=True)

            print(
                f"[{index}/{len(positions)}] position={position:.6f} mm, "
                f"{config.focus_metric}={score:.3f}, mean={mean_intensity:.1f}, "
                f"saturated={saturated_fraction:.4f}"
            )

    except Exception:
        # If something fails mid-scan, try to return to the starting position.
        try:
            system.stage.move_to_mm(start_position)
        finally:
            raise

    best_point = max(points, key=lambda point: point.score)
    system.stage.move_to_mm(best_point.position_mm)

    if config.save_frames and config.save_best_only:
        if best_frame is None:
            raise RuntimeError("Best autofocus frame was not captured.")
        best_image_path = _best_focus_image_path(config.output_dir, best_point.position_mm)
        save_frame(best_frame, best_image_path)
        best_point.image_path = best_image_path

    report_path = config.output_dir / config.report_filename
    _write_report(report_path, start_position, best_point, points, config)

    return AutofocusResult(
        start_position_mm=start_position,
        best_position_mm=best_point.position_mm,
        best_score=best_point.score,
        points=points,
        report_path=report_path,
    )


def build_scan_positions(
    start_mm: float,
    scan_range_mm: float,
    step_mm: float,
    *,
    scan_mode: str = "up",
    min_position_mm: float | None = 0.0,
    max_position_mm: float | None = None,
) -> list[float]:
    """Build MLJ050 scan positions.

    scan_mode controls the direction:
    - "up": start at the current position, then move upward.
    - "down": start at the current position, then move downward.
    - "centered": scan around the current position; scan_range_mm is the total range.
    - "plus-minus": scan around the current position; scan_range_mm is each side.
    - "absolute": scan from min_position_mm to max_position_mm, independent of current position.

    The default mode is "up" because many MLJ050 systems start near 0 mm.
    A centered or plus-minus scan near 0 mm would try negative positions,
    which Kinesis rejects.
    """

    if scan_mode == "absolute":
        if min_position_mm is None or max_position_mm is None:
            raise ValueError("absolute scan mode needs min_position_mm and max_position_mm.")
        return _build_inclusive_positions(min_position_mm, max_position_mm, step_mm)

    if scan_mode == "up":
        positions = _build_inclusive_positions(start_mm, start_mm + scan_range_mm, step_mm)
    elif scan_mode == "down":
        positions = _build_inclusive_positions(start_mm, start_mm - scan_range_mm, step_mm)
    elif scan_mode == "centered":
        half_range_mm = scan_range_mm / 2.0
        positions = _build_inclusive_positions(start_mm - half_range_mm, start_mm + half_range_mm, step_mm)
    elif scan_mode == "plus-minus":
        positions = _build_inclusive_positions(start_mm - scan_range_mm, start_mm + scan_range_mm, step_mm)
    else:
        raise ValueError(f"Unsupported scan_mode: {scan_mode!r}")

    return _filter_positions_by_limits(positions, min_position_mm, max_position_mm)


def _validate_config(config: AutofocusConfig) -> None:
    if config.step_mm <= 0:
        raise ValueError("step_mm must be positive.")
    if config.scan_mode not in {"up", "down", "centered", "plus-minus", "absolute"}:
        raise ValueError('scan_mode must be "up", "down", "centered", "plus-minus", or "absolute".')
    if (
        config.min_position_mm is not None
        and config.max_position_mm is not None
        and config.min_position_mm >= config.max_position_mm
    ):
        raise ValueError("min_position_mm must be smaller than max_position_mm.")
    if config.scan_mode == "absolute":
        if config.min_position_mm is None or config.max_position_mm is None:
            raise ValueError("absolute scan mode needs min_position_mm and max_position_mm.")
        absolute_range_mm = config.max_position_mm - config.min_position_mm
        if config.step_mm > absolute_range_mm:
            raise ValueError("step_mm should not be larger than the absolute scan range.")
        if config.reference_position_mm is not None:
            raise ValueError("reference_position_mm is not used with absolute scan mode.")
    else:
        if config.scan_range_mm <= 0:
            raise ValueError("scan_range_mm must be positive.")
        if config.step_mm > config.scan_range_mm:
            raise ValueError("step_mm should not be larger than scan_range_mm.")
    if config.settle_seconds < 0:
        raise ValueError("settle_seconds cannot be negative.")
    if not 0 < config.center_crop_fraction <= 1:
        raise ValueError("center_crop_fraction must be > 0 and <= 1.")
    _validate_focus_roi(config.focus_roi)
    if config.focus_metric not in {"tenengrad", "laplacian"}:
        raise ValueError('focus_metric must be "tenengrad" or "laplacian".')
    if config.camera_retries < 0:
        raise ValueError("camera_retries cannot be negative.")
    if config.camera_retry_seconds < 0:
        raise ValueError("camera_retry_seconds cannot be negative.")


def _build_inclusive_positions(start_mm: float, stop_mm: float, step_mm: float) -> list[float]:
    direction = 1.0 if stop_mm >= start_mm else -1.0
    signed_step = abs(step_mm) * direction
    positions: list[float] = []
    position = start_mm
    tolerance = 1e-12

    if direction > 0:
        while position <= stop_mm + tolerance:
            positions.append(_round_position(position))
            position += signed_step
        if positions[-1] < stop_mm - tolerance:
            positions.append(_round_position(stop_mm))
    else:
        while position >= stop_mm - tolerance:
            positions.append(_round_position(position))
            position += signed_step
        if positions[-1] > stop_mm + tolerance:
            positions.append(_round_position(stop_mm))

    return positions


def _capture_with_retries(camera, camera_retries: int, camera_retry_seconds: float):
    last_error: RuntimeError | None = None

    for attempt in range(camera_retries + 1):
        try:
            return camera.capture()
        except RuntimeError as exc:
            last_error = exc
            if attempt >= camera_retries:
                break

            print(
                "Camera capture failed; "
                f"retrying {attempt + 1}/{camera_retries} after {camera_retry_seconds:.1f} s. "
                f"Reason: {exc}"
            )
            time.sleep(camera_retry_seconds)

    raise last_error or RuntimeError("Camera capture failed.")


def _filter_positions_by_limits(
    positions: list[float],
    min_position_mm: float | None,
    max_position_mm: float | None,
) -> list[float]:
    filtered_positions: list[float] = []

    for position in positions:
        if min_position_mm is not None and position < min_position_mm:
            continue
        if max_position_mm is not None and position > max_position_mm:
            continue
        filtered_positions.append(position)

    if not filtered_positions:
        raise ValueError(
            "No autofocus scan positions are inside the configured limits. "
            "Change --scan-mode, --scan-range-mm, --min-position-mm, or --max-position-mm."
        )

    return filtered_positions


def _round_position(position_mm: float) -> float:
    return round(position_mm, 9)


def _to_grayscale_float(frame) -> np.ndarray:
    image = np.asarray(frame)
    if image.ndim == 2:
        return image.astype(np.float64)
    if image.ndim == 3 and image.shape[2] >= 3:
        red = image[:, :, 0].astype(np.float64)
        green = image[:, :, 1].astype(np.float64)
        blue = image[:, :, 2].astype(np.float64)
        return 0.299 * red + 0.587 * green + 0.114 * blue
    raise ValueError(f"Unsupported image shape for focus score: {image.shape}")


def _image_stats(
    frame,
    center_crop_fraction: float,
    focus_roi: tuple[float, float, float, float] | None = None,
) -> tuple[float, float, float]:
    image = np.asarray(frame)
    gray = _to_grayscale_float(image)
    gray = _crop_focus_region(gray, center_crop_fraction, focus_roi)

    mean_intensity = float(np.mean(gray))
    max_intensity = float(np.max(gray))
    saturated_fraction = 0.0

    if np.issubdtype(image.dtype, np.integer):
        dtype_max = np.iinfo(image.dtype).max
        saturated_fraction = float(np.mean(gray >= dtype_max))

    return mean_intensity, max_intensity, saturated_fraction


def _crop_focus_region(
    image: np.ndarray,
    center_crop_fraction: float,
    focus_roi: tuple[float, float, float, float] | None,
) -> np.ndarray:
    if focus_roi is not None:
        return _roi_crop(image, focus_roi)
    return _center_crop(image, center_crop_fraction)


def _center_crop(image: np.ndarray, fraction: float) -> np.ndarray:
    if fraction >= 1.0:
        return image

    height, width = image.shape[:2]
    crop_height = max(3, int(height * fraction))
    crop_width = max(3, int(width * fraction))
    y0 = (height - crop_height) // 2
    x0 = (width - crop_width) // 2
    return image[y0 : y0 + crop_height, x0 : x0 + crop_width]


def _roi_crop(image: np.ndarray, focus_roi: tuple[float, float, float, float]) -> np.ndarray:
    _validate_focus_roi(focus_roi)

    height, width = image.shape[:2]
    x, y, roi_width, roi_height = focus_roi
    x0 = int(round(x * width))
    y0 = int(round(y * height))
    crop_width = max(3, int(round(roi_width * width)))
    crop_height = max(3, int(round(roi_height * height)))
    x0 = min(max(0, x0), max(0, width - crop_width))
    y0 = min(max(0, y0), max(0, height - crop_height))

    cropped = image[y0 : y0 + crop_height, x0 : x0 + crop_width]
    if cropped.shape[0] < 3 or cropped.shape[1] < 3:
        raise ValueError("focus_roi is too small for this image.")
    return cropped


def _validate_focus_roi(focus_roi: tuple[float, float, float, float] | None) -> None:
    if focus_roi is None:
        return
    if len(focus_roi) != 4:
        raise ValueError("focus_roi must contain four numbers: x y width height.")

    x, y, width, height = focus_roi
    if x < 0 or y < 0:
        raise ValueError("focus_roi x and y must be >= 0.")
    if width <= 0 or height <= 0:
        raise ValueError("focus_roi width and height must be > 0.")
    if x + width > 1 or y + height > 1:
        raise ValueError("focus_roi must stay inside the image; x+width and y+height must be <= 1.")


def _focus_image_path(output_dir: Path, index: int, position_mm: float) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    position_text = f"{position_mm:.6f}".replace("-", "minus_").replace(".", "p")
    return output_dir / f"focus_{index:03d}_pos_{position_text}_{timestamp}.tiff"


def _best_focus_image_path(output_dir: Path, position_mm: float) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    position_text = f"{position_mm:.6f}".replace("-", "minus_").replace(".", "p")
    return output_dir / f"best_focus_pos_{position_text}_{timestamp}.tiff"


def _write_report(
    report_path: Path,
    start_position: float,
    best_point: FocusPoint,
    points: list[FocusPoint],
    config: AutofocusConfig,
) -> None:
    with report_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow(["focus_metric", config.focus_metric])
        writer.writerow(["scan_mode", config.scan_mode])
        writer.writerow(["scan_range_mm", f"{config.scan_range_mm:.9f}"])
        writer.writerow(["step_mm", f"{config.step_mm:.9f}"])
        writer.writerow(["reference_position_mm", _optional_float_text(config.reference_position_mm)])
        writer.writerow(["min_position_mm", _optional_float_text(config.min_position_mm)])
        writer.writerow(["max_position_mm", _optional_float_text(config.max_position_mm)])
        writer.writerow(["center_crop_fraction", f"{config.center_crop_fraction:.9f}"])
        writer.writerow(["focus_roi", _focus_roi_text(config.focus_roi)])
        writer.writerow(["start_position_mm", f"{start_position:.9f}"])
        writer.writerow(["best_position_mm", f"{best_point.position_mm:.9f}"])
        writer.writerow(["best_score", f"{best_point.score:.9f}"])
        writer.writerow([])
        writer.writerow(
            [
                "index",
                "position_mm",
                "focus_score",
                "mean_intensity",
                "max_intensity",
                "saturated_fraction",
                "is_best",
                "image_path",
            ]
        )

        for point in points:
            writer.writerow(
                [
                    point.index,
                    f"{point.position_mm:.9f}",
                    f"{point.score:.9f}",
                    f"{point.mean_intensity:.9f}",
                    f"{point.max_intensity:.9f}",
                    f"{point.saturated_fraction:.9f}",
                    point.index == best_point.index,
                    str(point.image_path) if point.image_path else "",
                ]
            )


def _optional_float_text(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.9f}"


def _focus_roi_text(focus_roi: tuple[float, float, float, float] | None) -> str:
    if focus_roi is None:
        return ""
    return " ".join(f"{value:.9f}" for value in focus_roi)
