![](resources/figures/CANinoApp_banner_background.png)
# CANino App

## Index

- [Introduction](#introduction)
  - [Supported Devices](#supported-devices)
- [Environment Setup and Usage](#environment-setup-and-usage)
  - [Requirements](#requirements)
  - [Installation](#installation)
  - [Package Naming](#package-naming)
  - [Repo Structure](#repo-structure)
- [Quick Start](#quick-start)
  - [Transmitting CAN Traffic](#transmitting-can-traffic)
  - [Receiving CAN Traffic](#receiving-can-traffic)
- [License](#license)

## Introduction

CANino App is a cross-platform Python + Qt6 application for analyzing, generating, and monitoring CAN bus traffic. It is designed for automotive developers, testers, and diagnosticians. The app allows you to:

- Transmit custom CAN messages with constant, dynamic, or slider-controlled payloads.
- Receive and view CAN messages in real time, with statistics on period, standard deviation, and payload.
- Load DBC files for automatic decoding of message names and structures.
- Save and load workspace configurations in JSON format.
- Connect custom Python scripts for dynamic payload generation.
- Export logs of received messages in CSV format.

The graphical interface is intuitive and allows quick management of IDs, periods, payloads, and scripts, making CANinoApp a versatile tool for automatic testing, manual debugging of ECUs, and CAN message generation.

## Supported Devices

- PCAN-USB (Windows) via PCANBasic.dll

# Environment Setup and Usage

## Requirements

- Python 3.9+ (Python 3.10 or above recommended)
- PCAN-USB driver installed ([download link](https://www.peak-system.com/PCAN-USB.199.0.html?L=1))
- [PCANBasic.dll](resources/PCANBasic.dll) (already included in `resources/`, update if needed)

## Installation

1. **Clone the repository**

    ```sh
    git clone https://github.com/NickCanino/CANino_app.git
    cd CANino_app
    ```

2. **Create a virtual environment**

    ```sh
    python -m venv .venv
    ```

3. **Activate the virtual environment**

    ```sh
    .\.venv\Scripts\activate  # On Windows
    ```

    ```sh
    source .venv/bin/activate  # On Linux/Mac
    ```

4. **Install dependencies**

    ```sh
    pip install -r requirements.txt
    ```

    > **OPTIONAL:** Set the venv interpreter if needed  
    > On Windows: `.venv\Scripts\python.exe`  
    > On Linux/Mac: `.venv/bin/python`

5. **Build the application executable**

    Before running the final command to generate the application:

    1. *Update the app version* in the `VERSION` file to match the release version.
    2. *Update the project files list* in the `.spec` file if additional files need to be included in the final build.

    ```sh
    pyinstaller CANinoApp_exe_setup.spec
    ```

## Package Naming

The built `.exe` will appear in the `dist/` folder with the following name:

> **CANinoApp_vX.Y.Z_hHASH**

Where:

1. **X**: Major version number of the release
2. **Y**: Minor version number of the release
3. **Z**: Patch version number of the release
4. **HASH**: Short Git commit hash of the source code used for the build

*Example:*  `CANinoApp_v1.1.0_ha1b2c3d.exe`

## Repo Structure

```
CANino_app/
│
├── main.py
├── requirements.txt
├── README.md
├── src/
│   └── ... (Python files of the project)
└── resources/
    ├── PCANBasic.dll
    ├── csv_logs/
    ├── figures/
    ├── script_templates/
    └── workspace_config_files/
```

# Quick Start

Once you have obtained `dist/CANinoApp_vX.Y.Z_hHASH.exe`, follow these simple workflows to start your first project, both for transmitting and receiving CAN traffic.

## Transmitting CAN Traffic

1. Add CAN messages to be transmitted in the **Transmitted CAN Frames (TX)** window:
    - a. Load a DBC file by pressing the `Load DBC` button,
    - b. Load a previously saved project (`File → Load → xxx.json`), or
    - c. Add messages manually using the `Add ID` button.

2. Select the desired device from the available options in the `Channel` drop-down menu (refresh the list after connecting/disconnecting a device).

3. Set the `Baudrate` to match the network, choosing a value between 5 kBit/s and 1 MBit/s, then click `Connect`.

4. Configure the payloads of the CAN frames to be transmitted:
    - a. Change the value manually,
    - b. Link a Python script via the `Link Script` button, or
    - c. **If a DBC is loaded**, control the value of a selected signal (portion of the payload) dynamically during transmission using one or more sliders (`Add Slider` button).

5. Press the `Start TX` button (available only when connected to a device) to start transmitting the configured traffic.

### Notes
> 1. CAN message IDs can be added, deleted, enabled, or disabled during transmission.
> 2. The transmission period of each ID can be changed during transmission.
> 3. Regarding the transmitted value for the payload of each ID (message):
>     a. **No DBC Loaded:** A manual value is overwritten by a linked Python script.
>     b. **DBC Loaded:** A manual value is overwritten by a linked Python script, which is partially overwritten by a slider (only the signal controlled by the slider).

## Receiving CAN Traffic

1. Load a DBC file (or a `.json` project in which a DBC has been linked) if you want to see the names of the received CAN frames that correspond to DBC messages.

2. Link a `.csv` file to log the received CAN traffic via the `Link CSV` button.

3. Select the desired device from the available options in the `Channel` drop-down menu (refresh the list after connecting/disconnecting a device).

4. Set the `Baudrate` to match the network, choosing a value between 5 kBit/s and 1 MBit/s, then click `Connect`.

5. Once connected, if a `.csv` file has been linked, you can use three buttons:
    - a. `Start LOG`: Starts logging of received traffic.
    - b. `Pause LOG`: Pauses logging. Resuming will append new logs to the linked file.
    - c. `Stop LOG`: Stops logging completely. Restarting logging will clear the linked file.

# License

This project is licensed under the Apache License 2.0. See the [LICENSE](LICENSE)
