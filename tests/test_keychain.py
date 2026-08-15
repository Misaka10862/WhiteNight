"""Keychain 接口测试：内存后端 + 模拟 macOS 命令。"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

import pytest

from whitenight.credentials.keychain import InMemoryKeychain, KeychainError, MacOSKeychain


def test_in_memory_roundtrip() -> None:
    store = InMemoryKeychain()
    assert store.get("s", "a") is None
    store.set("s", "a", "secret")
    assert store.get("s", "a") == "secret"
    store.delete("s", "a")
    assert store.get("s", "a") is None


@dataclass
class _FakeResult:
    returncode: int
    stdout: str
    stderr: str


@pytest.fixture
def fake_security(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    calls: list[Any] = []
    store: dict[tuple[str, str], str] = {}

    def fake_run(cmd: list[str], **_kwargs: Any) -> _FakeResult:
        calls.append(cmd)
        action = cmd[1]
        service = cmd[cmd.index("-s") + 1]
        account = cmd[cmd.index("-a") + 1]
        if action == "find-generic-password":
            key = (service, account)
            if key in store:
                return _FakeResult(0, store[key] + "\n", "")
            return _FakeResult(44, "", "could not be found")
        if action == "add-generic-password":
            store[(service, account)] = cmd[cmd.index("-w") + 1]
            return _FakeResult(0, "", "")
        if action == "delete-generic-password":
            store.pop((service, account), None)
            return _FakeResult(0, "", "")
        return _FakeResult(1, "", "unknown")

    monkeypatch.setattr(subprocess, "run", fake_run)
    return calls


def test_macos_keychain_roundtrip(fake_security: list[Any]) -> None:
    keychain = MacOSKeychain(security_bin="/fake/security")
    assert keychain.get("svc", "acct") is None
    keychain.set("svc", "acct", "hunter2")
    assert keychain.get("svc", "acct") == "hunter2"
    keychain.delete("svc", "acct")
    assert keychain.get("svc", "acct") is None
    assert all(call[0] == "/fake/security" for call in fake_security)


def test_macos_keychain_get_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(_cmd: list[str], **_kwargs: Any) -> _FakeResult:
        return _FakeResult(1, "", "some keychain error")

    monkeypatch.setattr(subprocess, "run", fake_run)
    with pytest.raises(KeychainError):
        MacOSKeychain().get("s", "a")
