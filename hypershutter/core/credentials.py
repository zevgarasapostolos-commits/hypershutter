"""Anthropic API key in the macOS Keychain (never in files, logs or the repo)."""

from __future__ import annotations

import os

import keyring

SERVICE = "HyperShutter"
ACCOUNT = "anthropic_api_key"


def get_api_key() -> str | None:
    """Keychain first, then the environment (for development)."""
    try:
        key = keyring.get_password(SERVICE, ACCOUNT)
    except keyring.errors.KeyringError:
        key = None
    return key or os.environ.get("ANTHROPIC_API_KEY") or None


def set_api_key(key: str) -> None:
    keyring.set_password(SERVICE, ACCOUNT, key.strip())


def delete_api_key() -> None:
    try:
        keyring.delete_password(SERVICE, ACCOUNT)
    except keyring.errors.PasswordDeleteError:
        pass


def masked() -> str:
    key = get_api_key()
    return f"{key[:7]}…{key[-4:]}" if key and len(key) > 12 else "(none)"


def client():
    import anthropic

    key = get_api_key()
    if not key:
        raise RuntimeError("No API key. Run `hypershutter key set` (stored in the macOS Keychain).")
    return anthropic.Anthropic(api_key=key, max_retries=4)
