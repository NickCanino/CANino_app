"""Phase 3 / sub-task 4 — TODO 1.10 (frames/s), 3.10 (hot reload), 3.11 (templates).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import os
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
import src.tx_panel as tx_panel  # noqa: E402
from src.received_frames_class import ReceivedFramesWindow  # noqa: E402

CONST_SCRIPT = (
    "VALUE = {v}\n" "def get_payload(dlc, id):\n" "    return bytes([VALUE]) * dlc\n"
)


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class FramesPerSecondTests(unittest.TestCase):
    def setUp(self):
        self.rx = ReceivedFramesWindow()

    def tearDown(self):
        h.dispose(self.rx)

    def test_counts_split_rx_and_own_echoes(self):
        for _ in range(3):
            self.rx.push_frame(0x100, b"\x01" * 8, 8, False)  # received
        self.rx.push_frame(
            0x100, b"\x01" * 8, 8, False, None, False, None, True
        )  # echo
        self.rx.drain()
        self.assertEqual(self.rx.take_frame_counts(), (3, 1))
        self.assertEqual(self.rx.take_frame_counts(), (0, 0))  # reset


class BusloadFramesLabelTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def test_label_shows_frames_per_second(self):
        import time

        class FakeIf:
            timing = gui.pcan_timing(gui.PCAN_BAUD_500K)
            is_fd = False

            def close(self):
                pass

        self.mw.can_if = FakeIf()
        for _ in range(100):
            self.mw.rx_window.push_frame(0x100, b"\x11" * 8, 8, False)
        self.mw._busload_since = time.monotonic() - 1.0
        self.mw.timer_busload_elapsed()
        text = self.mw.lbl_busload.text()
        self.assertIn("fr/s", text)
        self.assertIn("100 fr/s", text)

    def test_no_channel_resets_label(self):
        self.mw.can_if = None
        self.mw.timer_busload_elapsed()
        self.assertEqual(self.mw.lbl_busload.text(), "BusLoad: -")


class HotReloadTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()
        self.path = os.path.join(h.WORKDIR, "hot.py")

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def payload_for(self, entry):
        return self.mw._script_payload(entry)[0]

    def test_linked_script_reloads_when_the_file_changes(self):
        write(self.path, CONST_SCRIPT.format(v=1))
        entry = self.mw._add_tx_row(0x100, "A", dlc=4, script_path=self.path)
        self.assertEqual(self.payload_for(entry), b"\x01" * 4)
        # Edit the file; bump mtime so the change is unambiguous
        write(self.path, CONST_SCRIPT.format(v=2))
        os.utime(self.path, (0, self.mw._script_mtimes[self.path] + 5))
        self.mw._check_script_reloads()  # the GUI refresh step
        self.assertEqual(self.payload_for(entry), b"\x02" * 4)

    def test_unchanged_file_keeps_its_instance(self):
        write(
            self.path,
            "N = 0\ndef get_payload(dlc, id):\n global N\n N += 1\n return bytes([N]) * dlc\n",
        )
        entry = self.mw._add_tx_row(0x100, "A", dlc=2, script_path=self.path)
        self.assertEqual(self.payload_for(entry), b"\x01\x01")
        self.mw._check_script_reloads()  # no change -> state kept
        self.assertEqual(self.payload_for(entry), b"\x02\x02")  # counter advanced

    def test_global_script_hot_reloads(self):
        write(self.path, CONST_SCRIPT.format(v=7))
        self.mw.global_script_path = self.path
        entry = self.mw._add_tx_row(0x200, "B", dlc=3)
        self.assertEqual(self.payload_for(entry), b"\x07" * 3)
        write(self.path, CONST_SCRIPT.format(v=8))
        os.utime(self.path, (0, self.mw._script_mtimes[self.path] + 5))
        self.mw._check_script_reloads()
        self.assertEqual(self.payload_for(entry), b"\x08" * 3)


class TemplateTests(unittest.TestCase):
    def test_bundled_templates_are_listed(self):
        names = [n for n, _ in tx_panel.list_templates()]
        self.assertIn("TPS_random.py", names)
        self.assertIn("GLO_TPS_random.py", names)
        self.assertTrue(all(os.path.isfile(p) for _, p in tx_panel.list_templates()))

    def test_copy_template_adds_py_and_copies(self):
        src = dict(tx_panel.list_templates())["TPS_sawtooth.py"]
        dest = os.path.join(h.WORKDIR, "my_script")  # no extension
        out = tx_panel.copy_template(src, dest)
        self.assertEqual(out, dest + ".py")
        with open(out, encoding="utf-8") as f:
            self.assertIn("get_payload", f.read())


class NewFromTemplateDialogTests(unittest.TestCase):
    def setUp(self):
        self._orig = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        self.mw = gui.MainWindow()

    def tearDown(self):
        ci.CANInterface.get_available_channels = self._orig
        h.dispose(self.mw)

    def test_menu_action_creates_the_chosen_template(self):
        from PySide6.QtWidgets import QFileDialog, QInputDialog

        dest = os.path.join(h.WORKDIR, "from_menu.py")
        orig_item = QInputDialog.getItem
        orig_save = QFileDialog.getSaveFileName
        try:
            QInputDialog.getItem = staticmethod(
                lambda *a, **k: ("TPS_sawtooth.py", True)
            )
            QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (dest, ""))
            self.mw.new_script_from_template()
        finally:
            QInputDialog.getItem = orig_item
            QFileDialog.getSaveFileName = orig_save
        self.assertTrue(os.path.isfile(dest))
        self.assertEqual([d[0] for d in h.DIALOGS][-1], "information")

    def test_cancel_creates_nothing(self):
        from PySide6.QtWidgets import QFileDialog, QInputDialog

        before = set(os.listdir(h.WORKDIR))
        orig_item = QInputDialog.getItem
        orig_save = QFileDialog.getSaveFileName
        try:
            QInputDialog.getItem = staticmethod(lambda *a, **k: ("", False))
            QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: ("", ""))
            self.mw.new_script_from_template()
        finally:
            QInputDialog.getItem = orig_item
            QFileDialog.getSaveFileName = orig_save
        self.assertEqual(set(os.listdir(h.WORKDIR)), before)


if __name__ == "__main__":
    unittest.main()
