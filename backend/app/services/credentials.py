"""Encryption for credentials stored in the database (e.g. library API keys)."""
import base64

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings


class CredentialError(Exception):
    """A stored credential can't be decrypted (usually: the key changed)."""


def _fernet() -> Fernet:
    if settings.credentials_key:
        return Fernet(settings.credentials_key.encode())
    # Derive a separate key from SECRET_KEY so the raw signing key isn't reused
    derived = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=None, info=b"stacks:stored-credentials"
    ).derive(settings.secret_key.encode())
    return Fernet(base64.urlsafe_b64encode(derived))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise CredentialError(
            "Stored credential can't be decrypted; CREDENTIALS_KEY or SECRET_KEY may have changed. "
            "Re-enter it with `python -m app.cli configure-source`."
        ) from exc


def generate_key() -> str:
    return Fernet.generate_key().decode()
