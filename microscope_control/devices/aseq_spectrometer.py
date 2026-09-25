from __future__ import annotations

import ctypes
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from microscope_control.devices.base import Device, DeviceNotConnectedError


class AseqSpectrometerError(RuntimeError):
    """Raised when the ASEQ spectrometer DLL returns an error."""


@dataclass(slots=True)
class AseqSpectrometerConfig:
    """Settings for the ASEQ 16-bit ADC spectrometer DLL."""

    dll_path: Path | None = None
    serial_number: str | None = None
    device_index: int = 0
    start_element: int = 0
    end_element: int = 3647
    reduction_mode: int = 0
    dummy_start_pixels: int = 32
    spectrum_pixels: int = 3653
    acquisition_timeout_seconds: float = 10.0
    poll_interval_seconds: float = 0.025
    flash_size_bytes: int = 0x20000
    flash_read_chunk_bytes: int = 600
    flash_read_retries: int = 3
    flash_read_retry_seconds: float = 0.25
    connect_retries: int = 3
    connect_retry_seconds: float = 1.0


@dataclass(slots=True)
class Spectrum:
    """One acquired spectrum."""

    intensities: np.ndarray
    raw_frame: np.ndarray
    exposure_us: int
    averages: int


class AseqSpectrometer(Device):
    """ASEQ spectrometer controlled through spectrlib_shared_64bits.dll."""

    def __init__(self, config: AseqSpectrometerConfig | None = None):
        self.config = config or AseqSpectrometerConfig()
        self._dll = None
        self._connected = False
        self._frame_pixels = 0

    def connect(self) -> "AseqSpectrometer":
        if self._connected:
            return self

        self._dll = _load_dll(self.config.dll_path)
        _configure_dll_functions(self._dll)

        error_code, function_name = self._connect_device_with_retries()
        _raise_if_error(error_code, function_name)

        self._connected = True
        self.set_frame_format(
            self.config.start_element,
            self.config.end_element,
            self.config.reduction_mode,
        )
        return self

    def _connect_device_with_retries(self) -> tuple[int, str]:
        last_error_code = 0
        function_name = "connectToDeviceByIndex"

        for attempt in range(self.config.connect_retries + 1):
            self._disconnect_dll_safely()
            error_code, function_name = self._connect_device_once()
            if error_code == 0:
                return error_code, function_name

            last_error_code = error_code
            if attempt < self.config.connect_retries:
                time.sleep(self.config.connect_retry_seconds)

        return last_error_code, function_name

    def _connect_device_once(self) -> tuple[int, str]:
        if self._dll is None:
            raise DeviceNotConnectedError("ASEQ DLL is not loaded.")

        error_code = int(self._dll.connectToDeviceByIndex(ctypes.c_uint(self.config.device_index)))
        return error_code, "connectToDeviceByIndex"

    def _disconnect_dll_safely(self) -> None:
        if self._dll is None:
            return
        try:
            self._dll.disconnectDevice()
        except OSError:
            pass

    def disconnect(self) -> None:
        if not self._connected or self._dll is None:
            return
        try:
            self._dll.disconnectDevice()
        finally:
            self._connected = False

    def __enter__(self) -> "AseqSpectrometer":
        return self.connect()

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.disconnect()

    @property
    def dll(self):
        if not self._connected or self._dll is None:
            raise DeviceNotConnectedError("ASEQ spectrometer is not connected.")
        return self._dll

    @staticmethod
    def device_count(dll_path: str | Path | None = None) -> int:
        dll = _load_dll(Path(dll_path) if dll_path else None)
        _configure_dll_functions(dll)
        return int(dll.getDeviceCount())

    def set_frame_format(self, start_element: int, end_element: int, reduction_mode: int = 0) -> int:
        frame_pixels = ctypes.c_ushort()
        error_code = self.dll.setFrameFormat(
            ctypes.c_ushort(start_element),
            ctypes.c_ushort(end_element),
            ctypes.c_ubyte(reduction_mode),
            ctypes.byref(frame_pixels),
        )
        _raise_if_error(error_code, "setFrameFormat")
        self._frame_pixels = int(frame_pixels.value)
        return self._frame_pixels

    def set_acquisition_parameters(
        self,
        averages: int = 1,
        blank_scans: int = 0,
        scan_mode: int = 3,
        exposure_us: int = 10_000,
    ) -> None:
        if exposure_us <= 0:
            raise ValueError("exposure_us must be positive.")
        if averages <= 0:
            raise ValueError("averages must be positive.")
        if blank_scans < 0:
            raise ValueError("blank_scans cannot be negative.")

        exposure_units = _exposure_us_to_device_units(exposure_us)
        error_code = self.dll.setAcquisitionParameters(
            ctypes.c_ushort(averages),
            ctypes.c_ushort(blank_scans),
            ctypes.c_ubyte(scan_mode),
            ctypes.c_uint(exposure_units),
        )
        _raise_if_error(error_code, "setAcquisitionParameters")

    def capture_spectrum(
        self,
        exposure_us: int = 10_000,
        averages: int = 1,
        blank_scans: int = 0,
        scan_mode: int = 3,
    ) -> Spectrum:
        """Acquire one spectrum and return cropped intensities plus raw frame."""

        self.set_acquisition_parameters(
            averages=averages,
            blank_scans=blank_scans,
            scan_mode=scan_mode,
            exposure_us=exposure_us,
        )
        self._wait_for_frame()
        raw_frame = self._read_frame()
        intensities = self._crop_spectrum(raw_frame)
        return Spectrum(
            intensities=intensities,
            raw_frame=raw_frame,
            exposure_us=exposure_us,
            averages=averages,
        )

    def read_flash(
        self,
        offset: int = 0,
        bytes_to_read: int | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
    ) -> bytes:
        """Read bytes from the spectrometer user flash memory.

        ASEQ stores optional calibration information in this 128 kB flash area.
        Reading is safe; writing or erasing flash is deliberately not exposed here.
        """

        total_bytes = self.config.flash_size_bytes
        if bytes_to_read is None:
            bytes_to_read = total_bytes - offset
        if offset < 0:
            raise ValueError("offset cannot be negative.")
        if bytes_to_read <= 0:
            raise ValueError("bytes_to_read must be positive.")
        if offset + bytes_to_read > total_bytes:
            raise ValueError(f"Cannot read past ASEQ flash size: {total_bytes} bytes.")

        chunks: list[bytes] = []
        remaining = bytes_to_read
        current_offset = offset
        chunk_size = self.config.flash_read_chunk_bytes
        if chunk_size <= 0:
            raise ValueError("flash_read_chunk_bytes must be positive.")

        while remaining > 0:
            current_size = min(chunk_size, remaining)
            buffer = self._read_flash_chunk(current_offset, current_size)
            chunks.append(bytes(buffer))
            current_offset += current_size
            remaining -= current_size
            if progress_callback is not None:
                progress_callback(current_offset - offset, bytes_to_read)

        return b"".join(chunks)

    def _read_flash_chunk(self, offset: int, bytes_to_read: int):
        last_error_code = 0
        for attempt in range(self.config.flash_read_retries + 1):
            buffer_type = ctypes.c_ubyte * bytes_to_read
            buffer = buffer_type()
            error_code = self.dll.readFlash(buffer, ctypes.c_uint(offset), ctypes.c_uint(bytes_to_read))
            if int(error_code) == 0:
                return buffer

            last_error_code = int(error_code)
            if attempt < self.config.flash_read_retries:
                time.sleep(self.config.flash_read_retry_seconds)

        _raise_if_error(last_error_code, "readFlash")

    def _wait_for_frame(self) -> None:
        deadline = time.monotonic() + self.config.acquisition_timeout_seconds
        status_flags = ctypes.c_ubyte()
        frames_in_memory = ctypes.c_ushort()

        while True:
            error_code = self.dll.getStatus(ctypes.byref(status_flags), ctypes.byref(frames_in_memory))
            _raise_if_error(error_code, "getStatus")
            if frames_in_memory.value > 0:
                return
            if time.monotonic() > deadline:
                raise TimeoutError("Timed out waiting for ASEQ spectrum frame.")
            time.sleep(self.config.poll_interval_seconds)

    def _read_frame(self) -> np.ndarray:
        if self._frame_pixels <= 0:
            self.set_frame_format(
                self.config.start_element,
                self.config.end_element,
                self.config.reduction_mode,
            )

        buffer_type = ctypes.c_ushort * self._frame_pixels
        buffer = buffer_type()
        error_code = self.dll.getFrame(buffer, ctypes.c_ushort(0xFFFF))
        _raise_if_error(error_code, "getFrame")
        return np.ctypeslib.as_array(buffer).copy()

    def _crop_spectrum(self, raw_frame: np.ndarray) -> np.ndarray:
        start = self.config.dummy_start_pixels
        stop = start + self.config.spectrum_pixels
        if stop > len(raw_frame):
            raise RuntimeError(
                f"ASEQ raw frame has {len(raw_frame)} pixels, but crop requires {stop} pixels. "
                "Adjust dummy_start_pixels or spectrum_pixels."
            )
        return np.asarray(raw_frame[start:stop], dtype=np.uint16)


