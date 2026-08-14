#!/usr/bin/env python3
"""inscode2api 配置加载。

默认从 ~/.config/inscode/ 读取三个凭据文件（Windows 下即
C:\\Users\\<user>\\.config\\inscode\\）：
  - taotoken.json  免费额度：api_key / enabled_models / sign_key / model_meta
  - device.json    设备 ID
  - auth.json      登录态 access_token（JWT）

支持环境变量覆盖（详见 README「配置」一节）：
  INCODE2API_CONFIG_DIR   覆盖凭据目录
  INCODE2API_API_KEY      覆盖 api_key
  INCODE2API_BASE_URL     覆盖上游 base url（默认 https://taotoken.net）
  INCODE2API_HOST         监听地址（默认 127.0.0.1）
  INCODE2API_PORT         监听端口（默认 8000）
  INCODE2API_SKIP_SIGN    =1 时跳过签名直发上游（联调用）
  INCODE2API_PROXY        可选，显式指定 http(s) 代理；默认禁用系统代理

安全：任何位置都不打印完整密钥；`python config.py` 仅输出脱敏信息。
"""
from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

# 环境变量「名称」前缀。下面这些常量是 env 变量的名字（供 os.environ.get 读取），
# 不是凭据值；真正的凭据在运行时从 ~/.config/inscode/*.json 读取，绝无硬编码。
_ENV = "INCODE2API_"
ENV_CONFIG_DIR = _ENV + "CONFIG_DIR"
ENV_API_KEY = _ENV + "API_KEY"
ENV_BASE_URL = _ENV + "BASE_URL"
ENV_HOST = _ENV + "HOST"
ENV_PORT = _ENV + "PORT"
ENV_SKIP_SIGN = _ENV + "SKIP_SIGN"
ENV_PROXY = _ENV + "PROXY"

DEFAULT_BASE_URL = "https://taotoken.net"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

CONFIG_FILES = ("taotoken.json", "device.json", "auth.json")


@dataclass
class Config:
    base_url: str
    host: str
    port: int
    api_key: str
    key_id: str
    sign_key_b64: str
    sign_key_expire_at: str
    device_id: str
    skip_sign: bool
    config_dir: Path
    taotoken: dict
    device: dict
    auth: dict
    opener: object  # urllib opener，已按代理配置构建


def _env_flag(name: str) -> bool:
    v = (os.environ.get(name) or "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _build_opener(proxy_url: str | None):
    """构建 urllib opener。默认显式禁用系统代理（本机有 127.0.0.1:7890 系统
    代理时，urllib 默认会走它，导致连不上或行为异常）。"""
    if proxy_url:
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
    else:
        handler = urllib.request.ProxyHandler({})
    return urllib.request.build_opener(handler)


def load_config() -> Config:
    cfg_dir = Path(os.environ.get(ENV_CONFIG_DIR, Path.home() / ".config" / "inscode"))
    paths = {name: cfg_dir / name for name in CONFIG_FILES}

    missing = [name for name, p in paths.items() if not p.is_file()]
    if missing:
        raise FileNotFoundError(
            "凭据文件缺失：" + ", ".join(missing)
            + f"（目录：{cfg_dir}）。请先使用 InsCode 客户端登录，"
              "或用 INCODE2API_API_KEY 环境变量提供 api_key。"
        )

    def _load(name: str) -> dict:
        try:
            return json.loads(paths[name].read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"凭据文件 {paths[name]} 不是合法 JSON：{e}") from e

    taotoken = _load("taotoken.json")
    device = _load("device.json")
    auth = _load("auth.json")

    free = taotoken.get("free") or {}
    api_key = (os.environ.get(ENV_API_KEY) or free.get("api_key") or "").strip()
    if not api_key:
        raise ValueError("未找到 api_key（taotoken.json 的 free.api_key 或 INCODE2API_API_KEY）")

    sign_key = free.get("sign_key") or {}
    key_id = (sign_key.get("key_id") or "").strip()
    sign_key_b64 = (sign_key.get("sign_key") or "").strip()
    sign_key_expire_at = str(sign_key.get("expire_at") or "")
    device_id = (device.get("device_id") or "").strip()

    skip_sign = _env_flag(ENV_SKIP_SIGN)
    if not skip_sign and (not key_id or not sign_key_b64):
        raise ValueError(
            "需要签名但 taotoken.json 缺少 free.sign_key（key_id/sign_key）。"
            "若只想跑无需签名的端点，可设 INCODE2API_SKIP_SIGN=1。"
        )

    base_url = (os.environ.get(ENV_BASE_URL) or DEFAULT_BASE_URL).strip().rstrip("/")
    host = (os.environ.get(ENV_HOST) or DEFAULT_HOST).strip()
    port = int(os.environ.get(ENV_PORT) or DEFAULT_PORT)
    proxy = (os.environ.get(ENV_PROXY) or "").strip() or None

    return Config(
        base_url=base_url,
        host=host,
        port=port,
        api_key=api_key,
        key_id=key_id,
        sign_key_b64=sign_key_b64,
        sign_key_expire_at=sign_key_expire_at,
        device_id=device_id,
        skip_sign=skip_sign,
        config_dir=cfg_dir,
        taotoken=taotoken,
        device=device,
        auth=auth,
        opener=_build_opener(proxy),
    )


def redact(value, keep: int = 8, tail: int = 4) -> str:
    """脱敏：仅保留前后若干字符。"""
    s = str(value)
    if len(s) <= keep + 1:
        return s
    return s[:keep] + "…" + (s[-tail:] if tail else "")


if __name__ == "__main__":
    import sys
    try:
        c = load_config()
    except Exception as e:
        print(f"[config] 加载失败: {e}", file=sys.stderr)
        raise SystemExit(1) from e

    print("=== inscode2api 配置（脱敏） ===")
    print("config_dir       :", c.config_dir)
    print("base_url         :", c.base_url)
    print("host / port      :", f"{c.host}:{c.port}")
    print("api_key          :", redact(c.api_key))
    print("key_id           :", redact(c.key_id))
    print("sign_key(b64)    :", redact(c.sign_key_b64))
    print("sign_key_expire  :", c.sign_key_expire_at or "(无)")
    print("device_id        :", redact(c.device_id))
    print("skip_sign        :", c.skip_sign)
    print("enabled_models   :", (c.taotoken.get("free") or {}).get("enabled_models") or [])
    print("pros 数量         :", len(c.taotoken.get("pros") or []))
