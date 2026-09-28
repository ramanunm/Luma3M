# ASEQ

Provide `spectrlib_shared_64bits.dll` and, for wavelength-calibrated output, the device-specific `aseq_wavelengths_latest.txt` in this directory. Alternative locations are set by `paths.aseq_dll` and `paths.aseq_calibration` in the instrument configuration.

These files are excluded from version control. `--no-spectrum-calibration` selects pixel-index output; `--spectrum off` omits spectroscopy from alternating acquisition.
