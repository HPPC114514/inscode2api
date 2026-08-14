#!/usr/bin/env python3
"""inscode2api 入口：本地 OpenAI 兼容代理服务。

端点：
  GET  /healthz               健康检查
  GET  /v1/models             OpenAI 格式模型列表（转发 taotoken）
  POST /v1/chat/completions   聊天补全（转发，stream=true 时 SSE 逐块转发）

线程模型：ThreadingHTTPServer，每连接一线程，支持并发流式连接。
健壮性：上游超时/连接失败/非 2xx 一律映射为 OpenAI 风格错误 JSON，不会崩进程。
"""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import config
import oai
import upstream


class ProxyHandler(BaseHTTPRequestHandler):
    server_version = "inscode2api/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def cfg(self):
        return self.server.cfg

    # ---------- 基础 IO ----------

    def _read_body(self) -> bytes:
        te = (self.headers.get("Transfer-Encoding") or "").lower()
        if "chunked" in te:
            return self._read_chunked_body()
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return b""
        return self.rfile.read(length)

    def _read_chunked_body(self) -> bytes:
        data = bytearray()
        while True:
            size_line = self.rfile.readline().strip()
            if not size_line:
                break
            try:
                size = int(size_line, 16)
            except ValueError:
                break
            if size == 0:
                self.rfile.readline()  # 吃掉结尾 CRLF
                break
            data += self.rfile.read(size)
            self.rfile.readline()      # 吃掉分块后的 CRLF
        return bytes(data)

    def _read_json_body(self) -> dict:
        raw = self._read_body()
        if not raw.strip():
            raise ValueError("empty request body")
        obj = json.loads(raw.decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("request body must be a JSON object")
        return obj

    def _send_bytes(self, status: int, body: bytes,
                    content_type: str = "application/json",
                    extra_headers: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status: int, obj: dict,
                   extra_headers: dict | None = None) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, extra_headers=extra_headers)

    def _send_error(self, status: int, message: str, code: str | None = None) -> None:
        self._send_json(status, oai.error_payload(status, message, code=code))

    def _send_sse(self, lines) -> None:
        """以 chunked 编码逐块转发上游 SSE 行（data: [DONE] 透传）。"""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
            for line in lines:
                b = line if isinstance(line, bytes) else str(line).encode("utf-8")
                if not b:
                    continue
                self.wfile.write(("%x\r\n" % len(b)).encode("ascii") + b + b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass  # 客户端断开即停止转发，不崩线程

    # ---------- 路由 ----------

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/healthz":
            self._send_json(200, {"status": "ok", "service": "inscode2api"})
            return
        if path == "/v1/models":
            self._handle_models()
            return
        self._send_error(404, f"unknown path: {self.path}", code="not_found")

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/v1/chat/completions":
            self._handle_chat()
            return
        self._send_error(404, f"unknown path: {self.path}", code="not_found")

    # ---------- 端点实现 ----------

    def _handle_models(self) -> None:
        try:
            status, body = upstream.models_list(self.cfg)
        except upstream.UpstreamConnectionError as e:
            self._send_error(502, f"upstream unreachable: {e}",
                             code="upstream_connection_error")
            return
        except Exception as e:
            self._log_exc("GET /v1/models", e)
            self._send_error(500, f"internal error: {e}", code="internal_error")
            return
        if 200 <= status < 300:
            try:
                payload = json.loads(body.decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                self._send_error(502, "upstream returned non-JSON body",
                                 code="upstream_bad_response")
                return
            self._send_json(200, oai.taotoken_models_to_openai(payload))
        else:
            st, err = oai.upstream_error_payload(status, body)
            self._send_json(st, err)

    def _handle_chat(self) -> None:
        try:
            payload = self._read_json_body()
        except (ValueError, json.JSONDecodeError) as e:
            self._send_error(400, f"invalid request body: {e}", code="invalid_request")
            return
        try:
            payload = oai.normalize_chat_request(payload)
        except ValueError as e:
            self._send_error(400, str(e), code="invalid_request")
            return

        stream = bool(payload.get("stream"))
        try:
            status, resp_body, lines = upstream.chat(self.cfg, payload, stream=stream)
        except upstream.UpstreamConnectionError as e:
            self._send_error(502, f"upstream unreachable: {e}",
                             code="upstream_connection_error")
            return
        except Exception as e:
            self._log_exc("POST /v1/chat/completions", e)
            self._send_error(500, f"internal error: {e}", code="internal_error")
            return

        if lines is not None:
            self._send_sse(lines)
            return
        if 200 <= status < 300:
            self._send_bytes(status, resp_body, content_type="application/json")
            return
        st, err = oai.upstream_error_payload(status, resp_body)
        self._send_json(st, err)

    # ---------- 日志 ----------

    def _log_exc(self, where: str, exc: Exception) -> None:
        self.log_error("%s failed: %r", where, exc)


def main() -> None:
    try:
        cfg = config.load_config()
    except Exception as e:
        print(f"[inscode2api] 配置加载失败: {e}", file=sys.stderr)
        raise SystemExit(1) from e

    httpd = ThreadingHTTPServer((cfg.host, cfg.port), ProxyHandler)
    httpd.daemon_threads = True
    httpd.cfg = cfg
    print(f"[inscode2api] listening on http://{cfg.host}:{cfg.port}")
    print(f"[inscode2api] upstream: {cfg.base_url}  skip_sign={cfg.skip_sign}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[inscode2api] shutting down")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
