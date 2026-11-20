"""Soạn JSON nháp từ gói rà soát đã chuẩn bị để người dùng kiểm duyệt."""
from __future__ import annotations

import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from . import __version__
from .errors import IngestError, RemoteError
from .llm import PROVIDERS, _has_key, load_config, redact, request_completion, response_content
from .util import read_json, sha256_bytes, write_json, write_text


def _parse_content(content: str) -> dict | None:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    if "{" in text and "}" in text:
        candidates.append(text[text.find("{"):text.rfind("}") + 1])
    for candidate in candidates:
        try:
            value = json.loads(candidate, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            continue
        if isinstance(value, dict):
            try:
                json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (UnicodeError, ValueError, RecursionError):
                return None
            return value
        return None
    return None


def _reject_constant(value):
    raise ValueError("JSON không cho phép NaN hoặc Infinity.")


def _quote(path: Path) -> str:
    text = str(path)
    return '"' + text.replace('"', '\\"') + '"' if any(c.isspace() for c in text) else text


def _next_command(out_dir: Path, api_key=""):
    def order(path):
        match = re.search(r"part-(\d+)", path.name)
        return int(match.group(1)) if match else 0
    outputs = sorted((p for p in (out_dir / "draft").glob("ai-output*.json") if p.is_file()), key=order)
    if outputs:
        print(redact("Tiếp theo: learning-ingest validate-export " +
              " ".join("--input " + _quote(p) for p in outputs) + " --out " + _quote(out_dir), api_key))


def run_draft(out_dir: Path, *, provider="fpt", model=None, part=None, force=False,
              dry_run=False, timeout=None, env_file=Path(".env")) -> int:
    out_dir = Path(out_dir)
    review_dir = out_dir / "review"
    manifest_path = review_dir / "review-manifest.json"
    if not manifest_path.is_file():
        raise IngestError("Chưa có gói rà soát; chạy prepare-review trước.")
    try:
        manifest = read_json(manifest_path)
        parts = manifest["parts"]
        if not isinstance(parts, list) or not parts:
            raise ValueError
        for index, item in enumerate(parts, 1):
            if not isinstance(item, dict) or item.get("part") != index or not isinstance(item.get("file"), str):
                raise ValueError
        if part is not None and (isinstance(part, bool) or not isinstance(part, int) or not 1 <= part <= len(parts)):
            raise IngestError(f"--part phải từ 1 đến {len(parts)}.")
    except (OSError, ValueError, KeyError, TypeError):
        raise IngestError("Gói rà soát không hợp lệ; chạy lại prepare-review.") from None
    selected = [parts[part - 1]] if part is not None else parts
    draft_dir = out_dir / "draft"
    jobs = []
    for item in selected:
        number = item["part"]
        input_file = review_dir / item["file"]
        if not input_file.resolve().is_relative_to(review_dir.resolve()) or not input_file.is_file():
            raise IngestError("Thiếu hoặc sai file gói rà soát; chạy lại prepare-review.")
        output_file = draft_dir / ("ai-output.json" if len(parts) == 1 else
                                  f"ai-output-part-{number:02d}-of-{len(parts):02d}.json")
        raw_file = draft_dir / f"response-part-{number:02d}.txt"
        if not force and output_file.exists():
            raise IngestError(f"Kết quả phần {number} đã có; dùng --force để ghi đè.")
        try:
            data = input_file.read_bytes()
            text = data.decode("utf-8")
        except (OSError, UnicodeError):
            raise IngestError("Không đọc được file gói rà soát UTF-8.") from None
        jobs.append((item, output_file, raw_file, data, text))
    config = load_config(provider=provider, model=model, timeout=timeout, env_file=env_file)
    print(f"Provider: {PROVIDERS[config.provider]['name']}; model: {config.model}; endpoint: {config.endpoint}; "
          f"reasoning_effort: {redact(config.reasoning_effort or 'none', config.api_key)}")
    for item, _, _, _, text in jobs:
        print(f"Phần {item['part']}/{len(parts)}: {len(text)} ký tự ({redact(item['file'], config.api_key)})")
    if dry_run:
        print("Dry-run: không gọi API, không ghi file.")
        return 0
    run_path = draft_dir / "draft-run.json"
    old_parts = {}
    if run_path.is_file():
        try:
            old = read_json(run_path)
            if old.get("package_id") == manifest.get("package_id"):
                old_parts = {entry["part"]: entry for entry in old.get("parts", [])}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            raise IngestError("draft-run.json không hợp lệ; kiểm tra file trước khi chạy lại.") from None
    metadata = {"tool": "learning-ingest", "version": __version__, "provider": config.provider,
                "model": config.model, "endpoint": config.endpoint, "package_id": manifest.get("package_id"),
                "prompt_version": manifest.get("prompt_version"),
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "temperature": config.temperature, "json_mode": config.json_mode,
                "reasoning_effort": config.reasoning_effort}
    if _has_key(metadata, config.api_key) or _has_key(old_parts, config.api_key):
        raise IngestError("Thông tin gói rà soát chứa thông tin xác thực; không thể lưu nhật ký.")
    exit_code = 0
    for item, output_file, raw_file, data, text in jobs:
        number = item["part"]
        entry = {"part": number, "input_file": redact(item["file"], config.api_key), "input_sha256": sha256_bytes(data),
                 "input_chars": len(text), "output_file": None, "finish_reason": None}
        started = time.monotonic()
        try:
            response = request_completion(config, text)
        except RemoteError:
            entry.update(status="remote_error", duration_seconds=round(time.monotonic() - started, 3))
            old_parts[number] = entry
            write_json(run_path, metadata | {"parts": [old_parts[k] for k in sorted(old_parts)]})
            print(f"Phần {number}: lỗi gọi API.", file=sys.stderr)
            _next_command(out_dir, config.api_key)
            raise
        content, finish = response_content(response)
        safe_raw = redact(content, config.api_key).encode("utf-8", errors="replace").decode("utf-8")
        write_text(raw_file, safe_raw)
        stream_cut = response.get("stream_incomplete") is True
        value = None if stream_cut else _parse_content(content)
        credential_bearing = _has_key(value, config.api_key) or config.api_key in content
        if credential_bearing:
            write_text(raw_file, "[REDACTED: phản hồi chứa thông tin xác thực]")
        safe_finish = redact(finish, config.api_key) if finish is not None else None
        if safe_finish is not None:
            safe_finish = safe_finish.encode("utf-8", errors="replace").decode("utf-8")
        entry.update(finish_reason=safe_finish, duration_seconds=round(time.monotonic() - started, 3))
        reasoning_chars = response.get("reasoning_chars")
        if type(reasoning_chars) is int and reasoning_chars >= 0:
            entry["reasoning_chars"] = reasoning_chars
        if "usage" in response and not _has_key(response["usage"], config.api_key):
            try:
                json.dumps(response["usage"], ensure_ascii=False, allow_nan=False).encode("utf-8")
            except (UnicodeError, ValueError, TypeError, RecursionError):
                pass
            else:
                entry["usage"] = response["usage"]
        if stream_cut:
            elapsed_seconds = response.get("elapsed_seconds")
            if type(elapsed_seconds) is not float or not math.isfinite(elapsed_seconds) or elapsed_seconds < 0:
                elapsed_seconds = entry["duration_seconds"]
            entry.update(status="stream_cut", elapsed_seconds=elapsed_seconds)
            print(f"Phần {number}: luồng phản hồi kết thúc giữa chừng sau {elapsed_seconds:.0f} giây. "
                  "FPT giới hạn mỗi yêu cầu khoảng 300 giây. Giữ FPT_REASONING_EFFORT=low "
                  "hoặc chia nhỏ gói bằng prepare-review --max-chars. "
                  f"Raw: {redact(str(raw_file), config.api_key)}", file=sys.stderr)
            exit_code = 1
        elif finish == "length":
            entry["status"] = "truncated"
            print(f"Phần {number}: phản hồi bị cắt; tăng FPT_MAX_TOKENS hoặc chạy prepare-review --max-chars nhỏ hơn. Raw: {redact(str(raw_file), config.api_key)}", file=sys.stderr)
            exit_code = 1
        elif value is None or credential_bearing:
            entry["status"] = "invalid_json"
            print(f"Phần {number}: AI không trả về JSON hợp lệ. Raw: {redact(str(raw_file), config.api_key)}", file=sys.stderr)
            exit_code = 1
        else:
            if value.get("package_id") != manifest.get("package_id"):
                print(f"Cảnh báo phần {number}: package_id không khớp gói rà soát; cần kiểm tra.", file=sys.stderr)
            write_json(output_file, value)
            entry.update(status="saved", output_file=output_file.name)
            print(f"Đã lưu phần {number}: {redact(str(output_file), config.api_key)}")
        old_parts[number] = entry
        write_json(run_path, metadata | {"parts": [old_parts[k] for k in sorted(old_parts)]})
    _next_command(out_dir, config.api_key)
    return exit_code
