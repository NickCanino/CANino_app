import sys
import os


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_path(relative_path):
    """Absolute path of a bundled resource, given relative to the repo root.

    Frozen (PyInstaller): relative to sys._MEIPASS. From source: relative to the
    repo root, not to src/ (resources/ and tools/ live at the top level).
    """
    base_path = getattr(sys, "_MEIPASS", REPO_ROOT)
    return os.path.join(base_path, relative_path)


def format_can_id(frame_id: int, is_ext: bool = False) -> str:
    """0x123 for 11-bit IDs, 0x00000123 for 29-bit ones (PCAN-View style).

    The width alone tells a standard and an extended frame with the same
    number apart, in the TX and RX tables and in the CSV.
    """
    return f"0x{frame_id:08X}" if is_ext else f"0x{frame_id:03X}"
