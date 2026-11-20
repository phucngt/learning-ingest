"""Gọi API tương thích OpenAI; cấu hình không làm đổi os.environ."""
from __future__ import annotations

import json
import http.client
import math
import os
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from .errors import IngestError, RemoteError

PROVIDERS = {
    "fpt": {
        "name": "FPT.AI",
        "prefix": "FPT",
        "base_url": "https://token-api.fpt.ai/v1",
        "model": "GLM-5.3-Flash",
        "reasoning_effort": "low",
    }
}
RETRY_BACKOFF_SECONDS = (2, 8)
STREAM_PROGRESS_SECONDS = 30


@dataclass(frozen=True)
class Config:
    provider: str
    api_key: str = field(repr=False)
    endpoint: str
    model: str
    max_tokens: int | None
    temperature: float
    json_mode: bool
    timeout: float
    ca_bundle: str | None = None
    reasoning_effort: str | None = None


def redact(text: str, key: str) -> str:
    return text.replace(key, "[REDACTED]") if key else text


def _env_values(path: Path) -> dict[str, str]:
    values = {}
    if path.is_file():
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except (OSError, UnicodeError):
            raise IngestError("Không đọc được file cấu hình môi trường.") from None
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            if "=" not in line:
                continue
            name, value = line.split("=", 1)
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[name.strip()] = value
    return values


def load_config(*, provider="fpt", model=None, timeout=None, env_file=Path(".env")) -> Config:
    if provider not in PROVIDERS:
        raise IngestError("Provider không được hỗ trợ.")
    values = _env_values(Path(env_file))
    prefix = PROVIDERS[provider]["prefix"]
    def setting(name, default=""):
        setting_name = prefix + "_" + name
        return os.environ.get(setting_name, values.get(setting_name, default))
    key = setting("API_KEY").strip()
    if not key:
        raise IngestError("Thiếu FPT_API_KEY; cấu hình trong môi trường hoặc file .env.")
    if "\r" in key or "\n" in key:
        raise IngestError("API key không hợp lệ.")
    base = setting("BASE_URL", PROVIDERS[provider]["base_url"]).strip().rstrip("/")
    try:
        url = urllib.parse.urlsplit(base)
        valid = (url.scheme == "https" or
                 (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}))
        if not valid or not url.hostname or url.username or url.password or url.query or url.fragment or any(ord(c) < 32 for c in base):
            raise ValueError
        _ = url.port
    except ValueError:
        raise IngestError("FPT_BASE_URL phải là HTTPS hoặc HTTP loopback (localhost, 127.0.0.1, ::1).") from None
    chosen_model = model if model is not None else setting("MODEL", PROVIDERS[provider]["model"])
    if not chosen_model or key in chosen_model or key in base:
        raise IngestError("Cấu hình model hoặc endpoint không hợp lệ.")
    try:
        max_tokens = int(setting("MAX_TOKENS")) if setting("MAX_TOKENS") else None
        temperature = float(setting("TEMPERATURE", "0.2"))
        seconds = float(timeout if timeout is not None else setting("TIMEOUT", "600"))
        if (max_tokens is not None and max_tokens <= 0) or not math.isfinite(temperature) or temperature < 0 or not math.isfinite(seconds) or seconds <= 0:
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise IngestError("FPT_MAX_TOKENS phải là số nguyên dương; temperature và timeout phải là số hợp lệ (timeout > 0).") from None
    reasoning_effort = setting("REASONING_EFFORT", PROVIDERS[provider]["reasoning_effort"])
    if reasoning_effort not in {"low", "high", "max", "none", ""}:
        raise IngestError("FPT_REASONING_EFFORT chỉ nhận low, high, max, none hoặc giá trị rỗng.")
    return Config(provider, key, base + "/chat/completions", chosen_model, max_tokens,
                  temperature, setting("JSON_MODE").lower() in {"1", "true"},
                  seconds, setting("CA_BUNDLE") or None,
                  reasoning_effort=reasoning_effort if reasoning_effort not in {"none", ""} else None)


def _ssl_context(ca_bundle=None):
    cafile = ca_bundle
    if not cafile:
        try:
            import certifi
        except ImportError:
            pass
        else:
            cafile = certifi.where()
    try:
        return ssl.create_default_context(cafile=cafile)
    except (OSError, ssl.SSLError):
        raise RemoteError("Không nạp được chứng chỉ TLS; kiểm tra FPT_CA_BUNDLE.") from None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _has_key(value, key: str) -> bool:
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str) and key in item:
            return True
        if isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def _stream_lines(response: http.client.HTTPResponse) -> Iterable[bytes]:
    # Iterating HTTPResponse can hide broken HTTP chunk framing as a clean EOF.
    pending = bytearray()
    while chunk := response.read1(64 * 1024):
        *lines, tail = chunk.split(b"\n")
        if lines and pending:
            pending.extend(lines[0])
            lines[0] = bytes(pending)
            pending.clear()
        yield from lines
        pending.extend(tail)
    if pending:
        yield bytes(pending)


