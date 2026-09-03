"""Streaming authenticated encryption for metric archive tarballs."""

from __future__ import annotations

import os
import string
import tempfile
from typing import BinaryIO

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

MAGIC = b"GPMONAR1"
NONCE_SIZE = 12
TAG_SIZE = 16
CHUNK_SIZE = 1024 * 1024


def ensure_archive_storage(directory: str) -> None:
    """Create and probe the archive directory with restrictive permissions."""
    os.makedirs(directory, mode=0o700, exist_ok=True)
    if os.path.islink(directory) or not os.path.isdir(directory):
        raise RuntimeError("ARCHIVE_DIR must be a real directory")
    os.chmod(directory, 0o700)
    fd, probe = tempfile.mkstemp(prefix=".write-test-", dir=directory)
    try:
        os.fchmod(fd, 0o600)
        os.write(fd, b"probe")
        os.fsync(fd)
    finally:
        os.close(fd)
        os.unlink(probe)


def archive_storage_ready(directory: str) -> bool:
    try:
        ensure_archive_storage(directory)
        return True
    except Exception:
        return False


def _key_bytes(hex_key: str) -> bytes:
    if len(hex_key) != 64 or any(character not in string.hexdigits for character in hex_key):
        raise ValueError("archive encryption key must be exactly 64 hexadecimal characters")
    try:
        key = bytes.fromhex(hex_key)
    except ValueError as exc:
        raise ValueError("archive encryption key must be hexadecimal") from exc
    if len(key) != 32:
        raise ValueError("archive encryption key must contain exactly 32 bytes")
    return key


def encrypt_fileobj(source: BinaryIO, destination: str, hex_key: str) -> None:
    """Encrypt an already-open stream to a new named archive."""
    key = _key_bytes(hex_key)
    nonce = os.urandom(NONCE_SIZE)
    encryptor = Cipher(algorithms.AES(key), modes.GCM(nonce)).encryptor()
    encryptor.authenticate_additional_data(MAGIC + nonce)
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    succeeded = False
    try:
        with os.fdopen(fd, "wb", closefd=False) as dst:
            dst.write(MAGIC)
            dst.write(nonce)
            while chunk := source.read(CHUNK_SIZE):
                dst.write(encryptor.update(chunk))
            dst.write(encryptor.finalize())
            dst.write(encryptor.tag)
            dst.flush()
            os.fsync(dst.fileno())
        succeeded = True
    finally:
        os.close(fd)
        if not succeeded:
            try:
                os.unlink(destination)
            except FileNotFoundError:
                pass


def encrypt_file(source: str, destination: str, hex_key: str) -> None:
    with open(source, "rb") as src:
        encrypt_fileobj(src, destination, hex_key)


def decrypt_fileobj(source: str, destination: BinaryIO, hex_key: str) -> None:
    """Decrypt into an open private stream (typically an unnamed temp file)."""
    key = _key_bytes(hex_key)
    size = os.path.getsize(source)
    if size < len(MAGIC) + NONCE_SIZE + TAG_SIZE:
        raise ValueError("archive is truncated")
    with open(source, "rb") as src:
        magic = src.read(len(MAGIC))
        nonce = src.read(NONCE_SIZE)
        if magic != MAGIC:
            raise ValueError("archive is not a GPU Monitor encrypted archive")
        src.seek(-TAG_SIZE, os.SEEK_END)
        tag = src.read(TAG_SIZE)
        ciphertext_size = size - len(MAGIC) - NONCE_SIZE - TAG_SIZE
        src.seek(len(MAGIC) + NONCE_SIZE)
        decryptor = Cipher(algorithms.AES(key), modes.GCM(nonce, tag)).decryptor()
        decryptor.authenticate_additional_data(MAGIC + nonce)
        remaining = ciphertext_size
        while remaining:
            chunk = src.read(min(CHUNK_SIZE, remaining))
            if not chunk:
                raise ValueError("archive ciphertext is truncated")
            remaining -= len(chunk)
            destination.write(decryptor.update(chunk))
        destination.write(decryptor.finalize())
        destination.flush()
        os.fsync(destination.fileno())


def decrypt_file(source: str, destination: str, hex_key: str) -> None:
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    succeeded = False
    try:
        with os.fdopen(fd, "w+b", closefd=False) as dst:
            decrypt_fileobj(source, dst, hex_key)
        succeeded = True
    finally:
        os.close(fd)
        if not succeeded:
            try:
                os.unlink(destination)
            except FileNotFoundError:
                pass
