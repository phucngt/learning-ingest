"""Đọc / ghi file và vài hàm chuẩn hoá dùng chung.

Mọi file kết quả ghi UTF-8, xuống dòng "\\n" (cả trên Windows) và ghi nguyên
tử (file tạm rồi thay thế), để chạy lại cho ra đúng cùng nội dung và một lần
chạy hỏng giữa chừng không để lại file dở.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import unicodedata
from importlib import resources
from pathlib import Path
from typing import Any, Iterable


def write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def dumps_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def write_json(path: Path, obj: Any) -> None:
    write_text(path, dumps_json(obj))


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    write_text(path, "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))


def read_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_json(obj: Any) -> str:
    return sha256_bytes(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def strip_diacritics(text: str) -> str:
    text = text.replace("đ", "d").replace("Đ", "D")
    return "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")


def slugify(text: str, max_len: int = 60) -> str:
    """'Buổi 02' -> 'buoi-02'. Chỉ a-z, 0-9 và '-'."""
    slug = re.sub(r"[^a-z0-9]+", "-", strip_diacritics(text).lower()).strip("-")
    return slug[:max_len].rstrip("-") or "x"


def norm_text(text: str) -> str:
    """Chuẩn hoá để so trùng: NFC, chữ thường, bỏ dấu câu, gộp khoảng trắng.
    Giữ dấu tiếng Việt: 'lãi' và 'lại' là hai ý khác nhau."""
    text = unicodedata.normalize("NFC", text).lower()
    return re.sub(r"[\W_]+", " ", text).strip()


def resource_text(package_path: str) -> str:
    """Đọc file đóng gói kèm (schemas/*.json, prompts/*.md)."""
    folder, name = package_path.split("/", 1)
    return resources.files("learning_ingest").joinpath(folder).joinpath(name).read_text(encoding="utf-8")


def resource_json(package_path: str) -> Any:
    return json.loads(resource_text(package_path))
