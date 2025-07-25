import logging
import datetime

from src.version import __version__

# Crea un nome file log con data e ora
log_time = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = f"canino_app_v{__version__}_{log_time}.log"

logging.basicConfig(
    filename=log_filename,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def log_exception(e):
    logging.error("Exception occurred", exc_info=e)
