# ASEQ spectrometer files

Supply these files locally when using spectroscopy:

| File | Purpose |
| --- | --- |
| `spectrlib_shared_64bits.dll` | The 64-bit ASEQ vendor library required for spectrometer communication. |
| `aseq_wavelengths_latest.txt` | Optional wavelength calibration for the connected device. |

Obtain the library from your device's vendor distribution and use a calibration file for the same spectrometer. These files are excluded from version control and are not distributed with Luma3M.

Place them in this directory or configure their locations through `paths.aseq_dll` and `paths.aseq_calibration` in your instrument TOML file. Command-line overrides are `--spectrum-dll-path` and `--spectrum-calibration-file`.

To deliberately acquire without wavelength calibration, pass `--no-spectrum-calibration`; output then uses pixel indexes rather than calibrated wavelengths. To run alternating image acquisition without a spectrometer, use `--spectrum off`.

See the [installation guide](../../docs/INSTALLATION.md) for the rest of the hardware setup.
