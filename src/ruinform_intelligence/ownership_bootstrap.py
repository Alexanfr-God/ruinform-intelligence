"""Register RF-DEV-0.9 ownership routes without changing legacy transfer/sale modules."""

from .api import app
from .ownership_core import router

app.include_router(router)
