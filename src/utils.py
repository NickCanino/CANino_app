import sys, os

def resource_path(relative_path):
    """Ottieni il path assoluto della risorsa (compatibile con PyInstaller)."""
    try:
        base_path = sys._MEIPASS
    except AttributeError:
        base_path = os.path.dirname(os.path.abspath(__file__))
        
    return os.path.join(base_path, relative_path)
