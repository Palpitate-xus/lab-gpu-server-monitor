"""Re-encrypt stored SSH/BMC/MFA secrets with the primary credential key.

Configure CREDENTIAL_ENCRYPTION_KEYS as ``new_key,old_key``. Run without
``--apply`` first; the dry run verifies that every non-empty secret can be
decrypted. After a successful apply and backup/restore check, remove the old
key from the keyring.
"""

from __future__ import annotations

import argparse
import os
import sys

from cryptography.fernet import Fernet, InvalidToken

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from app.config import get_settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402
from app.models import Server, Setting, User, WebhookChannel  # noqa: E402
from app.notifier import WEBHOOK_ENCRYPTED_PREFIX  # noqa: E402
from app.security import _derive_key, decrypt_text, encrypt_text  # noqa: E402


def _uses_primary(ciphertext: str, primary: Fernet) -> bool:
    try:
        primary.decrypt(ciphertext.encode())
        return True
    except InvalidToken:
        return False


def main(apply: bool) -> None:
    keys = get_settings().credential_encryption_keys
    if not keys:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEYS is not configured")
    primary = Fernet(_derive_key(keys[0]))
    db = SessionLocal()
    checked = rotated = 0
    try:
        targets: list[tuple[object, str, str]] = []
        for server in db.query(Server).order_by(Server.id):
            targets.extend(
                (server, field, "")
                for field in ("password", "private_key", "passphrase", "bmc_password")
            )
        for user in db.query(User).order_by(User.id):
            targets.append((user, "mfa_secret", ""))
        for channel in db.query(WebhookChannel).order_by(WebhookChannel.id):
            targets.append((channel, "url", WEBHOOK_ENCRYPTED_PREFIX))
        legacy_webhook = db.get(Setting, "alert_webhook_url")
        if legacy_webhook is not None:
            targets.append((legacy_webhook, "value", WEBHOOK_ENCRYPTED_PREFIX))

        for model, field, prefix in targets:
            ciphertext = getattr(model, field) or ""
            if not ciphertext:
                continue
            checked += 1
            if prefix and not ciphertext.startswith(prefix):
                # A pre-hardening plaintext webhook URL is encrypted on apply.
                rotated += 1
                if apply:
                    setattr(model, field, prefix + encrypt_text(ciphertext))
                continue
            token = ciphertext.removeprefix(prefix) if prefix else ciphertext
            if _uses_primary(token, primary):
                continue
            # This verifies the complete configured keyring before any commit.
            plaintext = decrypt_text(token)
            rotated += 1
            if apply:
                setattr(model, field, prefix + encrypt_text(plaintext))

        if apply:
            db.commit()
        else:
            db.rollback()
        print(
            f"credential rotation {'applied' if apply else 'dry-run'}: "
            f"checked={checked}, rotate={rotated}"
        )
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    main(args.apply)
