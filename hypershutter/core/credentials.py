"""The sorting service's key in the macOS Keychain (never in files, logs or the repo).

Always read and written through Apple's `security` tool. The Keychain item trusts that tool, which
stays the same however often the app is rebuilt, so macOS never asks for the login password. The
price of that silence: any program running as this user could ask `security` for the key as well.
"""

from __future__ import annotations

import os
import subprocess

SERVICE = "HyperShutter"
ACCOUNT = "sorting_service_key"
SECURITY = "/usr/bin/security"


class NotSetUp(RuntimeError):
    """No key is stored on this Mac."""


def _stored() -> str | None:
    try:
        r = subprocess.run([SECURITY, "find-generic-password", "-s", SERVICE, "-a", ACCOUNT, "-w"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def get_api_key() -> str | None:
    """Keychain first, then the environment (for development)."""
    return _stored() or os.environ.get("ANTHROPIC_API_KEY") or None


def set_api_key(key: str) -> None:
    """The key reaches `security` on stdin, so it never shows on a command line."""
    key = key.strip()
    if not key or any(c in key for c in '"\\\n'):
        raise ValueError("not a valid key")
    command = f'add-generic-password -U -s "{SERVICE}" -a "{ACCOUNT}" -T {SECURITY} -w "{key}"\n'
    subprocess.run([SECURITY, "-i"], input=command, capture_output=True, text=True, timeout=30)
    if _stored() != key:
        raise RuntimeError("the Keychain did not accept the key")


def delete_api_key() -> None:
    subprocess.run([SECURITY, "delete-generic-password", "-s", SERVICE, "-a", ACCOUNT],
                   capture_output=True, text=True, timeout=30)


def masked() -> str:
    key = get_api_key()
    return f"{key[:7]}…{key[-4:]}" if key and len(key) > 12 else "(none)"


def client():
    import anthropic

    key = get_api_key()
    if not key:
        raise NotSetUp("No key stored. Run `hypershutter key set` (stored in the macOS Keychain).")
    return anthropic.Anthropic(api_key=key, max_retries=4)
