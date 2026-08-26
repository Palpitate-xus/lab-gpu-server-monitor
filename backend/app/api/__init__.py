from .auth import router as auth_router
from .users import router as users_router
from .servers import router as servers_router
from .server_test import router as server_test_router
from .metrics import router as metrics_router
from .alerts import router as alerts_router

__all__ = [
    "auth_router",
    "users_router",
    "servers_router",
    "server_test_router",
    "metrics_router",
    "alerts_router",
]
