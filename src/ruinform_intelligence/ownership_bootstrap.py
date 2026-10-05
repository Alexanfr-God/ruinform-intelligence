"""Register RF-DEV ownership routes and internal infrastructure bridges."""

from .api import app
from .ownership_core import router
from .solana_devnet_rpc import router as solana_devnet_rpc_router
from . import ownership_wallets as _ownership_wallets  # noqa: F401,E402

app.include_router(router)
app.include_router(solana_devnet_rpc_router)
