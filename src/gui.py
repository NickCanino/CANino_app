from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QComboBox,
    QLabel,
    QGroupBox,
    QTreeWidget,
    QTreeWidgetItem,
    QSpinBox,
    QFileDialog,
    QMessageBox,
    QInputDialog,
    QSplitter,
    QStyle,
    QMenuBar,
    QMenu,
    QSlider,
    QScrollArea,
)
from PyQt6.QtGui import QAction
from PyQt6.QtCore import Qt, QTimer
import json
import os

from src.dbc_loader import load_dbc
from src.can_interface import CANInterface
from src.exceptions_logger import log_exception
from src.xmetro_class import XMetroWindow
from src.received_frames_class import ReceivedFramesWindow
from src.PCANBasic import (
    PCAN_BAUD_1M,
    PCAN_BAUD_800K,
    PCAN_BAUD_500K,
    PCAN_BAUD_250K,
    PCAN_BAUD_125K,
    PCAN_BAUD_100K,
    PCAN_BAUD_95K,
    PCAN_BAUD_83K,
    PCAN_BAUD_50K,
    PCAN_BAUD_47K,
    PCAN_BAUD_33K,
    PCAN_BAUD_20K,
    PCAN_BAUD_10K,
    PCAN_BAUD_5K,
)


class SliderMeta:
    def __init__(
        self,
        msg_name: str,
        signal_name: str,
        frame_id: int,
        min_val: float,
        max_val: float,
        step: float,
        unit: str,
        value_index: int,
    ):
        self.msg_name = msg_name
        self.signal_name = signal_name
        self.frame_id = frame_id
        self.min_val = min_val
        self.max_val = max_val
        self.step = step
        self.unit = unit
        self.value_index = value_index  # posizione dello slider


