# Installation and configuration

## 1. Install the Python environment

Use Windows and 64-bit Python 3.11. From the repository root:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
```

The package installs NumPy, pyserial, pythonnet, pyzwoasi, and tifffile. To install the optional OpenCV dependency:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[preview]'
```

The explicit environment setup above is recommended for a new installation. `setup_work_computer.ps1` and the fallback in `run.ps1` retain compatibility with an earlier laboratory deployment; a fresh installation does not need that deployment or its directory layout.

## 2. Install hardware dependencies

- **ZWO camera:** Install the vendor driver and ASI SDK, and make the SDK available to `pyzwoasi`.
- **Thorlabs stage:** Install Kinesis and configure its installation directory and your MLJ050 serial number.
- **Arduino light controller:** Install firmware compatible with the protocol below and configure its serial port and baud rate. Firmware and wiring instructions are not supplied in this repository.
- **ASEQ spectrometer:** Obtain the 64-bit vendor DLL and the calibration for your device. See the [ASEQ instructions](../drivers/aseq/README.md).

Close other applications that hold device connections, including camera utilities, the Kinesis GUI, and Arduino Serial Monitor, before acquisition.

### Arduino protocol

The driver sends newline-terminated ASCII commands and expects a response starting with `OK`:

| Command | Expected response | Purpose |
| --- | --- | --- |
| `PING` | `OK` | Check communication. |
| `LED` | `OK LED` | Select LED illumination. |
| `LASER` | `OK LASER` | Select laser illumination. |
| `OFF` | `OK OFF` | Turn illumination off. |

The default baud rate is 9600. Confirm that the firmware and electrical connections implement these operations for your instrument.

## 3. Configure the instrument

The default configuration is [config/work_computer.toml](../config/work_computer.toml). Review these values before use:

| Section | Settings to review |
| --- | --- |
| `paths` | Writable output directory, Kinesis directory, ASEQ DLL, and calibration file. |
| `devices` | Camera index, stage serial number, Arduino port and baud rate, spectrometer index. |
| `camera` | Common exposure, gain, and image type. |
| `led`, `laser` | Per-illumination camera profiles used by `alternate`. |
| `acquisition` | Duration, cycle delay, illumination timing, autofocus interval, and spectroscopy setting. |

Bundled values describe an existing setup and are not automatic device detection. Replace the stage identifier and output path with values appropriate for your instrument. Device indexes are zero-based.

For a separate configuration, copy the complete TOML file to a location outside the repository, edit it, and select it in the current PowerShell session:

```powershell
$env:MICROSCOPY_CONFIG = Join-Path $env:USERPROFILE 'luma3m.local.toml'
```

Create that file before running the command-line tools. Relative paths inside the TOML file resolve against the repository root, not the configuration file's directory. For example, `output_root = "captures"` selects the repository's ignored `captures` directory. Configuration is loaded when the Python process starts.

## 4. Check the installation

```powershell
.\run.ps1 doctor
.\run.ps1 camera-info
```

`doctor` checks environment paths, serial port presence, and camera availability. It does not test stage movement, Arduino command responses, spectrometer acquisition, or optical alignment. It also reports missing ASEQ files when spectroscopy is not in use; interpret each result for the devices needed by your workflow.

Complete the [hardware checks](HARDWARE_CHECKS.md) before extended acquisition. Use `--spectrum off` to omit spectroscopy and `--focus off` to disable autofocus during initial checks. The current `alternate` command still requires a connected MLJ050 stage when autofocus is disabled.

## Troubleshooting

- **Python environment not found:** Create `.venv` using the installation commands above.
- **PowerShell script execution blocked:** Invoke the environment directly: `.\.venv\Scripts\python.exe -m microscope_control doctor`.
- **Serial port unavailable:** Check the port reported by `doctor`, update the configuration, and close other serial applications.
- **Camera or SDK unavailable:** Check vendor driver installation, SDK discovery, matching 64-bit libraries, and competing device connections.
- **Output cannot be saved:** Choose an existing, writable drive or a repository-relative output directory in your configuration.
- **Spectrometer calibration mismatch:** Use a calibration file for the connected device, or explicitly choose uncalibrated pixel-index output with `--no-spectrum-calibration`.

For a syntax-only source check without connecting hardware:

```powershell
.\.venv\Scripts\python.exe -m compileall -q microscope_control
```

This does not validate hardware operation. The repository currently does not include an automated test suite.