def save_spectrum_csv(
    spectrum: Spectrum,
    output_path: str | Path,
    wavelengths_nm: np.ndarray | None = None,
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8", newline="") as file:
        if wavelengths_nm is None:
            file.write("pixel,intensity\n")
            for pixel, intensity in enumerate(spectrum.intensities):
                file.write(f"{pixel},{int(intensity)}\n")
        else:
            if len(wavelengths_nm) != len(spectrum.intensities):
                raise ValueError("wavelengths_nm length must match spectrum intensity length.")
            file.write("pixel,wavelength_nm,intensity\n")
            for pixel, (wavelength, intensity) in enumerate(zip(wavelengths_nm, spectrum.intensities)):
                file.write(f"{pixel},{float(wavelength):.9f},{int(intensity)}\n")

    return output


def load_wavelengths(calibration_file: str | Path, expected_pixels: int = 3653) -> np.ndarray:
    """Load a plain text wavelength calibration file.

    This accepts either:
    - a wavelength-only text file with one wavelength per CCD element, or
    - a full ASEQ calibration file, where wavelength values are embedded after
      the absolute irradiation coefficient.
    """

    with Path(calibration_file).open("r", encoding="utf-8", errors="ignore") as file:
        values = _numeric_values_from_text(file.read())
    return extract_wavelengths_from_values(values, expected_pixels=expected_pixels)


def save_wavelengths(wavelengths_nm: np.ndarray, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8", newline="") as file:
        for wavelength in wavelengths_nm:
            file.write(f"{float(wavelength):.9f}\n")
    return output


def extract_wavelengths_from_calibration_bytes(
    calibration_bytes: bytes,
    expected_pixels: int = 3653,
) -> np.ndarray:
    text = decode_calibration_text(calibration_bytes)
    return extract_wavelengths_from_text(text, expected_pixels=expected_pixels)


def extract_wavelengths_from_text(text: str, expected_pixels: int = 3653) -> np.ndarray:
    return extract_wavelengths_from_values(_numeric_values_from_text(text), expected_pixels=expected_pixels)


def extract_wavelengths_from_values(values: list[float], expected_pixels: int = 3653) -> np.ndarray:
    if not values:
        raise ValueError("No numeric values were found in the calibration text.")
    if len(values) == expected_pixels:
        return np.asarray(values, dtype=np.float64)

    candidates: list[np.ndarray] = []
    max_start = min(64, len(values) - expected_pixels + 1)
    for start in range(max_start):
        candidate = np.asarray(values[start : start + expected_pixels], dtype=np.float64)
        if _looks_like_wavelength_table(candidate):
            candidates.append(candidate)

    if candidates:
        return candidates[0]

    raise ValueError(
        f"Found {len(values)} numeric values, but could not identify a {expected_pixels}-pixel "
        "ASEQ wavelength table. If this is a full calibration file, send me the first 30 text lines."
    )


def decode_calibration_text(calibration_bytes: bytes) -> str:
    """Decode raw ASEQ flash bytes into readable calibration text."""

    # Empty flash commonly reads as 0xFF. Keep only the meaningful prefix if the
    # rest of the flash is blank.
    meaningful = calibration_bytes.rstrip(b"\xff\x00\r\n\t ")
    if not meaningful:
        return ""
    for encoding in ("utf-8", "cp1252", "latin-1"):
        try:
            return meaningful.decode(encoding, errors="ignore")
        except UnicodeDecodeError:
            continue
    return meaningful.decode("latin-1", errors="ignore")


def _numeric_values_from_text(text: str) -> list[float]:
    values: list[float] = []
    for line in text.splitlines():
        normalized = line.strip().replace(",", " ").replace(";", " ")
        if not normalized:
            continue
        for part in normalized.split():
            try:
                values.append(float(part))
                break
            except ValueError:
                continue
    return values


def _looks_like_wavelength_table(values: np.ndarray) -> bool:
    if len(values) == 0 or not np.all(np.isfinite(values)):
        return False
    if float(np.min(values)) < 100.0 or float(np.max(values)) > 2500.0:
        return False
    if abs(float(values[-1] - values[0])) < 10.0:
        return False

    diffs = np.diff(values)
    nonzero = diffs[np.abs(diffs) > 1e-9]
    if len(nonzero) == 0:
        return False
    positive_fraction = float(np.mean(nonzero > 0))
    negative_fraction = float(np.mean(nonzero < 0))
    return positive_fraction > 0.95 or negative_fraction > 0.95


def _load_dll(dll_path: Path | None):
    path = _resolve_dll_path(dll_path)
    return ctypes.CDLL(str(path))


def _resolve_dll_path(dll_path: Path | None) -> Path:
    candidates: list[Path] = []
    if dll_path is not None:
        candidates.append(Path(dll_path))
    project_root = Path(__file__).resolve().parents[2]
    candidates.extend(
        [
            project_root / "drivers" / "aseq" / "spectrlib_shared_64bits.dll",
            project_root / "spectrlib_shared_64bits.dll",
            Path.cwd() / "spectrlib_shared_64bits.dll",
        ]
    )

    for candidate in candidates:
        if candidate.exists():
            return candidate

    searched = "\n".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        "Could not find spectrlib_shared_64bits.dll. "
        "Pass --dll-path or copy the DLL to drivers\\aseq\\.\n"
        f"Searched:\n{searched}"
    )


def _configure_dll_functions(dll) -> None:
    dll.getDeviceCount.argtypes = []
    dll.getDeviceCount.restype = ctypes.c_int

    dll.connectToDeviceByIndex.argtypes = [ctypes.c_uint]
    dll.connectToDeviceByIndex.restype = ctypes.c_int

    dll.disconnectDevice.argtypes = []
    dll.disconnectDevice.restype = None

    dll.setAcquisitionParameters.argtypes = [
        ctypes.c_ushort,
        ctypes.c_ushort,
        ctypes.c_ubyte,
        ctypes.c_uint,
    ]
    dll.setAcquisitionParameters.restype = ctypes.c_int

    dll.setFrameFormat.argtypes = [
        ctypes.c_ushort,
        ctypes.c_ushort,
        ctypes.c_ubyte,
        ctypes.POINTER(ctypes.c_ushort),
    ]
    dll.setFrameFormat.restype = ctypes.c_int

    dll.getStatus.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.POINTER(ctypes.c_ushort)]
    dll.getStatus.restype = ctypes.c_int

    dll.getFrame.argtypes = [ctypes.POINTER(ctypes.c_ushort), ctypes.c_ushort]
    dll.getFrame.restype = ctypes.c_int

    dll.readFlash.argtypes = [ctypes.POINTER(ctypes.c_ubyte), ctypes.c_uint, ctypes.c_uint]
    dll.readFlash.restype = ctypes.c_int


def _exposure_us_to_device_units(exposure_us: int) -> int:
    # ASEQ documentation says exposure time is expressed in 10 us units.
    return max(1, int(round(exposure_us / 10)))


def _raise_if_error(error_code: int, function_name: str) -> None:
    if int(error_code) == 0:
        return
    message = _ERROR_MESSAGES.get(int(error_code), "Unknown ASEQ DLL error")
    raise AseqSpectrometerError(f"{function_name} failed with error {error_code}: {message}")


_ERROR_MESSAGES = {
    500: "CONNECT_ERROR_WRONG_ID",
    501: "CONNECT_ERROR_NOT_FOUND",
    502: "CONNECT_ERROR_FAILED",
    503: "DEVICE_NOT_INITIALIZED",
    504: "WRITING_PROCESS_FAILED",
    505: "READING_PROCESS_FAILED",
    506: "WRONG_ANSWER",
    507: "GET_FRAME_REMAINING_PACKETS_ERROR",
    508: "NUM_OF_PACKETS_IN_FRAME_ERROR",
    509: "INPUT_PARAMETER_NOT_INITIALIZED",
    510: "READ_FLASH_REMAINING_PACKETS_ERROR",
}
