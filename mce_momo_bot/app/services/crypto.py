"""
Mijoz bot tokenlarini shifrlash/deshifrlash (Fernet, symmetric encryption).
Tokenlar DB'da hech qachon ochiq (plaintext) saqlanmaydi.
"""
from __future__ import annotations

from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import settings


@lru_cache
def _fernet() -> Fernet:
    if not settings.token_encryption_key:
        raise RuntimeError(
            "TOKEN_ENCRYPTION_KEY sozlanmagan. .env faylida kalit belgilang "
            "(generatsiya: python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\")"
        )
    return Fernet(settings.token_encryption_key.encode())


def encrypt_token(raw_token: str) -> str:
    return _fernet().encrypt(raw_token.encode()).decode()


def decrypt_token(encrypted_token: str) -> str:
    return _fernet().decrypt(encrypted_token.encode()).decode()
