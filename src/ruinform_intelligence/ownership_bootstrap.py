"""Register RF-DEV-0.9 ownership routes without changing legacy transfer/sale modules."""

from .api import app
from .ownership_core import router
from . import ownership_wallets as _ownership_wallets  # noqa: F401,E402

app.include_router(router)
