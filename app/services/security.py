from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


HASH_ALGORITHM = "pbkdf2_sha256"
HASH_ITERATIONS = 240_000


def generate_secret(slug: str) -> str:
    return f"cyber-{slug}-{secrets.token_urlsafe(6)}"


def hash_secret(secret: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, HASH_ITERATIONS)
    return (
        f"{HASH_ALGORITHM}${HASH_ITERATIONS}"
        f"${base64.urlsafe_b64encode(salt).decode('utf-8')}"
        f"${base64.urlsafe_b64encode(digest).decode('utf-8')}"
    )


def verify_secret(secret: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations, salt_b64, digest_b64 = stored_hash.split("$", 3)
    except ValueError:
        return False
    if algorithm != HASH_ALGORITHM:
        return False
    salt = base64.urlsafe_b64decode(salt_b64.encode("utf-8"))
    expected = base64.urlsafe_b64decode(digest_b64.encode("utf-8"))
    candidate = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, int(iterations))
    return hmac.compare_digest(candidate, expected)


def _keystream(operator_secret: str, length: int) -> bytes:
    seed = operator_secret.encode("utf-8")
    output = bytearray()
    counter = 0
    while len(output) < length:
        output.extend(hashlib.sha256(seed + counter.to_bytes(4, "big")).digest())
        counter += 1
    return bytes(output[:length])


def seal_secret(secret: str, operator_secret: str) -> str:
    raw = secret.encode("utf-8")
    mask = _keystream(operator_secret, len(raw))
    sealed = bytes(left ^ right for left, right in zip(raw, mask, strict=True))
    return base64.urlsafe_b64encode(sealed).decode("utf-8")


def unseal_secret(sealed_secret: str, operator_secret: str) -> str:
    raw = base64.urlsafe_b64decode(sealed_secret.encode("utf-8"))
    mask = _keystream(operator_secret, len(raw))
    unsealed = bytes(left ^ right for left, right in zip(raw, mask, strict=True))
    return unsealed.decode("utf-8")


def issue_secret_material(slug: str, operator_secret: str) -> tuple[str, str, str]:
    secret = generate_secret(slug)
    return secret, hash_secret(secret), seal_secret(secret, operator_secret)
