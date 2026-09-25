from __future__ import annotations

from pathlib import Path

from microscope_control.devices.aseq_spectrometer import save_spectrum_csv


def capture_spectrum(
    spectrometer,
    output: str | Path,
    *,
    exposure_us: int,
    averages: int = 1,
    blank_scans: int = 0,
    wavelengths_nm=None,
) -> Path:
    spectrum = spectrometer.capture_spectrum(
        exposure_us=exposure_us,
        averages=averages,
        blank_scans=blank_scans,
    )
    return save_spectrum_csv(spectrum, output, wavelengths_nm=wavelengths_nm)

