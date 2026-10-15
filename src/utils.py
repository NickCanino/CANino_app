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
