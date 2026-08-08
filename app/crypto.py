
from __future__ import annotations

import base64
import hashlib
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _key() -> bytes:
    configured = os.getenv("FIELD_ENCRYPTION_KEY", "").strip()
    if configured:
        try:
            raw = base64.urlsafe_b64decode(configured.encode("ascii"))
            if len(raw) == 32:
                return raw
        except Exception:
            pass
        raise RuntimeError("FIELD_ENCRYPTION_KEY debe ser base64 url-safe de 32 bytes.")

    # Compatibilidad de desarrollo: deriva una clave separada desde SECRET_KEY.
    # En producción define FIELD_ENCRYPTION_KEY de forma explícita.
    secret = os.getenv("SECRET_KEY", "development-only-change-me").encode("utf-8")
    return hashlib.sha256(b"ikercare-field-encryption-v2:" + secret).digest()


def encrypt_bytes(data: bytes, associated_data: bytes = b"ikercare-v2") -> bytes:
    nonce = os.urandom(12)
    encrypted = AESGCM(_key()).encrypt(nonce, data, associated_data)
    return nonce + encrypted


def decrypt_bytes(payload: bytes, associated_data: bytes = b"ikercare-v2") -> bytes:
    if len(payload) < 13:
        raise ValueError("Datos cifrados inválidos")
    nonce, encrypted = payload[:12], payload[12:]
    return AESGCM(_key()).decrypt(nonce, encrypted, associated_data)


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()
