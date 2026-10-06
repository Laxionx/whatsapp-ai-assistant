"""Validación de la firma X-Hub-Signature-256 y del token de administración."""

import hashlib
import hmac


def compute_signature(app_secret: str, body: bytes) -> str:
    digest = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(app_secret: str, body: bytes, header: str | None) -> bool:
    """Compara en tiempo constante; sin secreto o sin cabecera -> inválida."""
    if not app_secret or not header:
        return False
    return hmac.compare_digest(compute_signature(app_secret, body), header)


def tokens_match(expected: str, given: str) -> bool:
    """Igualdad en tiempo constante; un token esperado vacío nunca coincide."""
    if not expected:
        return False
    return hmac.compare_digest(expected.encode(), given.encode())
