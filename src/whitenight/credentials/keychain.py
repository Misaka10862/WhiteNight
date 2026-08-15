"""macOS Keychain 凭据接口。

数据库主密钥和服务凭据只进入 macOS Keychain，不落明文配置或日志。
`memory` 后端仅用于测试和 CI，生产配置不得使用。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Protocol

_SECURITY_BIN = "/usr/bin/security"
_NOT_FOUND_HINT = "could not be found"


class KeychainError(RuntimeError):
    """Keychain 操作失败。"""


class Keychain(Protocol):
    """凭据后端协议：Provider 可通过同一接口替换。"""

    def get(self, service: str, account: str) -> str | None:
        """读取密码；不存在时返回 None。"""

    def set(self, service: str, account: str, password: str) -> None:
        """写入或更新密码。"""

    def delete(self, service: str, account: str) -> None:
        """删除密码；不存在时视为成功。"""


@dataclass
class MacOSKeychain:
    """基于 ``/usr/bin/security`` 的 macOS 钥匙串实现。"""

    security_bin: str = _SECURITY_BIN

    def get(self, service: str, account: str) -> str | None:
        result = subprocess.run(
            [
                self.security_bin,
                "find-generic-password",
                "-s",
                service,
                "-a",
                account,
                "-w",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        if _NOT_FOUND_HINT in result.stderr.lower():
            return None
        raise KeychainError(
            f"读取 Keychain 失败 (service={service}, account={account}): "
            f"{result.stderr.strip() or result.returncode}"
        )

    def set(self, service: str, account: str, password: str) -> None:
        self.delete(service, account)
        result = subprocess.run(
            [
                self.security_bin,
                "add-generic-password",
                "-U",
                "-s",
                service,
                "-a",
                account,
                "-w",
                password,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise KeychainError(
                f"写入 Keychain 失败 (service={service}, account={account}): "
                f"{result.stderr.strip() or result.returncode}"
            )

    def delete(self, service: str, account: str) -> None:
        result = subprocess.run(
            [self.security_bin, "delete-generic-password", "-s", service, "-a", account],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 and _NOT_FOUND_HINT not in result.stderr.lower():
            raise KeychainError(
                f"删除 Keychain 条目失败 (service={service}, account={account}): "
                f"{result.stderr.strip() or result.returncode}"
            )


@dataclass
class InMemoryKeychain:
    """进程内凭据存储。仅用于测试与 CI，退出即丢失。"""

    _store: dict[tuple[str, str], str] = field(default_factory=dict)

    def get(self, service: str, account: str) -> str | None:
        return self._store.get((service, account))

    def set(self, service: str, account: str, password: str) -> None:
        self._store[(service, account)] = password

    def delete(self, service: str, account: str) -> None:
        self._store.pop((service, account), None)


def get_keychain(backend: str, service: str | None = None) -> Keychain:
    """按配置返回 Keychain 后端。`service` 参数保留给未来多用户隔离。"""
    del service  # 首版单用户，service 统一由配置提供
    if backend == "memory":
        return InMemoryKeychain()
    return MacOSKeychain()
