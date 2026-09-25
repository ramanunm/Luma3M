# Luma3M

Luma3M is a Python control platform for multimodal microscopy. It coordinates LED and laser illumination, camera acquisition, stage-based autofocus, and optional spectroscopy through a single command-line interface.

The current implementation supports sequential switching between LED and laser acquisition, with separate camera profiles and configurable timing for each illumination path. Switching speed depends on the controller, camera exposure, settling delays, and enabled acquisition steps; this repository does not specify a measured switching latency.

## Hardware and software

- Windows with 64-bit Python 3.11.
- A ZWO ASI camera with its vendor driver and SDK.
- An Arduino Uno light controller with compatible serial firmware.
- A Thorlabs MLJ050 stage and Kinesis for stage motion, autofocus, and the current alternating acquisition workflow.
- An ASEQ spectrometer and its 64-bit vendor DLL for spectroscopy.

Only the devices required by the selected command need to be connected. Vendor SDKs, Arduino firmware, and device-specific calibration files are not included.

## Getting started

From PowerShell:

```powershell
git clone https://github.com/ramanunm/Luma3M.git
cd Luma3M
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

Follow the [installation guide](docs/INSTALLATION.md) to install hardware dependencies and configure your devices before running acquisition commands. The bundled configuration contains setup-specific defaults and must be reviewed for your system.

```powershell
.\run.ps1 doctor
.\run.ps1 camera-info
.\run.ps1 image --light-image led --output .\captures\led.tiff
```

Run commands from the repository root. `run.ps1` uses the local `.venv`; alternatively, use `.\.venv\Scripts\python.exe -m microscope_control`. Installation also provides the `microscopy` entry point inside that environment.

## Commands

| Command | Purpose |
| --- | --- |
| `doctor` | Inspect Python, SDK paths, serial ports, output drive, and camera availability without moving the stage or switching illumination. |
| `camera-info` | Inspect the connected camera and available SDK controls. |
| `stage` | Move or home the MLJ050 stage. |
| `light` | Select illumination or run a timed light sequence. |
| `spectrum` | Acquire an ASEQ spectrum. |
| `image` | Capture an image under LED or laser illumination. |
| `focus` | Run stage-based autofocus under a selected illumination path. |
| `alternate` | Repeatedly switch illumination and acquire images, with optional spectroscopy and autofocus. |

Use `.\run.ps1 <command> --help` for all available options. Some command-line help and validation messages are currently in Chinese.

### Single-image acquisition

```powershell
.\run.ps1 image --light-image led --exposure-ms 100 --image-type raw16 --output .\captures\led.tiff
.\run.ps1 image --light-image laser --reference-axes --output .\captures\focus_roi.tiff
```

`--reference-axes` creates an annotated image with normalized coordinates for selecting an autofocus region. Use an unannotated image for quantitative analysis.

### Alternating acquisition

The current `alternate` command connects to the stage even with `--focus off`; a configured MLJ050 is still required. After completing the [hardware checks](docs/HARDWARE_CHECKS.md), start with a short acquisition with autofocus and spectroscopy disabled:

```powershell
.\run.ps1 alternate `
  --lights both --duration-m 0.2 `
  --focus off --spectrum off `
  --cycle-interval-s 1 `
  --light-led-on-s 1 --light-led-off-s 1 `
  --light-laser-on-s 1 --light-laser-off-s 1 `
  --led-exposure-ms 100 --led-image-type raw16 `
  --laser-exposure-ms 100 --laser-image-type raw16 `
  --output-dir .\captures\alternate
```

Each cycle selects LED illumination, waits for settling, captures an image, holds illumination, switches it off, and waits before repeating the sequence for laser illumination. Spectroscopy, when enabled, is acquired during the laser phase. `--cycle-interval-s` adds a delay after the completed cycle; it does not set the total cycle period.

LED and laser profiles have independent exposure, gain, white balance, and image format options, such as `--led-gain` and `--laser-gain`. Profile values from the configuration can override common camera settings.

Enable spectroscopy with `--spectrum on` after configuring the spectrometer. Enable periodic autofocus with `--focus on --focus-interval 100`; this sets an interval of 100 completed cycles. Autofocus options in this workflow use the `--af-` prefix, for example `--af-focus-roi` and `--af-scan-range-mm`.

### Autofocus

Choose a motion range that is appropriate for your instrument before running:

```powershell
.\run.ps1 focus `
  --focus-light led --focus-metric tenengrad `
  --scan-mode plus-minus --scan-range-mm 0.02 --step-mm 0.005 `
  --focus-roi 0.25 0.25 0.50 0.50 `
  --save-frames clear --output-dir .\captures\focus
```

`--focus-roi X Y W H` uses normalized image coordinates. Focus metrics are `tenengrad` and `laplacian`. Use `--save-frames all` to keep all scan frames, `clear` to keep the sharpest frame, or `--no-save-frames` to omit images. Configure `--min-position-mm` and `--max-position-mm` to match the usable travel range.

### Individual devices

```powershell
.\run.ps1 stage --move-mode up --move-range-mm 0.001
.\run.ps1 stage --move-mode down --move-range-mm 0.001
.\run.ps1 light --led-on-s 1
.\run.ps1 light --laser-on-s 1
.\run.ps1 spectrum --spectrum-exposure-us 10000 --spectrum-averages 3 --output .\captures\spectrum.csv
```

`up` and `down` mean positive and negative stage displacement. Confirm their physical direction on your instrument. An untimed light command such as `light --led on` waits for Enter before shutting off illumination.

## Camera settings

| Option | Meaning |
| --- | --- |
| `--exposure-us` or `--exposure-ms` | Exposure in microseconds or milliseconds; mutually exclusive. Both accept `auto`. |
| `--gain` | Integer gain or `auto`. |
| `--image-type` | `raw8`, `raw16`, `rgb24`, or `y8`. |
| `--wb-r`, `--wb-b` | Red and blue white balance. |
| `--roi-width`, `--roi-height` | Acquisition dimensions, subject to camera and SDK constraints. |
| `--software-binning` | Software binning factor. |
| `--high-speed`, `--bandwidth` | Camera transfer settings. |
| `--cooler`, `--target-temperature-c` | Cooling controls on supported models. |
| `--camera-control NAME=VALUE` | Additional model-specific control; repeat for multiple controls. |

Use `camera-info` to check supported controls and ranges. `raw16` stores raw data in a 16-bit container; actual sensor bit depth depends on the camera. `rgb24` provides an 8-bit color image.

## Repository layout

```text
microscope_control/
  devices/       Hardware communication
  functions/     Individual device operations
  workflows/     Imaging, autofocus, and alternating acquisition
  cli.py         Command-line entry point
  settings.py    Configuration loading
config/          Instrument configuration
drivers/aseq/    Instructions for locally supplied ASEQ files
docs/            Installation and hardware checks
```

Acquisition data, virtual environments, vendor binaries, and calibration files are excluded from version control. Software attempts to turn illumination off during cleanup; verify interruption behavior on the actual instrument before extended operation.
