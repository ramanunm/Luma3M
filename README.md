# Luma3M

A multimodal microscopy control platform with programmable switching between LED and laser acquisition, independent imaging profiles, stage-based autofocus, and optional spectroscopy.

The current hardware integration uses ZWO ASI, Arduino, Thorlabs MLJ050, and ASEQ on Windows with 64-bit Python 3.11 and the corresponding vendor SDKs.

## Setup

```powershell
pip install -e .
```

Instrument connections, SDK paths, acquisition profiles, and output settings are defined in [config/work_computer.toml](config/work_computer.toml). Replace the instrument-specific defaults before use, or select a separate configuration with `MICROSCOPY_CONFIG`. Relative configuration paths resolve against the repository root.

Vendor binaries, controller firmware, and device calibration are supplied separately. [ASEQ file locations](drivers/aseq/README.md).

## Acquisition

```powershell
microscopy image --light-image led
microscopy focus --focus-light led
microscopy alternate --lights both --duration-m 60 --focus on --spectrum on
```

`python -m microscope_control` provides the same entry point. Device operations and diagnostics are available through `stage`, `light`, `spectrum`, `camera-info`, and `doctor`; use `<command> --help` for parameters.

## Workflow conventions

- `alternate` acquires sequentially under LED and laser illumination. Each path has its own camera profile; spectroscopy is acquired during the laser phase.
- `--cycle-interval-s` is a post-cycle delay. Exposure, settling, and acquisition determine the full cycle time.
- `--focus-interval` counts completed cycles; autofocus options use the `--af-` prefix within `alternate`.
- The current `alternate` implementation connects to the MLJ050 even when `--focus off` is set.
