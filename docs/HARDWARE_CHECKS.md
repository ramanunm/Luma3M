# Hardware checks

Perform these checks after [installation and configuration](INSTALLATION.md), using motion ranges and illumination settings suitable for your instrument.

## Connections

1. Run `.\run.ps1 doctor` and review the configuration path, Python architecture, SDK paths, serial port, and camera availability.
2. Run `.\run.ps1 camera-info` and confirm the camera model, supported formats, and control ranges.
3. Verify the configured stage serial number, Arduino port, and spectrometer index against the connected hardware.

## Individual devices

1. Make a small stage movement, such as `--move-range-mm 0.001`, and verify the physical direction of `up` and `down`. Establish the usable travel limits before autofocus.
2. Briefly select each illumination path and confirm the Arduino command mapping and `OFF` behavior.
3. Save an image in a supported raw format and, for a color camera, `rgb24`. Check dimensions, intensity, and color.
4. If using spectroscopy, acquire a spectrum and check pixel count, exposure, and wavelength calibration.

## Workflows

1. Use an image generated with `--reference-axes` to choose an autofocus ROI.
2. Run autofocus over a small, clear travel range and inspect the selected focus and CSV report.
3. Run a short `alternate` acquisition with `--duration-m 0.2 --focus off --spectrum off`. Inspect images and acquisition records before enabling optional features.
4. Interrupt a short acquisition with Ctrl+C and verify that illumination turns off and device connections are released.
5. Check failure recovery under controlled conditions before extended operation. Software cleanup depends on device communication and is not a hardware interlock.

Keep instrument-specific calibration, serial numbers, acquisition settings, and validation records locally. Repeat the relevant checks after changing hardware, firmware, SDKs, or optical alignment.