def _stream_completion(lines: Iterable[bytes]) -> dict:
    content_parts = []
    content_chars = reasoning_chars = 0
    finish_reason = None
    done = False
    result = {}
    started = last_progress = time.monotonic()
    for line in lines:
        if line.startswith(b"data:"):
            data = line[5:].strip()
            if data == b"[DONE]":
                done = True
                break
            try:
                chunk = json.loads(data.decode("utf-8"))
            except (ValueError, RecursionError):
                raise RemoteError("API trả về luồng phản hồi không hợp lệ.") from None
            if not isinstance(chunk, dict):
                raise RemoteError("API trả về luồng phản hồi không hợp lệ.")
            if "usage" in chunk:
                result["usage"] = chunk["usage"]
            choices = chunk.get("choices")
            if isinstance(choices, list) and choices and isinstance(choices[0], dict):
                choice = choices[0]
                if choice.get("finish_reason") is not None:
                    finish_reason = choice["finish_reason"]
                delta = choice.get("delta")
                if isinstance(delta, dict):
                    content = delta.get("content")
                    if isinstance(content, str):
                        content_parts.append(content)
                        content_chars += len(content)
                    reasoning = delta.get("reasoning_content")
                    if isinstance(reasoning, str):
                        reasoning_chars += len(reasoning)
        now = time.monotonic()
        if now - last_progress >= STREAM_PROGRESS_SECONDS:
            print(f"Đang nhận phản hồi ({now - started:.0f} giây, {reasoning_chars} ký tự suy luận, "
                  f"{content_chars} ký tự nội dung).", file=sys.stderr, flush=True)
            last_progress = now
    result.update(
        choices=[{"message": {"content": "".join(content_parts)}, "finish_reason": finish_reason}],
        reasoning_chars=reasoning_chars,
    )
    if not done and finish_reason is None:
        result.update(stream_incomplete=True, elapsed_seconds=float(time.monotonic() - started))
    return result


def request_completion(config: Config, user_text: str) -> dict:
    system = ("Bạn là trợ lý biên soạn điểm kiến thức. Chỉ trả về đúng một đối tượng JSON "
              "tuân thủ schema trong gói. Không dùng Markdown, không thêm văn bản ngoài JSON. "
              "Schema đã có trong nội dung người dùng. Giữ nguyên package_id và căn cứ trong gói đầu vào.")
    payload = {"model": config.model, "messages": [{"role": "system", "content": system},
                {"role": "user", "content": user_text}],
               "temperature": config.temperature, "stream": True, "stream_options": {"include_usage": True}}
    if config.max_tokens is not None:
        payload["max_tokens"] = config.max_tokens
    if config.reasoning_effort is not None:
        payload["reasoning_effort"] = config.reasoning_effort
    if config.json_mode:
        payload["response_format"] = {"type": "json_object"}
    request = urllib.request.Request(config.endpoint, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                                     headers={"Authorization": "Bearer " + config.api_key,
                                              "Content-Type": "application/json",
                                              "Accept": "text/event-stream"}, method="POST")
    handlers = [_NoRedirect()]
    if urllib.parse.urlsplit(config.endpoint).scheme == "https":
        handlers.append(urllib.request.HTTPSHandler(context=_ssl_context(config.ca_bundle)))
    opener = urllib.request.build_opener(*handlers)
    for attempt in range(len(RETRY_BACKOFF_SECONDS) + 1):
        try:
            with opener.open(request, timeout=config.timeout) as response:
                if response.headers.get_content_type() == "text/event-stream":
                    started = time.monotonic()
                    try:
                        return _stream_completion(_stream_lines(response))
                    except (OSError, http.client.HTTPException):
                        elapsed = time.monotonic() - started
                        raise RemoteError(f"Luồng phản hồi bị ngắt giữa chừng sau {elapsed:.0f} giây.") from None
                raw = response.read().decode("utf-8")
            try:
                result = json.loads(raw)
            except (ValueError, TypeError, RecursionError):
                raise RemoteError("API trả về phản hồi không phải JSON hợp lệ.") from None
            if not isinstance(result, dict):
                raise RemoteError("API trả về cấu trúc phản hồi không hợp lệ.")
            return result
        except urllib.error.HTTPError as exc:
            status = exc.code
            if status in {429, 500, 502, 503, 504, 524} and attempt < len(RETRY_BACKOFF_SECONDS):
                exc.close()
                time.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue
            if status in {401, 403}:
                message = "API key bị từ chối"
            elif status == 404:
                message = "API HTTP 404: kiểm tra FPT_BASE_URL và model."
            else:
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except (OSError, http.client.HTTPException):
                    body = ""
                message = f"API HTTP {status}: {redact(body, config.api_key)[:500]}"
            exc.close()
            raise RemoteError(message) from None
        except (urllib.error.URLError, OSError, TimeoutError, UnicodeError, http.client.HTTPException) as exc:
            reason = getattr(exc, "reason", exc)
            if isinstance(reason, ssl.SSLCertVerificationError):
                raise RemoteError("Xác minh chứng chỉ TLS thất bại; kiểm tra FPT_CA_BUNDLE.") from None
            if attempt < len(RETRY_BACKOFF_SECONDS):
                time.sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue
            raise RemoteError("Không kết nối được API hoặc đã hết thời gian chờ; kiểm tra mạng và timeout.") from None
    raise RemoteError("Không gọi được API.")


def response_content(response: dict) -> tuple[str, str | None]:
    finish_reason = None
    try:
        choice = response["choices"][0]
        finish_reason = choice.get("finish_reason")
        content = choice.get("message", {}).get("content", "")
        if isinstance(content, list):
            content = "".join(item["text"] for item in content
                              if isinstance(item, dict) and isinstance(item.get("text"), str))
        if not isinstance(content, str):
            content = ""
        return content, finish_reason if isinstance(finish_reason, str) else None
    except (KeyError, IndexError, TypeError, AttributeError):
        return "", finish_reason if isinstance(finish_reason, str) else None
