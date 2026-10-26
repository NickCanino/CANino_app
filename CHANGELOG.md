# Changelog

All notable changes to CANino App. Versions from 1.4.0 on are PySide6 builds;
1.3.x and earlier were PyQt6.

## 1.7.2 — Signal Plot: every value, anomaly intervals

Added
- **Signal Plot shows every value**: every received and transmitted frame of a
  plotted signal is drawn at its own frame time (before: the newest value per
  frame every 100 ms, so a 10 ms signal showed 1 sample in 10 and a one-frame
  spike could be missing). At high rates each pixel column draws its first,
  lowest, highest and last value: no spike is lost and redraw cost stays flat
  (≈ 25 ms per refresh for 4 signals at 1 ms).
- **Anomaly labels in payload scripts**: `get_payload` may return
  `(payload, label)`; a non-empty `str` marks that frame as anomalous. Plain
  `bytes` / `None` returns work as before.
- **Anomaly intervals in the Signal Plot**: each run of equally labelled TX
  frames gets a red band (first to last labelled frame), a red onset line and
  the label; one-frame anomalies show as a line.

Changed
- **Replay**: idle gaps longer than 10 s (was 1 s) are compressed, and
  Tools → "Replay: Compress Idle Gaps > 10 s" turns it off (recorded timing);
  Stop interrupts a long gap.
- **TX buttons**: Start TX with a play icon, Stop TX red, Replay amber while
  running, Mute/Unmute All; the status bar reads "BusLoad: x% [n fr/s]".
- **TX table**: the payload column stretches; the script column fits the
  linked names.
- **DBC Decoded Signals panel**: every column can be resized by dragging,
  and the columns always fill the panel (an inner edge moves like a splitter,
  the right wall stays put). Defaults: Unit as wide as its header, Value
  80 px, Signal the rest.
- **Templates**: only five payload templates are tracked and shipped in the
  exe (GLO_TPS_random/sawtooth, TPS_random/sawtooth/sine).

Fixed
- **TPS_sine template** keeps the script contract: exactly `dlc` bytes at any
  DLC (zeros when the signal does not fit, instead of `None`), the
  `get_payload` signature in its header, English comments. Its output at the
  DLCs that fit is unchanged.

## 1.7.1 — UI polish

Changed
- **Main window reorganised**: XMetro, Signal Plot and VAGILETTA under a
  **Tools** menu; a **View** menu shows/hides the Sliders and decoded-signal
  panels; Load DBC only in File (no top-bar button). Connection settings in
  one top bar; bus state, BusLoad, the linked **DBC** and the logos in a
  **status bar** (the footer is gone).
- **DBC Signal Sliders (TX)** and **DBC Decoded Signals (RX)** are side docks: hide, float or move
  them left/right; sharing a side, Sliders stay on top. Sliders have an orange
  border, Decoded a purple one.
- **TX toolbar** on one row, packed left: four groups (Add ID / Delete All,
  Enable All / Start TX, Burst + Send Now + Replay Trace, global script),
  separated.
- **RX**: Clear RX, filter and the log controls on one row, packed left and
  separated; Start/Pause/Stop are icon buttons (the tooltip says what a
  click does).
- **Link Log** shows the linked file's name (green), like the script
  buttons. Help → About shows the logos.
- **Signal Plot**: wider plotted-signals box; icons on Add and Remove.

## 1.7.0 — Phase 3 (add-ons)

Added
- **Standard traces**: log to `.trc` (PEAK TRC 2.1), `.asc`/`.blf` (Vector) or
  `.log` (candump) — every frame on the wire, received and transmitted, with
  hardware timestamps. `Link Log` picks the format by extension.
- **Attack modes** (`src/attacks.py`): flood, fuzzing, spoofing, replay and
  suspension, built on the TX engine with reproducible, seeded payloads — for
  CAN-IDS datasets.
- **Labelled capture**: attack start/stop written into the trace and a sidecar
  `<trace>.labels.csv`, so attack windows are reproducible.
- **Frames/s** in the bus-load readout; **script hot-reload** (edit a linked
  script while transmitting); **Scripts → New script from template**.
- **RX filter** (ID/name/payload or `id/mask`) and a **decoded-signal panel**
  for the selected RX row.
- **Trace replay**: play a `.trc`/`.asc`/`.blf`/`.log` back onto the bus in
  recorded time.
- **Send Now / burst** and **remote frames (RTR)** in the TX table.
- **Signal Plot**: live QtCharts time plots of DBC signals.
- **Virtual interface**: an in-process loopback bus for demos and tests, no
  hardware; an Interface selector chooses PCAN-USB or Virtual.
- **Enum signals** are a combo box instead of a slider.
- **Recent workspaces**, `Ctrl+S` / `Ctrl+O`, an unsaved-changes prompt, and a
  **Help → About** dialog (version, libraries, license).

Changed
- Workspace format version 3: each TX row gains `rtr`. Older files load
  unchanged (a missing `rtr` is a normal data frame).

Fixed
- Test-suite segfault: windows are now disposed in test teardown instead of
  being left for the garbage collector (surfaced an existing VAGILETTA teardown
  race).

## 1.6.0 — Phase 2 (architecture)

- RX and TX moved to Qt Model/View; a dedicated TX scheduler thread with
  absolute deadlines (no timer drift, no catch-up bursts).
- Exact bit-level bus-load (stuff bits, real CRC, FD data phase).
- Workspace format version 2 (JSON booleans, portable paths, slider values).
- `gui.py` split into `tx_panel` / `slider_panel` / `workspace` / `tx_scheduler`
  / `busload`; unused Qt modules dropped from the exe (70 → 47 MB).

## 1.5.0 — Phase 1 (robustness)

- Bus status in the UI, TX-queue-full / bus-off handling, listen-only connect.
- RX pipeline rewrite (RX thread only enqueues; the GUI drains): fixes the
  sorted-table and dictionary-race bugs and the CSV off-by-one / timestamps.
- Per-user log directory with rotation; many silent failures now reported.

## 1.4.0 — Phase 0 (first PySide6 release)

- Baudrate and CAN FD actually applied to the adapter; 29-bit IDs; the Add ID
  regression fixed; per-ID scripts run as independent instances; template and
  replay-file fixes.
