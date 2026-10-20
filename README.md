![](resources/figures/CANinoApp_banner_background.png)

# CANino App

## Index

- [Introduction](#introduction)
  - [Supported Devices](#supported-devices)
- [Environment Setup and Usage](#environment-setup-and-usage)
  - [Requirements](#requirements)
  - [Installation](#installation)
  - [Building the Executable](#building-the-executable)
  - [Package Naming](#package-naming)
  - [Repo Structure](#repo-structure)
  - [Logs](#logs)
  - [Tests](#tests)
- [Quick Start](#quick-start)
  - [Transmitting CAN Traffic](#transmitting-can-traffic)
  - [Receiving CAN Traffic](#receiving-can-traffic)
  - [Bus Status](#bus-status)
- [Payloads](#payloads)
  - [Precedence](#precedence)
  - [Payload Scripts](#payload-scripts)
  - [Script Templates](#script-templates)
- [Workspace Files](#workspace-files)
- [License](#license)

# Introduction

CANino App is a Windows desktop application (Python + Qt) to transmit, receive and inspect CAN and CAN FD traffic through a PEAK PCAN-USB adapter. It is built for automotive developers, testers and researchers. With it you can:

- Transmit periodic CAN frames with 11-bit or 29-bit IDs, classic CAN or CAN FD, with constant, scripted or slider-controlled payloads.
- Receive CAN traffic and see, per ID, the payload, count and period statistics (average, min, max, standard deviation), and log it to CSV or record a standard trace (`.trc` PCAN-View, `.asc` / `.blf` Vector, `.log` candump) of every frame on the wire, received and transmitted.
- Load DBC files for message names, signal sliders, live gauges (XMetro) and live time plots (Signal Plot).
- Watch the bus state (OK, error warning, error passive, bus-off) while connected, and connect in listen-only mode to sniff a network without ever driving it.
- Save and load complete workspaces (TX table, scripts, sliders, DBC) as JSON files.
- Flash up to 8 Arduino Uno nodes from the VAGILETTA window (the generated sketch is still a placeholder).

## Supported Devices

- PEAK PCAN-USB adapters on Windows, through the PEAK driver and its PCAN-Basic DLL.
- CAN FD needs an FD-capable PCAN channel; CANino refuses the CAN FD baudrate on classic adapters and, on a classic channel, skips CAN FD rows at Start TX with a warning.

# Environment Setup and Usage

## Requirements

- Windows 10 or 11.
- Python 3.10 or newer (developed and tested with Python 3.13).
- PEAK-System device driver ([download](https://www.peak-system.com/support/downloads/drivers/driver-packages/)). It also installs `PCANBasic.dll`, which CANino App uses: no PCAN adapter works on Windows without it. Without the driver the app still starts, but lists no channels.

## Installation

1. **Clone the repository**

   ```sh
   git clone https://github.com/NickCanino/CANino_app.git
   cd CANino_app
   ```
2. **Create and activate a virtual environment**

   ```sh
   python -m venv .venv
   .\.venv\Scripts\activate
   ```
3. **Install the dependencies** (pinned versions)

   ```sh
   pip install -r requirements.txt
   ```
4. **Run the app** from the repository root

   ```sh
   python main.py
   ```

   The working directory matters: at start-up CANino loads `resources/workspace_config_files/default_config_file.json` from it, if that file exists.

## Building the Executable

1. Install the build tools: `pip install -r requirements-dev.txt` (PyInstaller, ruff, black).
2. Set the release version in the `VERSION` file.
3. Commit your changes, then build:

   ```sh
   pyinstaller CANinoApp_exe_setup.spec
   ```

The spec bundles `VERSION`, the figures, `tools/arduino-cli.exe` and the payload-script templates tracked in git. Untracked files in `resources/script_templates/` are never shipped. Qt parts CANino does not use (software OpenGL, QML/Quick, PDF, network, virtual keyboard) are left out, which takes the exe from about 70 MB to 47 MB.

**Folder build.** With `CANINO_ONEDIR=1` (PowerShell: `$env:CANINO_ONEDIR = "1"`) the spec builds a folder, `dist/CANinoApp_vX.Y.Z_hHASH/`, holding the exe and its `_internal/` files. It starts in about 0.7 s instead of about 2 s and unpacks nothing to `%TEMP%`; distribute the whole folder (for example zipped).

## Package Naming

The built `.exe` appears in the `dist/` folder with the name:

> **CANinoApp_vX.Y.Z_hHASH[-dirty].exe**

1. **X.Y.Z**: major, minor and patch version, from the `VERSION` file.
2. **HASH**: short git commit hash of the source code used for the build.
3. **-dirty**: added when tracked files differ from that commit, so the exe does not contain exactly the named commit.

*Example:* `CANinoApp_v1.5.0_ha1b2c3d.exe`

## Repo Structure

```
CANino_app/
│
├── main.py
├── VERSION
├── CANinoApp_exe_setup.spec    PyInstaller spec
├── requirements.txt            runtime dependencies (pinned)
├── requirements-dev.txt        + build, lint and format tools
├── src/                        application code
├── tests/                      offscreen regression tests
├── tools/
│   └── arduino-cli.exe         used by VAGILETTA
└── resources/
    ├── figures/
    ├── script_templates/       payload-script templates
    ├── tmp/                    replay files for the read-from-file templates
    ├── dbc_files/
    ├── csv_logs/
    └── workspace_config_files/
```

DBC files, workspaces (`*.json`), CSV files and logs are git-ignored.

## Logs

Errors are logged to `%LOCALAPPDATA%\CANinoApp\log`, one file per session. A file is created only when something is logged; the newest 30 files are kept. **Help → Open log folder** opens the folder.

## Tests

From the repository root:

```sh
python -m unittest discover -s tests
```

The tests run Qt offscreen with a simulated PCAN driver: no adapter is needed. Lint and format checks: `ruff check .` and `black --check .` (settings in `pyproject.toml`).

GitHub Actions (`.github/workflows/ci.yml`) runs the same checks and tests on Windows for every push and pull request, and builds the exe as a downloadable artifact. On CI the three tests that measure the machine's timer precision are skipped.

# Quick Start

These workflows apply to both `python main.py` and the built `.exe`.

## Transmitting CAN Traffic

Use the `Interface` selector to pick **PCAN-USB** (a PEAK adapter) or **Virtual** (an in-process loopback bus for demos and tests, no hardware — only this app is on it). The rest works the same for both.


1. Add the CAN frames to transmit to the **Transmitted CAN Frames (TX)** table:

   - a. Load a DBC file with `Load DBC` (many can be found in [opendbc](https://github.com/commaai/opendbc)). Messages already in the table are not added twice, and ID format, CAN FD flag, length and cycle time come from the DBC.
   - b. Load a saved workspace (`File → Load`), or
   - c. Add frames manually with `Add ID`: one form for ID (hex), 29-bit extended ID, CAN FD, DLC, period and name. The form rejects out-of-range IDs and IDs already in the table.
2. Select the adapter in the `Channel` drop-down (press refresh after plugging or unplugging one).
3. Set the `Baudrate` of the network, between 5 kBit/s and 1 MBit/s, or `2 MBit/s (CANFD)` on an FD-capable channel, then press `Connect`.
4. Configure the payloads:

   - a. Edit the hex bytes in the table (double-click the `Payload` cell; a payload that is not exactly DLC hex bytes is refused and the row keeps its own),
   - b. Link a Python script to a row (`Link Script`) or to every row (`Link Global Script`), or
   - c. **With a DBC loaded**, drive one signal of a frame with a slider (`Add Slider`); a signal with a value table (enum) gets a drop-down of its named values instead of a slider.
5. Set each row's `Period (ms)` (double-click the cell, 1–10000 ms), then press `Start TX`. Extended IDs are shown with 8 hex digits (`0x18FF0001`, `0x00000123`), standard IDs with 3 (`0x123`).

> Rows can be added, deleted, enabled or disabled, and periods changed, while transmitting: only the affected row changes, the others keep their timing. Linking a script or adding a slider also takes effect during transmission.
>
> `Stop TX` also drops the frames the adapter could not send yet, so no stale backlog reaches the bus later.

**Send Now / burst.** Select a row and press `Send Now` to transmit its frame once, outside the periodic schedule. Set the `Burst` count above 1 to send that many frames back-to-back (useful for flooding or triggering). It works whether or not periodic TX is running.

**Remote frames (RTR).** Tick `Remote frame (RTR)` in `Add ID` for a row that carries no data, only the requested DLC — a request for the owning node to transmit. RTR is classic CAN only (mutually exclusive with CAN FD); the payload cell shows `(RTR, DLC n)` and is not editable.

**Replay a trace.** `Replay Trace` reads a `.trc`/`.asc`/`.blf`/`.log` file and transmits its frames onto the bus in their recorded timing (received and transmitted frames alike). Press it again to stop. The bus must be connected and not in listen-only mode.

## Receiving CAN Traffic

1. Load a DBC file (or a workspace that links one) to see message names. A name is shown only for frames with the same ID format (standard or extended) as in the DBC.
2. Tick `Listen only` before `Connect` to observe a network without ever driving it: no acknowledgements, no error frames, no transmission.
3. Link a log file with `Link Log`. The extension picks the format:

   | Extension | Content | Format |
   |---|---|---|
   | `.csv` | received frames, one line each, with the row's statistics (count, period, std-dev) | CANino's own |
   | `.trc` | trace | PEAK TRC 2.1 (PCAN-View) |
   | `.asc` / `.blf` | trace | Vector ASCII / binary logging format |
   | `.log` | trace | candump log (Linux can-utils) |

   Every trace format reads back with python-can (`can.LogReader`).

   A trace holds **every frame on the wire**: received frames (`Rx`) and CANino's own (`Tx`), in bus order, CAN FD included. The `Tx` frames are the adapter's confirmations of what really reached the bus, not what was queued. All timestamps come from the adapter's hardware clock. Then:

   - a. `Start LOG`: start logging. Every frame is written with its hardware timestamp.
   - b. `Pause LOG`: pause. Resuming appends to the same file.
   - c. `Stop LOG`: stop. Starting again overwrites the file.

Standard and extended frames with the same number are separate rows. Error frames reported by the adapter are counted (see the bus status tooltip), not shown as data.

**Filter.** The `Filter` box above the table hides rows that do not match: a substring of the ID, DBC name or payload, or an `id/mask` in hex (e.g. `100/700` keeps IDs whose masked value is `0x100`). Filtering only changes the view — the trace, the CSV and the statistics still see every frame.

**Decoded signals.** When a DBC is loaded, selecting a row shows its DBC signals (name, value, unit, enum text) in the panel below the table, decoded from the row's latest payload and updated live while frames arrive.

## Bus Status

While connected, the top bar shows the controller state: `OK`, `error warning`, `error passive`, `BUS-OFF` or `TX queue full`. CANino stops the transmission (as if `Stop TX` were pressed) and shows a message when:

- the bus is off or the transmit queue is full, at once, or
- the controller stays in error warning or error passive for 2 seconds while transmitting.

The usual cause is that nothing acknowledges the frames: wrong baudrate, missing termination, or no other active node on the bus.

The top bar also shows `BusLoad: x.x% | N fr/s`: the share of the last second the bus was busy, and the number of frames seen on the wire per second (received plus CANino's own, split in the tooltip). The error-frame count is in the bus-state tooltip.

# Payloads

## Precedence

For every frame CANino builds the payload in this order:

1. **Per-row script**, if one is linked to the row.
2. Otherwise the **global script**, if one is linked.
3. Otherwise, or when the script returns `None`, the **manual payload** of the table.
4. Then every **slider** on that frame writes its own signal's bits. All other bits are kept as they are.

The result is sent and written back into the payload cell. If a linked script file is missing, or the script raises or returns the wrong length, that frame is **not sent**: the row turns red, the tooltip shows the error, and the error is logged once. `Start TX` lists missing script files.

## Payload Scripts

A payload script is a Python file that defines:

```python
def get_payload(dlc: int, id: int) -> bytes | None:
    ...
```

- Return exactly `dlc` bytes (`bytes` or `bytearray`), or `None` to send the row's manual payload.
- Every row linked to a script gets **its own instance** of it, even when several rows link the same file. Module-level variables (counters, file positions) therefore advance only when that row transmits.
- The global script is a single instance shared by all rows: keep its state keyed by `id`.
- `Start TX` starts every script from scratch. Enabling, disabling, adding or deleting other rows does not reset it.
- **Hot reload:** editing and saving a linked script while transmitting reloads it automatically at the next frame — no `Start TX` needed. The reload restarts that script's state (it is a fresh instance), which is the point: you see the edited version immediately.

> **Scripts are ordinary Python code and run with your user's rights.** Opening someone else's workspace and pressing `Start TX` runs the scripts it links. Only open workspaces from sources you trust.

## Script Templates

`resources/script_templates/` contains ready-to-use scripts: `TPS_*` for a single row, `GLO_TPS_*` for the global script. `Scripts → New script from template...` copies one to a file you choose; edit it and link it with the row's `Link` button (or as the global script).

| Template | Payload |
|---|---|
| `TPS_constant_0`, `GLO_TPS_constant` | all bytes `0x00` |
| `TPS_blink` | all bytes `0xFF`, byte 0 toggling every 10 frames |
| `TPS_sawtooth`, `GLO_TPS_sawtooth` | last byte counts 1…255, 0, 1… |
| `TPS_random`, `GLO_TPS_random` | random bytes, attack marker in byte 1 |
| `TPS_read_from_file`, `GLO_TPS_read_from_file` | replays a recorded payload sequence per ID, attack marker in byte 1 |

**Attack marker.** The random and read-from-file templates set byte 1 of every frame to `0xA7`, to label injected frames. Frames with DLC 1 carry no marker. Set `ATTACK_MARKER = None` at the top of the template to send the bytes unmarked, for example for an exact replay of a benign sequence.

**Replay files.** The read-from-file templates read `payload_sequence_ID_<hex ID>.csv` (e.g. `payload_sequence_ID_130.csv`) from the `tmp` folder next to the templates' folder (`resources/tmp`), whatever the working directory. Format: a header `Index,B7,B6,B5,B4,B3,B2,B1,B0`, then one frame per row, last column = byte 0. Bytes are **decimal** (0–255); write `0x..` for hex. The sequence repeats when it ends. An ID without a file gets its manual payload.

# Signal Views

With a DBC loaded, two menu windows show decoded signals live, fed by received and transmitted frames alike:

- **XMetro** — up to 4×5 draggable semicircular gauges, one DBC signal each.
- **Signal Plot** — a scrolling time chart: pick a message and signal, press `Add`, and the value is plotted over time. Add several signals to one chart, set how many seconds of history to keep, and remove a signal from the list on the right.

Both follow `Load` / `Load DBC`: changing the DBC updates their available signals.

# Workspace Files

`File → Save / Save As / Load` (shortcuts `Ctrl+S` / `Ctrl+O`) store the whole workspace in a JSON file. `File → Recent workspaces` reopens a recent one, and CANino asks before discarding unsaved changes (the title shows `*` while there are any). `Help → About` shows the version and library versions.

| Key | Content |
|---|---|
| `format`, `version` | `"canino-workspace"`, `3` |
| `app_version` | the CANino version that saved the file (information only) |
| `dbc_file` | DBC file |
| `global_script` | global payload script |
| `signals` | one entry per TX row: `enabled`, `id` (`"0x123"`), `ext`, `fd` and `rtr` (`true`/`false`), `name`, `period` (ms), `payload` (`"00 11 …"`), `dlc`, `script_path` |
| `sliders` | one entry per slider: `msg_name`, `signal_name`, `frame_id`, `is_ext`, `value` (physical value), `unit` |

- **Older files load.** A file without `version` (CANino 1.5 and earlier) is converted when it is loaded: missing ID formats are taken from the ID (above `0x7FF` = extended), missing or `null` CAN FD flags mean classic CAN, `\` in paths becomes `/`, old slider positions become values, and scripts linked under the template names used before August 2025 are found under their new names. `File → Load` lists what was converted; `Save` writes the new format. Rows that cannot be read (bad or duplicate IDs) are skipped and listed. A file written by a newer CANino is refused and the current workspace is kept.

- Paths are stored **relative to the JSON file**, so a project folder can be moved or shared as a whole (absolute when the file is on another drive). Files from older versions, with paths relative to the working directory, still load.
- **Load replaces** the current workspace: TX rows, sliders, global script and DBC. A running transmission is stopped first. A file that cannot be read leaves the current workspace untouched.
- **Save** writes to the file last loaded or saved (shown in the window title), otherwise it asks for a file like `Save As`.

# License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE) file.
