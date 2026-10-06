"""Fábrica de clientes HTTP (punto único para sustituirlo en los tests)."""

import httpx


def make_client(timeout: float = 10.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout)
