# store/apps.py
from django.apps import AppConfig
import logging


class StoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "store"

    def ready(self):
        # Register system checks (non-fatal if missing)
        try:
            from . import checks  # noqa: F401
        except Exception as exc:
            logging.getLogger(__name__).warning("Store checks not loaded: %s", exc)