class MainWindow(QMainWindow):
    CONFIG_FILE = "resources/workspace_config_files/default_config_file.json"

    def __init__(self):
        super().__init__()
        self.setWindowTitle("CANino App - CAN Traffic Generator")
        self.setGeometry(100, 100, 1100, 700)
        self.dbc = None
        self.can_if = None
        self.timers = []
        self.tx_running = False

        self.project_root = os.getcwd()

        # --- MENU ---
        menubar = QMenuBar(self)
        menubar.setStyleSheet(
            """
            QMenuBar {
                background-color: #444444;
                color: white;
            }
            QMenuBar::item {
                background: #444444;
                color: white;
            }
            QMenuBar::item:selected {
                background: #666666;
            }
            QMenu {
                background-color: #444444;
                color: white;
            }
            QMenu::item:selected {
                background: #666666;
            }
        """
        )
        file_menu = QMenu("&File", self)
        action_save = QAction("Salva", self)
        action_save_as = QAction("Salva con nome...", self)
        action_load = QAction("Carica", self)
        # Connect actions to methods
        action_save.triggered.connect(self.save_config)
        action_save_as.triggered.connect(self.save_config_as)
        action_load.triggered.connect(self.load_config)
        # Set icons for actions
        action_save.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        action_save_as.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogSaveButton)
        )
        action_load.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogOpenButton)
        )
        # Add actions to the file menu
        file_menu.addAction(action_save)
        file_menu.addAction(action_save_as)
        file_menu.addAction(action_load)
        menubar.addMenu(file_menu)
        self.setMenuBar(menubar)

        # --- CONTROLLI IN ALTO ---
        top_controls = QWidget()
        top_layout = QHBoxLayout()
        top_controls.setLayout(top_layout)
        top_controls.setFixedHeight(50)  # Imposta l'altezza fissa del box superiore

        # --- PULSANTI E COMBOBOX IN ALTO ---
        self.btn_load_dbc = QPushButton("  Carica DBC")
        self.btn_load_dbc.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogContentsView)
        )
        self.btn_load_dbc.setFixedSize(120, 30)
        self.btn_load_dbc.clicked.connect(self.load_dbc_file)
        top_layout.addWidget(self.btn_load_dbc)

        ## ComboBox per selezionare il canale CAN
        self.lbl_bus_tx = QLabel("Channel:")
        self.lbl_bus_tx.setAlignment(Qt.AlignmentFlag.AlignRight)
        top_layout.addWidget(self.lbl_bus_tx, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.cb_bus_tx = QComboBox()
        self.cb_bus_tx.setFixedSize(200, 30)
        top_layout.addWidget(self.cb_bus_tx)

        self.btn_refresh_bus = QPushButton()
        self.btn_refresh_bus.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.btn_refresh_bus.setFixedSize(30, 30)
        self.btn_refresh_bus.clicked.connect(self.refresh_bus_list)
        top_layout.addWidget(self.btn_refresh_bus)

        self.lbl_baudrate = QLabel("Baudrate:")
        self.lbl_baudrate.setAlignment(Qt.AlignmentFlag.AlignRight)
        top_layout.addWidget(self.lbl_baudrate, alignment=Qt.AlignmentFlag.AlignVCenter)

        self.cb_baudrate = QComboBox()
        baudrate_values = [
            ("1 MBit/s", str(PCAN_BAUD_1M.value), 1000000),
            ("800 kBit/s", str(PCAN_BAUD_800K.value), 800000),
            ("500 kBit/s", str(PCAN_BAUD_500K.value), 500000),
            ("250 kBit/s", str(PCAN_BAUD_250K.value), 250000),
            ("125 kBit/s", str(PCAN_BAUD_125K.value), 125000),
            ("100 kBit/s", str(PCAN_BAUD_100K.value), 100000),
            ("95.238 kBit/s", str(PCAN_BAUD_95K.value), 95238),
            ("83.333 kBit/s", str(PCAN_BAUD_83K.value), 83333),
            ("50 kBit/s", str(PCAN_BAUD_50K.value), 50000),
            ("47.619 kBit/s", str(PCAN_BAUD_47K.value), 47619),
            ("33.333 kBit/s", str(PCAN_BAUD_33K.value), 33333),
            ("20 kBit/s", str(PCAN_BAUD_20K.value), 20000),
            ("10 kBit/s", str(PCAN_BAUD_10K.value), 10000),
            ("5 kBit/s", str(PCAN_BAUD_5K.value), 5000),
        ]
        for label, pcan_val, real_val in baudrate_values:
            self.cb_baudrate.addItem(label, (pcan_val, real_val))
        self.cb_baudrate.setCurrentIndex(2)  # Default to 500 kBit/s
        self.cb_baudrate.setFixedSize(100, 30)
        top_layout.addWidget(self.cb_baudrate)

        self.btn_connect = QPushButton("Connetti")
        self.btn_connect.setCheckable(True)
        self.btn_connect.clicked.connect(self.toggle_connection)
        self.btn_connect.setFixedSize(100, 30)
        self.btn_connect.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
        )
        top_layout.addWidget(self.btn_connect)

        self.btn_add_id = QPushButton("Aggiungi ID")
        self.btn_add_id.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.btn_add_id.setFixedSize(120, 30)
        self.btn_add_id.clicked.connect(self.add_manual_id)

        self.btn_start_tx = QPushButton("Start TX")
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )
        self.btn_start_tx.setFixedSize(100, 30)
        self.btn_start_tx.clicked.connect(self.start_stop_transmission)
        self.btn_start_tx.setEnabled(False)  # Disabilita il pulsante all'inizio

        self.btn_add_xmetro = QPushButton("Aggiungi XMetro TX")
        self.btn_add_xmetro.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)
        )
        self.btn_add_xmetro.setFixedSize(180, 30)
        self.btn_add_xmetro.clicked.connect(self.open_xmetro_window)

        self.xmetro_windows = []

        # Layout orizzontale per i due pulsanti
        tx_buttons_layout = QHBoxLayout()
        tx_buttons_layout.addWidget(self.btn_add_id)
        tx_buttons_layout.addWidget(self.btn_start_tx)
        tx_buttons_layout.addWidget(
            self.btn_add_xmetro, alignment=Qt.AlignmentFlag.AlignRight
        )
        tx_buttons_layout.addStretch(1)

        # --- ALBERO DEI SEGNALI ---
        self.signal_tree = QTreeWidget()
        self.signal_tree.setHeaderLabels(
            ["", "Abilita", "ID", "Nome", "Periodo (ms)", "Payload (0 - 7)", ""]
        )
        self.signal_tree.setColumnWidth(0, 50)
        self.signal_tree.setColumnWidth(1, 50)
        self.signal_tree.setColumnWidth(2, 50)
        self.signal_tree.setColumnWidth(3, 100)
        self.signal_tree.setColumnWidth(4, 80)
        self.signal_tree.setColumnWidth(5, 140)
        self.signal_tree.setColumnWidth(6, 70)
        self.signal_tree.itemChanged.connect(self.on_signal_tree_item_changed)

        self.signal_tree.setSortingEnabled(
            True
        )  # Abilita l'ordinamento della tabella dei segnali

        # Groupbox per i controlli di trasmissione
        tx_group = QGroupBox()
        tx_group.setStyleSheet(
            "QGroupBox { border: 2px solid #4CAF50; border-radius: 5px; }"
        )
        # Crea il layout verticale per il gruppo di trasmissione
        tx_layout = QVBoxLayout()
        tx_group.setLayout(tx_layout)
        tx_title = QLabel("Trasmissione CAN (TX)")
        tx_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tx_title.setStyleSheet("font-weight: bold;")
        tx_layout.addWidget(tx_title)
        tx_layout.addLayout(tx_buttons_layout)
        tx_layout.addWidget(self.signal_tree)

        # Aggiungi il layout dei controlli di ricezione al layout principale
        self.rx_window = ReceivedFramesWindow(self.dbc)
        rx_group = QGroupBox()
        rx_group.setStyleSheet(
            "QGroupBox { border: 2px solid #2196F3; border-radius: 5px; }"
        )
        # Crea il layout verticale per il gruppo di ricezione
        rx_layout = QVBoxLayout()
        rx_group.setLayout(rx_layout)
        rx_title = QLabel("Ricezione CAN (RX)")
        rx_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        rx_title.setStyleSheet("font-weight: bold;")
        rx_layout.addWidget(rx_title)
        rx_layout.addWidget(self.rx_window)

        # --- GRUPPO DEGLI SLIDER ---
        slider_group = QGroupBox()
        slider_group.setStyleSheet(
            "QGroupBox { border: 2px solid #FF9800; border-radius: 5px; }"
        )
        slider_group.setMinimumWidth(300)

        slider_layout = QVBoxLayout()
        slider_group.setLayout(slider_layout)

        slider_title = QLabel("Sliders per TX")
        slider_title.setAlignment(Qt.AlignmentFlag.AlignTop)
        slider_title.setStyleSheet("font-weight: bold;")
        slider_layout.addWidget(slider_title)

        self.btn_add_slider = QPushButton("Aggiungi Slider")
        self.btn_add_slider.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
        )
        self.btn_add_slider.setFixedSize(150, 30)
        slider_layout.addWidget(self.btn_add_slider)

        # Area scrollabile
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        slider_scroll_widget = QWidget()
        self.slider_container = QVBoxLayout()
        slider_scroll_widget.setLayout(self.slider_container)
        scroll_area.setWidget(slider_scroll_widget)
        slider_layout.addWidget(scroll_area)

        # Contenitore per gli slider dinamici
        self.slider_container = QVBoxLayout()
        slider_layout.addLayout(self.slider_container)

        self.added_sliders = set()
        self.slider_widgets = []

        def add_slider():
            if not hasattr(self, "dbc") or self.dbc is None:
                QMessageBox.warning(self, "DBC", "Carica prima un file DBC!")
                return
            msg_names = [msg.name for msg in self.dbc.messages]
            msg_idx, ok = QInputDialog.getItem(
                self, "Seleziona messaggio", "Messaggio:", msg_names, 0, False
            )
            if not ok:
                return
            msg = next(m for m in self.dbc.messages if m.name == msg_idx)
            sig_names = [sig.name for sig in msg.signals]
            sig_idx, ok = QInputDialog.getItem(
                self, "Seleziona segnale", "Segnale:", sig_names, 0, False
            )
            if not ok:
                return
            sig = next(s for s in msg.signals if s.name == sig_idx)

            key = (msg.name, sig.name)
            if key in self.added_sliders:
                QMessageBox.warning(
                    self,
                    "Slider già esistente",
                    f"Esiste già uno slider per {msg.name} (0x{msg.frame_id:03X}) → {sig.name}",
                )
                return
            self.added_sliders.add(key)

            # Calcolo min/max SEMPRE da bit_length, offset, scale, signed/unsigned, endianess
            factor = getattr(sig, "factor", getattr(sig, "scale", 1.0)) or 1.0
            offset = getattr(sig, "offset", 0.0)
            bit_length = getattr(sig, "length", 8)
            is_signed = getattr(sig, "is_signed", False)
            # endianess non influisce su min/max, ma la includo per completezza
            # byte_order = getattr(sig, 'byte_order', 'little_endian')
            if is_signed:
                raw_min = -(2 ** (bit_length - 1))
                raw_max = 2 ** (bit_length - 1) - 1
            else:
                raw_min = 0
                raw_max = 2**bit_length - 1
            min_val = raw_min * factor + offset
            max_val = raw_max * factor + offset
            step = factor

            # Crea il widget per lo slider
            slider_widget = QGroupBox()
            slider_widget.setFixedHeight(100)  # Altezza fissa
            slider_widget.setStyleSheet(
                "QGroupBox { margin-top: 10px; border: 1px solid gray; border-radius: 5px; }"
            )
            slider_layout_inner = QVBoxLayout()
            slider_widget.setLayout(slider_layout_inner)

            # Aggiungi il widget dello slider alla lista
            if not hasattr(
                self, "slider_widgets"
            ):  # Ensure slider_widgets is initialized
                self.slider_widgets = []

            slider_widget.key = key  # Store the key for later reference
            self.slider_widgets.append(slider_widget)  # Store the widget for later use

            label = QLabel(f"{msg.name} (0x{msg.frame_id:03X}) → {sig.name}")
            slider_layout_inner.addWidget(label)

            # Crea e setta lo slider
            num_steps = int(round((max_val - min_val) / step))

            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setMinimum(0)
            slider.setMaximum(num_steps)
            slider.setSingleStep(1)
            slider.setValue(0)
            slider_layout_inner.addWidget(slider)

            # Salva metadata
            slider_widget.frame_id = msg.frame_id
            slider_widget.signal = sig
            slider_widget.slider = slider
            slider_widget.min_val = min_val
            slider_widget.max_val = max_val
            slider_widget.step = step
            slider_widget.unit = sig.unit if sig.unit else ""

            info_layout = QHBoxLayout()
            lbl_min = QLabel(f"Min: {min_val}")
            lbl_max = QLabel(f"Max: {max_val}")
            lbl_value = QLabel(f"Val: {min_val} [{sig.unit}]")
            btn_remove = QPushButton()
            btn_remove.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            )
            btn_remove.setFixedWidth(30)

            def update_value_label(step_index):
                real_value = min_val + step_index * step
                formatted = f"{real_value:.2f}" if step < 1.0 else f"{int(real_value)}"
                lbl_value.setText(f"Val: {formatted} {sig.unit if sig.unit else ''}")

            def remove_slider():
                for i in reversed(range(self.slider_container.count())):
                    widget = self.slider_container.itemAt(i).widget()
                    if widget == slider_widget:
                        # Rimuovi il widget visivamente
                        widget.setParent(None)

                        # Rimuovi la chiave dallo set di slider aggiunti
                        self.added_sliders.discard(key)

                        # Rimuovi il widget dalla lista slider_widgets
                        if hasattr(self, "slider_widgets"):
                            self.slider_widgets = [
                                w
                                for w in self.slider_widgets
                                if not (
                                    w.frame_id == msg.frame_id
                                    and w.signal.name == sig.name
                                )
                            ]

                        # Riavvia la trasmissione per aggiornare il comportamento
                        if self.tx_running:
                            self.stop_tx()
                            self.start_tx()
                        break

            slider.valueChanged.connect(update_value_label)
            btn_remove.clicked.connect(remove_slider)

            info_layout.addWidget(lbl_min)
            info_layout.addStretch()
            info_layout.addWidget(lbl_value)
            info_layout.addStretch()
            info_layout.addWidget(lbl_max)
            info_layout.addWidget(btn_remove)
            slider_layout_inner.addLayout(info_layout)

            self.slider_container.addWidget(slider_widget)

        self.refresh_bus_list()

        self.btn_add_slider.clicked.connect(add_slider)

        # --- SPLITTER PRINCIPALE ---
        main_splitter = QSplitter(Qt.Orientation.Horizontal)
        # Box sinistra: splitter verticale con TX e RX
        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(tx_group)
        left_splitter.addWidget(rx_group)
        left_splitter.setStretchFactor(0, 3)
        left_splitter.setStretchFactor(1, 2)
        main_splitter.addWidget(left_splitter)
        main_splitter.addWidget(slider_group)
        main_splitter.setStretchFactor(0, 5)
        main_splitter.setStretchFactor(1, 2)

        # Layout principale
        main_layout = QVBoxLayout()
        main_layout.addWidget(top_controls)
        main_layout.addWidget(main_splitter)

        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        self.refresh_bus_list()
        # Carica la configurazione all'avvio, se esiste
        self.load_config(auto=True)

    def save_config(self):
        self._save_config_to_file(self.CONFIG_FILE)

    def save_config_as(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, "Salva configurazione con nome", "", "File JSON (*.json)"
        )
        if filename:
            self._save_config_to_file(filename)
            self.CONFIG_FILE = filename  # Aggiorna il file di default

    def _save_config_to_file(self, filename):
        dbc_path = os.path.relpath(
            self.dbc.dbc_filename, start=self.project_root
        )  # percorso relativo del file DBC

        config = {"dbc_file": dbc_path, "signals": [], "sliders": []}

        for widget in getattr(self, "slider_widgets", []):
            meta = SliderMeta(
                msg_name=widget.signal.name,
                signal_name=widget.signal.name,
                frame_id=widget.frame_id,
                min_val=widget.min_val,
                max_val=widget.max_val,
                step=widget.step,
                unit=widget.unit,
                value_index=widget.slider.value(),
            )
            config["sliders"].append(meta.__dict__)

        for i in range(self.signal_tree.topLevelItemCount()):
            item = self.signal_tree.topLevelItem(i)
            signal = {
                "enabled": item.checkState(1) == Qt.CheckState.Checked,
                "id": item.text(2),
                "name": item.text(3),
                "period": (
                    self.signal_tree.itemWidget(item, 4).value()
                    if self.signal_tree.itemWidget(item, 4)
                    else 100
                ),
                "payload": item.text(5),
                "dlc": item.data(2, Qt.ItemDataRole.UserRole + 1) or 8,
                "script_path": item.data(
                    6, Qt.ItemDataRole.UserRole
                ),  # salva anche lo script per l'ID
            }
            config["signals"].append(signal)
        try:
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
            QMessageBox.information(
                self,
                "Configurazione",
                f"Configurazione salvata con successo in:\n{filename}",
            )
        except Exception as e:
            QMessageBox.critical(
                self, "Errore", f"Errore salvataggio configurazione: {e}"
            )
            log_exception(e)

    def load_config(self, auto=False):
        if auto:
            filename = self.CONFIG_FILE
            if not os.path.exists(filename):
                return
        else:
            filename, _ = QFileDialog.getOpenFileName(
                self, "Carica configurazione", "", "File JSON (*.json)"
            )
            if not filename:
                return
        try:
            with open(filename, "r", encoding="utf-8") as f:
                config = json.load(f)

            # Carica DBC se presente
            dbc_file = config.get("dbc_file")
            if dbc_file:
                absolute_path = os.path.abspath(
                    os.path.join(self.project_root, dbc_file)
                )
                if os.path.exists(absolute_path):
                    self.dbc = load_dbc(absolute_path)
                    self.populate_signal_tree()
                    self.rx_window.set_dbc(self.dbc)
                else:
                    QMessageBox.warning(
                        self,
                        "DBC",
                        f"Impossibile trovare il file DBC:\n{absolute_path}",
                    )

            # Carica segnali solo se presenti nella configurazione
            if "signals" in config:
                loaded_ids = set()  # Tieni traccia degli ID già caricati
                for i in range(self.signal_tree.topLevelItemCount()):
                    item = self.signal_tree.topLevelItem(i)
                    try:
                        existing_id = int(item.text(2), 16)
                        loaded_ids.add(existing_id)
                    except Exception:
                        pass

                for sig in config["signals"]:
                    try:
                        frame_id = int(sig.get("id", "0"), 16)
                    except ValueError:
                        continue

                    # Se è già stato caricato dal DBC (populate_signal_tree), collega solo lo script
                    if frame_id in loaded_ids:
                        item = next(
                            (
                                self.signal_tree.topLevelItem(i)
                                for i in range(self.signal_tree.topLevelItemCount())
                                if int(self.signal_tree.topLevelItem(i).text(2), 16)
                                == frame_id
                            ),
                            None,
                        )
                        if item and sig.get("script_path"):
                            script_path = sig["script_path"]
                            item.setData(6, Qt.ItemDataRole.UserRole, script_path)
                            payload_btn = self.signal_tree.itemWidget(item, 6)
                            if payload_btn and isinstance(payload_btn, QPushButton):
                                payload_btn.setChecked(True)
                                payload_btn.setStyleSheet(
                                    "background-color: #4CAF50; color: white;"
                                )
                                payload_btn.setToolTip(
                                    f"Script: {os.path.relpath(script_path, start=self.project_root)}"
                                )
                                payload_btn.setText(os.path.basename(script_path))
                        continue  # salta l'aggiunta dell'intero messaggio: già caricato

                    # Messaggio non caricato: aggiungilo manualmente
                    msg_item = QTreeWidgetItem(self.signal_tree)
                    msg_item.setFlags(
                        msg_item.flags()
                        | Qt.ItemFlag.ItemIsUserCheckable
                        | Qt.ItemFlag.ItemIsEditable
                    )
                    msg_item.setCheckState(
                        1,
                        (
                            Qt.CheckState.Checked
                            if sig.get("enabled")
                            else Qt.CheckState.Unchecked
                        ),
                    )
                    msg_item.setText(2, sig.get("id", ""))
                    msg_item.setText(3, sig.get("name", ""))

                    period_spin = QSpinBox()
                    period_spin.setRange(1, 10000)
                    period_spin.setValue(sig.get("period", 100))
                    self.signal_tree.setItemWidget(msg_item, 4, period_spin)
                    msg_item.setData(4, Qt.ItemDataRole.UserRole, period_spin)

                    # Payload e DLC
                    raw_payload = sig.get("payload", "")
                    dlc = sig.get("dlc", 8)
                    payload_parts = raw_payload.strip().split()
                    if len(payload_parts) != dlc or any(
                        len(p) != 2 for p in payload_parts
                    ):
                        raw_payload = " ".join(["00"] * dlc)
                    msg_item.setText(5, raw_payload)
                    msg_item.setData(2, Qt.ItemDataRole.UserRole + 1, dlc)

                    # Pulsanti standard
                    btn_delete_id = QPushButton()
                    btn_delete_id.setIcon(
                        self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
                    )
                    btn_delete_id.setToolTip("Elimina")
                    btn_delete_id.clicked.connect(
                        lambda _, item=msg_item: self.delete_signal_row(item)
                    )
                    self.signal_tree.setItemWidget(msg_item, 0, btn_delete_id)

                    payload_btn = QPushButton("Link Script")
                    payload_btn.setCheckable(True)
                    payload_btn.setIcon(
                        self.style().standardIcon(
                            QStyle.StandardPixmap.SP_FileDialogDetailedView
                        )
                    )
                    # payload_btn.setToolTip("Script Payload")
                    payload_btn.clicked.connect(
                        lambda _, item=msg_item: self.modify_payload_script(item)
                    )
                    self.signal_tree.setItemWidget(msg_item, 6, payload_btn)

                    if sig.get("script_path"):
                        script_path = sig["script_path"]
                        msg_item.setData(6, Qt.ItemDataRole.UserRole, script_path)
                        payload_btn.setChecked(True)
                        payload_btn.setStyleSheet(
                            "background-color: #4CAF50; color: white;"
                        )
                        payload_btn.setToolTip(
                            f"Script: {os.path.relpath(script_path, start=self.project_root)}"
                        )
                        payload_btn.setText(os.path.basename(script_path))

            # Carica sliders
            if "sliders" in config:
                for meta in config["sliders"]:
                    msg = next(
                        (
                            m
                            for m in self.dbc.messages
                            if m.frame_id == meta["frame_id"]
                        ),
                        None,
                    )
                    if not msg:
                        continue
                    sig = next(
                        (s for s in msg.signals if s.name == meta["signal_name"]), None
                    )
                    if not sig:
                        continue

                    # Ricostruisci lo slider manualmente
                    key = (msg.name, sig.name)
                    if key in self.added_sliders:
                        continue
                    self.added_sliders.add(key)

                    # Calcolo min/max SEMPRE da bit_length, offset, scale, signed/unsigned, endianess
                    factor = getattr(sig, "factor", getattr(sig, "scale", 1.0)) or 1.0
                    offset = getattr(sig, "offset", 0.0)
                    bit_length = getattr(sig, "length", 8)
                    is_signed = getattr(sig, "is_signed", False)
                    if is_signed:
                        raw_min = -(2 ** (bit_length - 1))
                        raw_max = 2 ** (bit_length - 1) - 1
                    else:
                        raw_min = 0
                        raw_max = 2**bit_length - 1
                    min_val = raw_min * factor + offset
                    max_val = raw_max * factor + offset
                    step = factor
                    value_index = meta["value_index"]
                    unit = sig.unit if hasattr(sig, "unit") and sig.unit else ""

                    # costruttore slider come da add_slider()
                    slider_widget = QGroupBox()
                    slider_widget.setFixedHeight(100)
                    slider_layout_inner = QVBoxLayout()
                    slider_widget.setLayout(slider_layout_inner)

                    label = QLabel(f"{msg.name} (0x{msg.frame_id:03X}) → {sig.name}")
                    slider_layout_inner.addWidget(label)

                    slider = QSlider(Qt.Orientation.Horizontal)
                    num_steps = int(round((max_val - min_val) / step))
                    slider.setMinimum(0)
                    slider.setMaximum(num_steps)
                    slider.setSingleStep(1)
                    slider.setValue(value_index)
                    slider_layout_inner.addWidget(slider)

                    # Salva metadata
                    slider_widget.frame_id = msg.frame_id
                    slider_widget.signal = sig
                    slider_widget.slider = slider
                    slider_widget.min_val = min_val
                    slider_widget.max_val = max_val
                    slider_widget.step = step
                    slider_widget.unit = unit

                    info_layout = QHBoxLayout()
                    lbl_min = QLabel(f"Min: {min_val}")
                    lbl_max = QLabel(f"Max: {max_val}")
                    lbl_value = QLabel(f"Val: {min_val} [{unit}]")
                    btn_remove = QPushButton()
                    btn_remove.setIcon(
                        self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
                    )
                    btn_remove.setFixedWidth(30)

                    def update_value_label(
                        step_index,
                        min_val=min_val,
                        step=step,
                        lbl_value=lbl_value,
                        unit=unit,
                    ):
                        real_value = min_val + step_index * step
                        formatted = (
                            f"{real_value:.2f}" if step < 1.0 else f"{int(real_value)}"
                        )
                        lbl_value.setText(f"Val: {formatted} {unit}")

                    def remove_slider():
                        for i in reversed(range(self.slider_container.count())):
                            widget = self.slider_container.itemAt(i).widget()
                            if widget == slider_widget:
                                widget.setParent(None)
                                self.added_sliders.discard(key)
                                if hasattr(self, "slider_widgets"):
                                    self.slider_widgets = [
                                        w
                                        for w in self.slider_widgets
                                        if not (
                                            w.frame_id == msg.frame_id
                                            and w.signal.name == sig.name
                                        )
                                    ]
                                if self.tx_running:
                                    self.stop_tx()
                                    self.start_tx()
                                break

                    slider.valueChanged.connect(update_value_label)
                    btn_remove.clicked.connect(remove_slider)

                    info_layout.addWidget(lbl_min)
                    info_layout.addStretch()
                    info_layout.addWidget(lbl_value)
                    info_layout.addStretch()
                    info_layout.addWidget(lbl_max)
                    info_layout.addWidget(btn_remove)
                    slider_layout_inner.addLayout(info_layout)

                    if not hasattr(self, "slider_widgets"):
                        self.slider_widgets = []

                    self.slider_container.addWidget(slider_widget)
                    slider_widget.key = key  # Unico identificatore per lo slider
                    self.slider_widgets.append(slider_widget)

            if not auto:
                QMessageBox.information(
                    self, "Configurazione", "Configurazione caricata con successo."
                )
        except Exception as e:
            QMessageBox.critical(
                self, "Errore", f"Errore caricamento configurazione: {e}"
            )
            log_exception(e)

    def remove_slider_widget(self, widget):
        # Rimuove il widget dallo slider_container e aggiorna la lista degli slider
        widget.setParent(None)
        if hasattr(widget, "key"):
            self.added_sliders.discard(widget.key)

        self.slider_widgets = [w for w in self.slider_widgets if w != widget]
        if self.tx_running:
            self.stop_tx()
            self.start_tx()

    def refresh_bus_list(self):
        self.cb_bus_tx.clear()
        for display, handle in CANInterface.get_available_channels():
            self.cb_bus_tx.addItem(display, handle)

    def toggle_connection(self):
        if self.btn_connect.isChecked():  # Connetti
            channel = self.cb_bus_tx.currentData()
            if channel is None:
                QMessageBox.warning(self, "Attenzione", "Nessun canale CAN selezionato")
                self.btn_connect.setChecked(False)
                return
            try:
                pcan_val, bitrate = self.cb_baudrate.currentData()
                print(f"bitrate value {bitrate} bps")
                self.can_if = CANInterface(channel, bitrate=bitrate)
                self.can_if.set_receive_callback(self.process_received_frame)
                QMessageBox.information(
                    self,
                    "Info",
                    f"Connesso a USB {channel & 0x00F} - BR: {bitrate} bps",
                )
                self.btn_connect.setText("Disconnetti")
                self.btn_connect.setIcon(
                    self.style().standardIcon(
                        QStyle.StandardPixmap.SP_DialogCancelButton
                    )
                )
                self.cb_baudrate.setEnabled(False)
                self.cb_bus_tx.setEnabled(False)
                self.btn_refresh_bus.setEnabled(False)
                self.btn_add_id.setEnabled(True)
                self.btn_start_tx.setEnabled(True)  # <--- Abilita dopo connessione
            except Exception as e:
                QMessageBox.critical(self, "Errore", f"Errore apertura CAN: {e}")
                log_exception(e)
                self.btn_connect.setChecked(False)
                self.btn_start_tx.setEnabled(False)  # <--- Disabilita se errore
        else:  # Disconnetti
            if self.can_if:
                self.can_if.close()
                self.can_if = None
            self.btn_connect.setText("Connetti")
            self.btn_connect.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton)
            )
            self.cb_baudrate.setEnabled(True)
            self.cb_bus_tx.setEnabled(True)
            self.btn_refresh_bus.setEnabled(True)
            self.btn_add_id.setEnabled(True)
            self.btn_start_tx.setEnabled(False)  # <--- Disabilita dopo disconnessione
            if self.tx_running:
                self.stop_tx()  # <--- Ferma la trasmissione se attiva

    def load_dbc_file(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "Apri file DBC", "", "DBC Files (*.dbc)"
        )
        if filename:
            self.dbc = load_dbc(filename)
            self.populate_signal_tree()
            self.rx_window.set_dbc(self.dbc)

    def populate_signal_tree(
        self,
    ):  # Popola l'albero dei segnali con i messaggi del DBC
        self.signal_tree.clear()
        if not self.dbc:
            return
        for msg in self.dbc.messages:
            msg_item = QTreeWidgetItem(self.signal_tree)
            msg_item.setFlags(
                msg_item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
                | Qt.ItemFlag.ItemIsEditable
            )
            msg_item.setCheckState(1, Qt.CheckState.Checked)
            msg_item.setText(2, f"0x{msg.frame_id:03X}")
            msg_item.setText(3, msg.name)

            period_spin = QSpinBox()
            period_spin.setRange(1, 10000)
            period_spin.setValue(msg.cycle_time if msg.cycle_time else 100)

            self.signal_tree.setItemWidget(msg_item, 4, period_spin)
            msg_item.setData(
                4, Qt.ItemDataRole.UserRole, period_spin
            )  # Store period spinbox in user data
            msg_item.setData(
                2, Qt.ItemDataRole.UserRole + 1, msg.payload_length
            )  # Store DLC in user data
            msg_item.setText(
                5, " ".join(["00"] * msg.payload_length)
            )  # Set default payload

            # Add delete button as first column
            btn_delete_id = QPushButton()
            btn_delete_id.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            )
            btn_delete_id.setToolTip("Elimina")
            btn_delete_id.clicked.connect(
                lambda _, item=msg_item: self.delete_signal_row(item)
            )
            self.signal_tree.setItemWidget(msg_item, 0, btn_delete_id)

            # Add custom payload button in 5th column
            payload_btn = QPushButton("Link Script")
            payload_btn.setCheckable(True)
            payload_btn.setIcon(
                self.style().standardIcon(
                    QStyle.StandardPixmap.SP_FileDialogDetailedView
                )
            )
            payload_btn.setToolTip("No Script Linked")
            payload_btn.clicked.connect(
                lambda _, item=msg_item: self.modify_payload_script(item)
            )
            self.signal_tree.setItemWidget(msg_item, 6, payload_btn)

            # Ascending sort by ID (column 2)
            self.signal_tree.sortItems(2, Qt.SortOrder.AscendingOrder)

    def add_manual_id(self):
        id_text, ok = QInputDialog.getText(
            self, "Aggiungi ID manuale", "Inserisci ID esadecimale (es. 100):"
        )
        if not ok or not id_text:
            return
        try:
            frame_id = int(id_text, 16)
        except ValueError:
            QMessageBox.warning(self, "Errore", "ID non valido")
            return
        name, ok = QInputDialog.getText(self, "Aggiungi ID manuale", "Inserisci nome:")
        if not ok or not name:
            return
        period, ok = QInputDialog.getInt(
            self, "Aggiungi ID manuale", "Inserisci periodo (ms):", min=1, max=10000
        )
        if not ok:
            return
        dlc, ok = QInputDialog.getInt(
            self, "Aggiungi ID manuale", "Inserisci DLC (1-8):", min=1, max=8
        )
        if not ok:
            return

        msg_item = QTreeWidgetItem(self.signal_tree)
        msg_item.setFlags(
            msg_item.flags()
            | Qt.ItemFlag.ItemIsUserCheckable
            | Qt.ItemFlag.ItemIsEditable
        )
        msg_item.setCheckState(1, Qt.CheckState.Checked)
        msg_item.setText(2, f"0x{frame_id:03X}")
        msg_item.setText(3, name)

        # Salva DLC come dato dell'item
        msg_item.setData(2, Qt.ItemDataRole.UserRole + 1, dlc)

        period_spin = QSpinBox()
        period_spin.setRange(1, 10000)
        period_spin.setValue(period)
        self.signal_tree.setItemWidget(msg_item, 4, period_spin)
        msg_item.setData(4, Qt.ItemDataRole.UserRole, period_spin)

        msg_item.setText(5, " ".join(["00"] * dlc))

        # Pulsanti standard
        btn_delete_id = QPushButton()
        btn_delete_id.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        btn_delete_id.setToolTip("Elimina")
        btn_delete_id.clicked.connect(
            lambda _, item=msg_item: self.delete_signal_row(item)
        )
        self.signal_tree.setItemWidget(msg_item, 0, btn_delete_id)

        # Pulsante per linkare lo script del payload
        payload_btn = QPushButton("Link Script")
        payload_btn.setCheckable(True)
        payload_btn.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        )
        payload_btn.setToolTip("No Script Linked")
        payload_btn.clicked.connect(
            lambda _, item=msg_item: self.modify_payload_script(item)
        )
        self.signal_tree.setItemWidget(msg_item, 6, payload_btn)

        # Ascending sort by ID (column 2)
        self.signal_tree.sortItems(2, Qt.SortOrder.AscendingOrder)

    def delete_signal_row(self, item):
        idx = self.signal_tree.indexOfTopLevelItem(item)
        if idx != -1:
            self.signal_tree.takeTopLevelItem(idx)

    def on_signal_tree_item_changed(self, item, column):
        if column == 1:  # Checkbox abilitazione
            if self.tx_running:
                self.stop_tx()
                self.start_tx()
        elif column == 5:
            text = item.text(5).strip()
            parts = text.split()
            dlc = item.data(2, Qt.ItemDataRole.UserRole + 1) or 8

            if len(parts) != dlc or any(len(p) != 2 for p in parts):
                QMessageBox.warning(
                    self,
                    "Errore Payload",
                    f"Payload deve contenere esattamente {dlc} byte in esadecimale, es. {' '.join(['00'] * dlc)}",
                )
                item.setText(5, " ".join(["00"] * dlc))

    def modify_payload_script(self, item):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Seleziona script Python", "", "Python Files (*.py)"
        )
        rel_file_path = (
            os.path.relpath(file_path, start=self.project_root) if file_path else None
        )
        if rel_file_path:
            item.setData(6, Qt.ItemDataRole.UserRole, rel_file_path)
            widget = self.signal_tree.itemWidget(item, 6)
            if widget and isinstance(widget, QPushButton):
                widget.setChecked(True)
                widget.setStyleSheet("background-color: #4CAF50; color: white;")
                widget.setToolTip(f"Script: {rel_file_path}")
                widget.setText(os.path.basename(rel_file_path))
            QMessageBox.information(
                self,
                "Script selezionato",
                f"Script associato all’ID {item.text(2)}:\n{rel_file_path}",
            )

    # Aggiorna il payload di un singolo segnale nel messaggio CAN
    def insert_value_in_payload(
        self, frame_id: int, signal_name: str, value: int, current_payload: bytes
    ) -> bytes:
        """
        Usa cantools per aggiornare un singolo segnale nel payload esistente.
        """
        if not self.dbc or not hasattr(self.dbc, "db"):
            raise RuntimeError("DBC non caricato correttamente.")

        message = self.dbc.db.get_message_by_frame_id(frame_id)
        if not message:
            raise ValueError(f"Messaggio con ID {frame_id} non trovato nel DBC.")

        try:
            decoded = message.decode(current_payload)
        except Exception:
            decoded = {sig.name: 0 for sig in message.signals}

        decoded[signal_name] = value
        return bytes(message.encode(decoded))

    def start_stop_transmission(self) -> None:
        if not self.tx_running:
            if not self.can_if:
                QMessageBox.warning(
                    self,
                    "Attenzione",
                    "Devi connetterti al CAN prima di iniziare la trasmissione",
                )
                return
            self.start_tx()
        else:
            self.stop_tx()

    def start_tx(self):
        """Avvia la trasmissione periodica dei messaggi CAN abilitati in ordine crescente di ID."""
        self.timers.clear()
        items_to_send = []
        for i in range(self.signal_tree.topLevelItemCount()):
            item = self.signal_tree.topLevelItem(i)
            if item.checkState(1) == Qt.CheckState.Checked:
                try:
                    frame_id = int(item.text(2), 16)
                    items_to_send.append((frame_id, item))
                except Exception:
                    continue
        items_to_send.sort(key=lambda x: x[0])

        # Prepara gli slider per i frame
        slider_overrides = {}
        if hasattr(self, "slider_widgets"):
            for w in self.slider_widgets:
                fid = w.frame_id
                sig = w.signal
                if fid not in slider_overrides:
                    slider_overrides[fid] = []
                slider_overrides[fid].append((sig, w.slider))

        # Inizializza i timer per ogni frame
        for frame_id, item in items_to_send:
            period_spin = self.signal_tree.itemWidget(item, 4)
            period = period_spin.value() if period_spin else 1000
            script_path = item.data(6, Qt.ItemDataRole.UserRole)

            script_cache = {}

            def callback(frame_id=frame_id, item=item, script_path=script_path):
                dlc = (
                    item.data(2, Qt.ItemDataRole.UserRole + 1) or 8
                )  # se il payload viene da testo manuale
                if not isinstance(dlc, int) or not (1 <= dlc <= 8):
                    dlc = 8

                # Se il payload è stato specificato come script, lo esegue
                try:
                    if script_path and os.path.exists(script_path):
                        if script_path not in script_cache:
                            script_globals = {}
                            with open(script_path, "r", encoding="utf-8") as f:
                                exec(f.read(), script_globals)
                            get_payload_fn = script_globals.get("get_payload")
                            if not callable(get_payload_fn):
                                raise RuntimeError(
                                    "Il file selezionato non contiene una funzione get_payload()"
                                )
                            script_cache[script_path] = get_payload_fn
                        else:
                            get_payload_fn = script_cache[script_path]

                        payload = get_payload_fn(dlc)
                        if not isinstance(payload, bytes) or len(payload) != dlc:
                            raise ValueError(
                                f"get_payload(dlc) deve restituire esattamente {dlc} byte"
                            )
                    else:
                        payload_text = item.text(5).strip()

                        if payload_text:
                            payload_parts = payload_text.split()
                            payload = bytes(int(b, 16) for b in payload_parts[:dlc])
                        else:
                            payload = bytes([0x00] * dlc)

                        # Se lo script restituisce un payload, usa solo i primi DLC byte
                        if isinstance(payload, bytes):
                            payload = payload[:dlc] + bytes(
                                [0x00] * max(0, dlc - len(payload))
                            )

                    # oppure se arriva da uno script, taglia i byte in eccesso
                    # payload = payload[:dlc] + bytes([0x00] * max(0, dlc - len(payload)))

                    payload_list = list(payload)
                    if frame_id in slider_overrides:
                        for sig, slider in slider_overrides[frame_id]:
                            val_index = slider.value()
                            real_value = (
                                slider.parent().min_val
                                + val_index * slider.parent().step
                            )
                            result = self.insert_value_in_payload(
                                frame_id, sig.name, real_value, bytes(payload_list)
                            )
                            if isinstance(result, int):
                                result = bytes([result])
                            payload_list = list(result)
                    final_payload = bytes(payload_list)
                    if len(final_payload) != dlc:
                        final_payload = final_payload[:dlc] + bytes(
                            [0x00] * max(0, dlc - len(final_payload))
                        )
                    # print(f"[DEBUG] final_payload type: {type(final_payload)}, value: {final_payload}")

                    # Invia il frame e aggiorna il payload nella finestra TX
                    self.send_can_message(frame_id, final_payload, dlc)
                    item.setText(5, " ".join(f"{b:02X}" for b in final_payload))

                    # 🧭 Update live gauges (XMetro)
                    for gauge in getattr(self, "xmetro_windows", []):
                        if gauge.cb_messages.currentData() == frame_id:
                            if not isinstance(
                                final_payload, bytes
                            ):  # Converti in bytes se necessario
                                try:
                                    final_payload = bytes(final_payload)
                                except Exception:
                                    print(
                                        f"[XMetro] Payload non convertibile: {type(final_payload)}, valore {final_payload}"
                                    )
                                    continue
                            # Aggiorna il gauge con il payload finale
                            gauge.update_gauge(final_payload)
                            # print(f"[XMetro] Payload passato al gauge: {type(final_payload)}, valore {final_payload}")

                except Exception as e:
                    print(f"[Errore TX ID {frame_id:03X}]: {e}")
                    log_exception(e)

            timer = QTimer(self)
            timer.timeout.connect(callback)
            timer.start(period)
            self.timers.append(timer)

        self.tx_running = True
        self.btn_start_tx.setText("Stop TX")
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaStop)
        )

    def stop_tx(self):
        for t in self.timers:
            t.stop()
        self.timers.clear()
        self.tx_running = False
        self.btn_start_tx.setText("Start TX")
        self.btn_start_tx.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay)
        )

    def make_timer_callback(self, frame_id, data, dlc, item=None):
        def callback():
            self.send_can_message(frame_id, data, dlc)
            if item:
                item.setText(5, " ".join(f"{b:02X}" for b in data))

        return callback

    def send_can_message(self, frame_id, data, dlc=None):
        if self.can_if:
            try:
                self.can_if.send_frame(frame_id, data, dlc)
            except Exception as e:
                print(f"Errore trasmissione CAN: {e}")
                log_exception(e)

    def process_received_frame(self, frame_id, data, dlc=None):
        try:
            self.rx_window.update_frame(frame_id, data, dlc)
        except Exception as e:
            log_exception(e)

    def open_xmetro_window(self):
        tx_items = []
        for i in range(self.signal_tree.topLevelItemCount()):
            item = self.signal_tree.topLevelItem(i)
            if item.checkState(1) == Qt.CheckState.Checked:
                tx_items.append(item)
        if not tx_items:
            QMessageBox.information(self, "XMetro", "Nessun messaggio TX abilitato.")
            return

        # Lista di finestre XMetro che sono state aperte
        # self.xmetro_windows = []

        xmetro = XMetroWindow(self.dbc, tx_items)
        xmetro.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        xmetro.show()
        self.xmetro_windows.append(xmetro)
        # Tiene traccia di quelle eliminate
        xmetro.destroyed.connect(lambda: self.xmetro_windows.remove(xmetro))


if __name__ == "__main__":
    import sys

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
