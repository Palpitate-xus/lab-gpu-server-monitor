from __future__ import annotations

import atexit
import os
import shutil
import sys
import tempfile


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO_ROOT)

TEST_ROOT = tempfile.mkdtemp(prefix="gpu-monitor-tests-")
atexit.register(shutil.rmtree, TEST_ROOT, True)

os.environ.update(
    {
        "DATA_DIR": os.path.join(TEST_ROOT, "data"),
        "DATABASE_URL": f"sqlite:///{TEST_ROOT}/test.db",
        "AUTO_MIGRATE": "yes",
        "JWT_SIGNING_KEY": "test-jwt-signing-key-000000000000000000000000000000",
        "CREDENTIAL_ENCRYPTION_KEYS": "test-credential-key-000000000000000000000000000000",
        "ARCHIVE_DIR": "",
        "COOKIE_SECURE": "no",
        "ALLOW_INSECURE_HTTP": "yes",
        "COOKIE_SAMESITE": "strict",
        "INIT_ADMIN_USERNAME": "security_admin",
        "INIT_ADMIN_PASSWORD": "security-admin-password-000000000000",
        "REMOTE_PROCESS_CONTROL_ENABLED": "no",
        "REQUIRE_ADMIN_MFA": "yes",
        "SECRET_KEY": "",
    }
)
