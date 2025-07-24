# CANino App

description...

## Requirements

- Python 3.9+ (suggested 3.10 or above)
- PCAN-USB driver installed (for Windows)
- [PCANBasic.dll](resources/PCANBasic.dll) (already in `resources/`, to be updated if needed)

## Installation

1. **Clone repo**

```sh
git clone https://github.com/NickCanino/CANino_app.git
cd CANino_app
```

2. **Create a venv**

```sh
python -m venv .venv
```

3. **Activate the venv**

      On Windows
```sh
.\.venv\Scripts\activate (or activate.bat)
```

      On Linux/Mac
```sh
source .venv/bin/activate
```

4. **Install Dependencies**

```sh
pip install -r requirements.txt
```

5. **Set venv interpreter if needed**

```sh
.venv\Scripts\python.exe
```

6. **In CMD create the .EXE of the application, modify the .SPEC file if additional files should be included in the project**

```sh
pyinstaller CANinoApp_v0.1.spec
```


## Repo Structure

CANino_app/
│
├── main.py
├── requirements.txt
├── README.md
├── src/
│   └── ... (Python files of the project)
└── resources/
    ├── PCANBasic.dll
    ├── csv_logs
    ├── figures
    ├── script_templates
    └── workspace_config_files

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.