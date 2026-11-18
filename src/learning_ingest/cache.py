"""Cache theo hash nội dung đầu vào + cấu hình.

Khoá cache = sha256 của (loại việc, hash file đầu vào, cấu hình liên quan,
phiên bản bộ trích). Đổi file, đổi model hay đổi đoạn cắt thì khoá đổi; giữ
nguyên thì lần chạy sau đọc lại kết quả, không chép lời lại từ đầu.

Hash một video vài GB mất vài giây, nên hash file được nhớ theo
(đường dẫn, kích thước, mtime): file không đổi thì không đọc lại.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from .util import read_json, sha256_json, write_json


class Cache:
    def __init__(self, root: Path, enabled: bool = True):
        self.root = Path(root)
        self.enabled = enabled
        self.hits: Counter = Counter()
        self.misses: Counter = Counter()
        self._hash_index_path = self.root / "file-hashes.json"
        self._hash_index: dict[str, dict] | None = None

    # ── hash file ──────────────────────────────────────────────────────────
    def file_sha256(self, path: Path) -> str:
        path = Path(path).resolve()
        st = path.stat()
        index = self._load_hash_index()
        key = str(path)
        known = index.get(key)
        if known and known.get("size") == st.st_size and known.get("mtime_ns") == st.st_mtime_ns:
            return known["sha256"]
        h = hashlib.sha256()
        with open(path, "rb") as fh:
            for block in iter(lambda: fh.read(1 << 20), b""):
                h.update(block)
        digest = h.hexdigest()
        index[key] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": digest}
        if self.enabled:
            write_json(self._hash_index_path, index)
        return digest

    def _load_hash_index(self) -> dict[str, dict]:
        if self._hash_index is None:
            self._hash_index = {}
            if self.enabled and self._hash_index_path.exists():
                try:
                    self._hash_index = read_json(self._hash_index_path)
                except (OSError, json.JSONDecodeError):
                    self._hash_index = {}
        return self._hash_index

    # ── kết quả ────────────────────────────────────────────────────────────
    @staticmethod
    def key(kind: str, *parts: Any) -> str:
        return sha256_json([kind, *parts])

    def _path(self, kind: str, key: str) -> Path:
        return self.root / kind / key[:2] / f"{key}.json"

    def get(self, kind: str, key: str) -> Any | None:
        if not self.enabled:
            self.misses[kind] += 1
            return None
        path = self._path(kind, key)
        if path.exists():
            try:
                value = read_json(path)
            except (OSError, json.JSONDecodeError):
                value = None          # hỏng: coi như chưa có, ghi lại
            if value is not None:
                self.hits[kind] += 1
                return value
        self.misses[kind] += 1
        return None

    def put(self, kind: str, key: str, value: Any) -> None:
        if self.enabled:
            write_json(self._path(kind, key), value)

    def stats(self) -> dict:
        return {"hits": dict(self.hits), "misses": dict(self.misses)}
