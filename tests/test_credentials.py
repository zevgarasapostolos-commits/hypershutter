import subprocess

import pytest

from hypershutter.core import credentials


class FakeSecurity:
    def __init__(self):
        self.key, self.calls = None, []

    def __call__(self, argv, input=None, **kw):
        self.calls.append((argv, input))
        if argv[1] == "-i":
            self.key = input.split('-w "')[1].split('"')[0]
        elif argv[1] == "delete-generic-password":
            self.key = None
        elif self.key is None:
            return subprocess.CompletedProcess(argv, 44, "", "not found")
        return subprocess.CompletedProcess(argv, 0, f"{self.key}\n", "")


@pytest.fixture
def security(monkeypatch):
    fake = FakeSecurity()
    monkeypatch.setattr(credentials.subprocess, "run", fake)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    return fake


def test_the_key_never_appears_on_a_command_line(security):
    credentials.set_api_key("  sk-secret-value-123456  ")
    assert credentials.get_api_key() == "sk-secret-value-123456"
    assert all(a[0] == credentials.SECURITY for a, _ in security.calls)
    assert not any("sk-secret" in " ".join(a) for a, _ in security.calls)
    assert any(i and "sk-secret" in i for _, i in security.calls)


def test_no_key_stored_is_reported_as_not_set_up(security):
    assert credentials.get_api_key() is None
    with pytest.raises(credentials.NotSetUp):
        credentials.client()


def test_a_save_the_keychain_refused_is_an_error(security, monkeypatch):
    monkeypatch.setattr(credentials, "_stored", lambda: None)
    with pytest.raises(RuntimeError):
        credentials.set_api_key("sk-secret-value-123456")


def test_delete_removes_the_key(security):
    credentials.set_api_key("sk-secret-value-123456")
    credentials.delete_api_key()
    assert credentials.get_api_key() is None
