"""Хэширование токенов: в логах и БД не хранить сырое значение."""

import hashlib


def hash_token(plaintext: str, pepper: str) -> bytes:
    """SHA-256(pepper || 0-byte || plaintext UTF-8). Результат — 32 байта для колонки token_hash."""
    h = hashlib.sha256()
    h.update(pepper.encode("utf-8"))
    h.update(b"\x00")
    h.update(plaintext.encode("utf-8"))
    return h.digest()
