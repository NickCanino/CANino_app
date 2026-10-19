"""Phase 1 / sub-task 7 — TODO 7.2, 7.3, 7.4, 7.5, 7.6, 4.11 (XMetro).

Run from the repo root:  python -m unittest discover -s tests -v
"""

import threading
import unittest

import qt_harness as h  # noqa: F401  (must come before src imports)

from PySide6.QtCore import QCoreApplication, QEvent  # noqa: E402

import src.can_interface as ci  # noqa: E402
import src.gui as gui  # noqa: E402
import src.dbc_loader as dbc_loader  # noqa: E402
from test_tx_engine import FakeIf  # noqa: E402

# STD_A and EXT_A share the number 0x100
DBC = """VERSION ""
NS_ :
BS_:
BU_: ECU
BO_ 256 STD_A: 8 ECU
 SG_ SIG_X : 0|8@1+ (1,0) [0|100] "km/h" ECU
 SG_ SIG_MODE : 8|8@1+ (1,0) [0|3] "" ECU
BO_ 2147483904 EXT_A: 8 ECU
 SG_ SIG_E : 0|8@1+ (1,0) [0|255] "" ECU
VAL_ 256 SIG_MODE 0 "OFF" 1 "ON" 2 "AUTO" ;
"""


class Base(unittest.TestCase):
    def setUp(self):
        h.DIALOGS.clear()
        self._orig_scan = ci.CANInterface.get_available_channels
        ci.CANInterface.get_available_channels = staticmethod(lambda: [])
        with open("xm.dbc", "w", encoding="utf-8") as f:
            f.write(DBC)
        self.mw = gui.MainWindow()
        self.mw.dbc = dbc_loader.load_dbc("xm.dbc")

    def tearDown(self):
        self.mw.stop_tx()
        self.mw.can_if = None
        ci.CANInterface.get_available_channels = self._orig_scan
        self.mw.close()

    def gauge(self, msg_name, sig_name):
        if not self.mw.xmetro_windows:
            self.mw.open_xmetro_window()
        window = self.mw.xmetro_windows[-1]
        window.add_gauge()
        g = window.gauges[-1]
        g.cb_messages.setCurrentIndex(
            next(i for i, m in enumerate(g.messages) if m.name == msg_name)
        )
        g.cb_signals.setCurrentIndex(g.cb_signals.findText(sig_name))
        return window, g

    def rx(self, frame_id, data, is_ext=False):
        t = threading.Thread(
            target=self.mw.rx_window.push_frame,
            args=(frame_id, data, len(data), False, None, is_ext),
        )
        t.start()
        t.join()
        self.mw.rx_window.drain()


class FeedTests(Base):
    def test_transmitted_frames_feed_the_gauge(self):
        """7.2: a gauge follows a row CANino transmits, not only received frames."""
        _, g = self.gauge("STD_A", "SIG_X")
        self.mw._add_tx_row(0x100, "STD_A", payload="2A 00 00 00 00 00 00 00")
        self.mw.can_if = FakeIf()
        self.mw.start_stop_transmission()
        h.fire_tx(self.mw)
        self.assertEqual(g.gauge.value, 42)

    def test_std_and_ext_with_the_same_number_stay_apart(self):
        """4.11: the EXT_A gauge ignores std 0x100 frames and vice versa."""
        _, g_std = self.gauge("STD_A", "SIG_X")
        _, g_ext = self.gauge("EXT_A", "SIG_E")
        self.rx(0x100, bytes([11] + [0] * 7), is_ext=False)
        self.rx(0x100, bytes([99] + [0] * 7), is_ext=True)
        self.assertEqual((g_std.gauge.value, g_ext.gauge.value), (11, 99))

    def test_short_payload_does_not_break_the_gauge(self):
        """7.3: a frame shorter than the DBC message no longer raises in decode."""
        _, g = self.gauge("STD_A", "SIG_MODE")
        self.rx(0x100, bytes([5]))
        self.assertEqual(g.gauge.value, 0)


class GaugeTests(Base):
    def test_range_from_dbc_and_needle_clamped(self):
        """7.3: scale = DBC [0|100]; 200 km/h parks the needle at the end."""
        _, g = self.gauge("STD_A", "SIG_X")
        self.assertEqual((g.gauge.min_val, g.gauge.max_val), (0, 100))
        self.rx(0x100, bytes([200] + [0] * 7))
        self.assertEqual(g.gauge.value, 200)
        self.assertEqual(g.gauge.needle_ratio(), 1.0)
        g.gauge.grab()  # paintEvent with an out-of-range value

    def test_zero_span_does_not_divide_by_zero(self):
        g = gui.XMetroWindow.__mro__[0]  # noqa: F841  (module import check)
        from src.xmetro_class import SemiCircularGauge

        gauge = SemiCircularGauge()
        gauge.setRange(5, 5)
        gauge.setValue(5)
        self.assertEqual(gauge.needle_ratio(), 0.0)
        gauge.resize(300, 200)
        gauge.grab()

    def test_enum_value_shows_its_name(self):
        """7.3: enum signals draw the number and its DBC text."""
        _, g = self.gauge("STD_A", "SIG_MODE")
        self.rx(0x100, bytes([0, 2] + [0] * 6))
        self.assertEqual((g.gauge.value, g.gauge.label), (2, "AUTO"))
        g.gauge.grab()

    def test_tooltips(self):
        """7.6: the gauge and its controls explain themselves."""
        window, g = self.gauge("STD_A", "SIG_X")
        self.assertIn("SIG_X", g.toolTip())
        self.assertIn("km/h", g.toolTip())
        self.assertTrue(g.cb_messages.toolTip() and g.cb_signals.toolTip())


class WindowTests(Base):
    def test_remove_gauge_frees_its_cell(self):
        """7.4: a removed gauge's cell is reused by the next Add Gauge."""
        window, g1 = self.gauge("STD_A", "SIG_X")
        _, g2 = self.gauge("STD_A", "SIG_MODE")
        cell = (g1.row, g1.col)
        window.remove_gauge(g1)
        self.assertEqual(window.gauges, [g2])
        window.add_gauge()
        self.assertEqual((window.gauges[-1].row, window.gauges[-1].col), cell)

    def test_window_method_not_shadowed(self):
        """7.4: QWidget.window() works again on a gauge box."""
        window, g = self.gauge("STD_A", "SIG_X")
        self.assertIs(g.window(), window)
        self.assertIs(g.xmetro, window)

    def test_closed_window_leaves_the_list(self):
        """7.5: a closed XMetro window is forgotten, so RX stops feeding it."""
        window, _ = self.gauge("STD_A", "SIG_X")
        window.close()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        QCoreApplication.processEvents()
        self.assertEqual(self.mw.xmetro_windows, [])


if __name__ == "__main__":
    unittest.main()
