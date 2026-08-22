#!/usr/bin/env python3
"""Run idempotent, non-destructive stage 1 capability verification.

Checks the local platform, Ollama/models, Hermes, Codex, NapCat installation,
SQLCipher prototype, and a disposable macOS Keychain probe.

Usage:
    uv run scripts/verify_phase1.py
    uv run scripts/verify_phase1.py --smoke-model
    uv run scripts/verify_phase1.py --smoke-gateway

Writes a secret-free data/reports/phase1-*.json report and terminal summary.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "data" / "reports"
OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
MODEL_VL = "qwen3-vl:8b"
MODEL_TEXT = "qwen3:8b"
TIMEOUT = httpx.Timeout(15.0)
# 本脚本只探测本机服务。macOS 上 httpx 会读取系统代理配置（如 Clash），
# 导致 127.0.0.1 被代理劫持返回 502；本地探测必须 trust_env=False。
CLIENT = httpx.Client(timeout=TIMEOUT, trust_env=False)


@dataclass
class CheckResult:
    capability: str
    status: str  # ok | partial | blocked | skipped
    detail: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


def run_cmd(cmd: list[str], timeout: int = 60) -> tuple[int, str, str]:
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def probe_env() -> CheckResult:
    uname = run_cmd(["uname", "-m"])[1]
    mem_bytes = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    usage = shutil.disk_usage(ROOT)
    return CheckResult(
        "environment",
        "ok",
        f"arch={uname}, memory={mem_bytes / 1024**3:.1f} GiB, disk_free={usage.free / 1024**3:.1f} GiB",
        {
            "arch": uname,
            "memory_gib": round(mem_bytes / 1024**3, 1),
            "disk_free_gib": round(usage.free / 1024**3, 1),
        },
    )


def probe_ollama() -> CheckResult:
    evidence: dict[str, Any] = {}
    try:
        response = CLIENT.get(f"{OLLAMA_BASE}/api/version")
        response.raise_for_status()
        evidence["server_version"] = response.json().get("version")
    except Exception as exc:  # 探测脚本吞掉并报告
        return CheckResult("ollama", "blocked", f"Ollama service unavailable: {exc}", evidence)

    try:
        tags = CLIENT.get(f"{OLLAMA_BASE}/api/tags").json().get("models", [])
        evidence["models"] = [m["name"] for m in tags]
    except Exception as exc:
        return CheckResult("ollama", "partial", f"Unable to list models: {exc}", evidence)

    present = {name: any(m["name"] == name for m in tags) for name in (MODEL_TEXT, MODEL_VL)}
    evidence["required_models"] = present
    if present[MODEL_VL]:
        status, detail = (
            "ok",
            f"Server {evidence['server_version']}; {MODEL_VL} and {MODEL_TEXT} are ready",
        )
    elif present[MODEL_TEXT]:
        status, detail = (
            "partial",
            f"Server {evidence['server_version']}; only {MODEL_TEXT} is ready; {MODEL_VL} is missing",
        )
    else:
        status, detail = "blocked", "Ollama is reachable but required models are missing"
    return CheckResult("ollama", status, detail, evidence)


def make_test_png(path: Path, color: tuple[int, int, int] = (220, 40, 40)) -> Path:
    """生成 32x32 纯色 PNG，用于 VL 烟测。"""
    width = height = 32
    raw = b"".join(b"\x00" + bytes(color) * width for _ in range(height))

    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            len(data).to_bytes(4, "big") + kind + data + zlib.crc32(kind + data).to_bytes(4, "big")
        )

    ihdr = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2, 0, 0, 0])
    png = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    path.write_bytes(png)
    return path


def ollama_chat_latency(
    model: str, messages: list[dict[str, Any]], images: list[str] | None = None
) -> dict[str, Any]:
    """流式 chat，返回首 token / 首内容延迟与生成内容（截断）。"""
    if images:
        # Ollama 0.32 的 qwen3-vl 要求 images 挂在 user message 上，
        # 顶层 images 字段会被忽略（阶段 1 实测结论）。
        for index, message in reversed(list(enumerate(messages))):
            if message.get("role") == "user":
                messages[index] = {**message, "images": images}
                break
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "stream": True,
        # qwen3 文本模型支持顶层 think=False；qwen3-vl 当前模板忽略该开关，
        # 先输出 thinking，内容随后到达——烟测记录两个延迟以区分。
        "think": False,
        "options": {"num_predict": 512, "temperature": 0.0},
    }
    start = time.perf_counter()
    first_any_at: float | None = None
    first_content_at: float | None = None
    content_parts: list[str] = []
    thinking_parts: list[str] = []
    with (
        httpx.Client(timeout=httpx.Timeout(600.0, connect=10.0), trust_env=False) as client,
        client.stream("POST", f"{OLLAMA_BASE}/api/chat", json=payload) as response,
    ):
        response.raise_for_status()
        for line in response.iter_lines():
            if not line:
                continue
            chunk = json.loads(line)
            message = chunk.get("message", {})
            thinking = message.get("thinking") or ""
            content = message.get("content") or ""
            if first_any_at is None and (thinking or content):
                first_any_at = time.perf_counter() - start
            if thinking:
                thinking_parts.append(thinking)
            if content:
                if first_content_at is None:
                    first_content_at = time.perf_counter() - start
                content_parts.append(content)
            if chunk.get("done"):
                break
    total = time.perf_counter() - start
    return {
        "first_any_s": round(first_any_at, 2) if first_any_at else None,
        "first_content_s": round(first_content_at, 2) if first_content_at else None,
        "total_s": round(total, 2),
        "generated": "".join(content_parts)[:200],
        "thinking_prefix": "".join(thinking_parts)[:120],
    }


def ollama_tool_call_smoke(model: str) -> dict[str, Any]:
    """工具调用烟测：模型必须按 JSON Schema 返回 tool_calls。"""
    tool = {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "查询指定城市的天气",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
            },
        },
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "帮我查一下杭州的天气"}],
        "stream": False,
        "think": False,
        "tools": [tool],
        "options": {"temperature": 0.0},
    }
    start = time.perf_counter()
    response = CLIENT.post(
        f"{OLLAMA_BASE}/api/chat",
        json=payload,
        timeout=httpx.Timeout(300.0, connect=10.0),
    )
    elapsed = time.perf_counter() - start
    if response.status_code != 200:
        return {"error": f"HTTP {response.status_code}: {response.text[:200]}"}
    message = response.json().get("message", {})
    calls = message.get("tool_calls") or []
    return {
        "latency_s": round(elapsed, 2),
        "tool_calls": calls,
        "schema_ok": bool(
            calls
            and calls[0].get("function", {}).get("name") == "get_weather"
            and isinstance(calls[0].get("function", {}).get("arguments", {}).get("city"), str)
        ),
    }


def probe_ollama_smoke() -> CheckResult:
    base = probe_ollama()
    if base.status != "ok":
        return base
    evidence = dict(base.evidence)
    evidence["smoke"] = {}
    try:
        evidence["smoke"]["text"] = ollama_chat_latency(
            MODEL_TEXT,
            [{"role": "user", "content": "只回复两个字：好的"}],
        )
    except Exception as exc:
        evidence["smoke"]["text"] = {"error": str(exc)}

    try:
        with tempfile.TemporaryDirectory() as tmp:
            image = make_test_png(Path(tmp) / "red.png")
            encoded = base64.b64encode(image.read_bytes()).decode()
            evidence["smoke"]["vision"] = ollama_chat_latency(
                MODEL_VL,
                [{"role": "user", "content": "描述这张图片的内容，一句话。"}],
                images=[encoded],
            )
    except Exception as exc:
        evidence["smoke"]["vision"] = {"error": str(exc)}

    try:
        evidence["smoke"]["tools"] = ollama_tool_call_smoke(MODEL_TEXT)
    except Exception as exc:
        evidence["smoke"]["tools"] = {"error": str(exc)}

    text_ok = (
        isinstance(evidence["smoke"].get("text"), dict)
        and "first_content_s" in evidence["smoke"]["text"]
        and bool(evidence["smoke"]["text"].get("generated"))
    )
    vision_ok = (
        isinstance(evidence["smoke"].get("vision"), dict)
        and "first_content_s" in evidence["smoke"]["vision"]
        and bool(evidence["smoke"]["vision"].get("generated"))
    )
    tools_ok = bool(evidence["smoke"].get("tools", {}).get("schema_ok"))
    status = "ok" if text_ok and vision_ok and tools_ok else "partial"
    return CheckResult(
        "ollama-smoke",
        status,
        f"text={text_ok}, vision={vision_ok}, tools={tools_ok}",
        evidence,
    )


def probe_hermes() -> CheckResult:
    evidence: dict[str, Any] = {}
    code, version, err = run_cmd(["hermes", "--version"], timeout=30)
    if code != 0:
        return CheckResult("hermes", "blocked", f"Hermes unavailable: {err}", evidence)
    evidence["version"] = version
    code, _, _ = run_cmd(["hermes", "serve", "--help"], timeout=30)
    evidence["gateway_command"] = code == 0
    code, status, _ = run_cmd(["hermes", "computer-use", "status"], timeout=30)
    evidence["cua_driver_installed"] = "installed" in status.lower()
    if not evidence["cua_driver_installed"]:
        return CheckResult(
            "hermes",
            "partial",
            f"v{version}; Gateway command "
            f"{'available' if evidence['gateway_command'] else 'missing'}; cua-driver not installed",
            evidence,
        )
    return CheckResult(
        "hermes",
        "ok" if evidence["gateway_command"] else "partial",
        f"v{version}; Gateway command available; cua-driver: {status}",
        evidence,
    )


def probe_codex() -> CheckResult:
    evidence: dict[str, Any] = {}
    code, version, _ = run_cmd(["codex", "--version"], timeout=30)
    evidence["cli"] = code == 0
    if code == 0:
        evidence["version"] = version
    code, help_text, err = run_cmd(["codex", "mcp-server", "--help"], timeout=30)
    evidence["mcp_server"] = code == 0
    evidence["mcp_help_head"] = (help_text or err)[:120]
    auth_path = Path.home() / ".codex" / "auth.json"
    evidence["auth_file_present"] = auth_path.exists()
    status = (
        "ok"
        if evidence["cli"] and evidence["mcp_server"] and evidence["auth_file_present"]
        else "partial"
    )
    detail = (
        f"CLI={'yes' if evidence['cli'] else 'no'}, "
        f"mcp-server={'yes' if evidence['mcp_server'] else 'no'}, "
        f"auth={'yes' if evidence['auth_file_present'] else 'no'}"
    )
    return CheckResult("codex", status, detail, evidence)


def probe_napcat() -> CheckResult:
    # NapCat 官方分发不在 npm registry；安装需要下载与 QQ 扫码，由用户在阶段 8 前完成。
    found = shutil.which("napcat")
    return CheckResult(
        "napcat",
        "skipped" if not found else "ok",
        "Not installed (official download and QR login required); OneBot adapter is not blocked"
        if not found
        else f"found at {found}",
        {"binary": found},
    )


def probe_sqlcipher() -> CheckResult:
    evidence: dict[str, Any] = {}
    try:
        import sqlcipher3  # type: ignore[import-not-found]
    except ImportError:
        return CheckResult(
            "sqlcipher",
            "skipped",
            "Optional sqlcipher3 dependency missing; run uv sync --extra sqlcipher",
            evidence,
        )
    evidence["driver"] = sqlcipher3.sqlite_version
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "probe.db"
        connection = sqlcipher3.connect(str(db_path))
        cursor = connection.cursor()
        cursor.execute("PRAGMA key = 'probe-key-0123456789'")
        cursor.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT)")
        cursor.execute("INSERT INTO t (value) VALUES ('小白')")
        connection.commit()
        connection.close()

        # 正确密钥可读
        good = sqlcipher3.connect(str(db_path))
        good.execute("PRAGMA key = 'probe-key-0123456789'")
        value = good.execute("SELECT value FROM t").fetchone()[0]
        good.close()
        evidence["read_with_correct_key"] = value == "小白"

        # 错误密钥必须失败（验证确实加密，而非普通 SQLite 文件）
        bad = sqlcipher3.connect(str(db_path))
        try:
            bad.execute("PRAGMA key = 'wrong-key'")
            bad.execute("SELECT value FROM t").fetchone()
            evidence["wrong_key_rejected"] = False
        except Exception:
            evidence["wrong_key_rejected"] = True
        finally:
            bad.close()

    status = (
        "ok"
        if evidence.get("read_with_correct_key") and evidence.get("wrong_key_rejected")
        else "partial"
    )
    return CheckResult(
        "sqlcipher",
        status,
        "Encrypted read/write prototype verified" if status == "ok" else "Verification incomplete",
        evidence,
    )


def probe_keychain() -> CheckResult:
    from whitenight.credentials.keychain import MacOSKeychain

    service = "com.whitenight.phase1-probe"
    account = f"probe-{datetime.now(UTC).timestamp():.0f}"
    dummy = "phase1-probe-value"  # 一次性探针值，非真实凭据
    keychain = MacOSKeychain()
    try:
        keychain.set(service, account, dummy)
        read_back = keychain.get(service, account)
        return CheckResult(
            "keychain",
            "ok" if read_back == dummy else "partial",
            "macOS Keychain write/read/delete probe completed",
            {"roundtrip": read_back == dummy, "service": service},
        )
    finally:
        with contextlib.suppress(Exception):
            keychain.delete(service, account)


def probe_hermes_gateway() -> CheckResult:
    """启动 hermes serve 烟测：进程能监听端口并响应 HTTP。"""
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    with tempfile.NamedTemporaryFile(mode="w+", encoding="utf-8", errors="replace") as log_file:
        proc = subprocess.Popen(
            ["hermes", "serve", "--host", "127.0.0.1", "--port", str(port)],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            text=True,
        )
        try:
            deadline = time.time() + 300
            reachable = False
            status_code = None
            while time.time() < deadline:
                if proc.poll() is not None:
                    break
                try:
                    response = CLIENT.get(f"http://127.0.0.1:{port}/")
                    status_code = response.status_code
                    reachable = status_code < 500
                    if reachable:
                        break
                except Exception:
                    time.sleep(1)
            evidence = {
                "port": port,
                "http_reachable": reachable,
                "http_status": status_code,
                "exit_code": proc.poll(),
            }
            status = "ok" if reachable else "partial"
            return CheckResult(
                "hermes-gateway",
                status,
                "Gateway started and responded over HTTP"
                if reachable
                else "Gateway did not respond before timeout",
                evidence,
            )
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()


CHECKS = {
    "environment": probe_env,
    "ollama": probe_ollama,
    "hermes": probe_hermes,
    "codex": probe_codex,
    "napcat": probe_napcat,
    "sqlcipher": probe_sqlcipher,
    "keychain": probe_keychain,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="WhiteNight stage 1 capability verification")
    parser.add_argument("--smoke-model", action="store_true", help="Run live text/vision inference")
    parser.add_argument(
        "--smoke-gateway", action="store_true", help="Start a Hermes Gateway smoke test"
    )
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args()

    results: list[dict[str, Any]] = []
    for name, probe in CHECKS.items():
        try:
            results.append(asdict(probe()))
        except Exception as exc:
            results.append(asdict(CheckResult(name, "blocked", f"Probe failed: {exc}")))

    if args.smoke_model:
        results.append(asdict(probe_ollama_smoke()))
    if args.smoke_gateway:
        results.append(asdict(probe_hermes_gateway()))

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = REPORT_DIR / f"phase1-{timestamp}.json"
    report = {"generated_at": timestamp, "results": results}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        for item in results:
            print(f"[{item['status']:7}] {item['capability']}: {item['detail']}")
        print(f"\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
