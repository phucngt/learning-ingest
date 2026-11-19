"""Danh mục 8 môn chuyên môn và các lộ trình hành nghề."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
from pathlib import Path

import yaml

from .errors import IngestError
from .util import resource_text


def _rows_by_id(data: dict, key: str, id_key: str) -> dict[str, dict]:
    rows = data.get(key)
    if not isinstance(rows, list) or not rows:
        raise IngestError(f"Danh mục môn: {key} phải là một danh sách có nội dung.")
    indexed = {}
    for row in rows:
        value = row.get(id_key) if isinstance(row, dict) else None
        if not isinstance(value, str) or not value:
            raise IngestError(f"Danh mục môn: mỗi mục trong {key} cần có {id_key}.")
        if value in indexed:
            raise IngestError(f"Danh mục môn: {id_key} trùng: {value}")
        indexed[value] = row
    return indexed


@lru_cache(maxsize=None)
def load_registry(path: str | Path | None = None) -> dict:
    """Đọc danh mục đóng gói, hoặc danh mục ở path để kiểm tra độc lập."""
    try:
        raw = resource_text("registry/subjects.yaml") if path is None else Path(path).read_text(encoding="utf-8-sig")
        data = yaml.safe_load(raw)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise IngestError(f"Danh mục môn không đọc được: {exc}") from exc
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data["schema_version"] != 1:
        raise IngestError("Danh mục môn cần schema_version: 1.")

    programs = _rows_by_id(data, "programs", "program_id")
    subjects = _rows_by_id(data, "subjects", "subject_id")
    counts: Counter[str] = Counter()
    for sid, item in subjects.items():
        memberships = item.get("programs")
        if not isinstance(memberships, list) or not all(isinstance(pid, str) for pid in memberships):
            raise IngestError(f"Danh mục môn: {sid} cần danh sách programs.")
        unknown = sorted(set(memberships) - programs.keys())
        if unknown:
            raise IngestError(f"Danh mục môn: {sid} khai báo program_id không hợp lệ: {', '.join(unknown)}")
        if len(set(memberships)) != len(memberships):
            raise IngestError(f"Danh mục môn: {sid} có program_id trùng.")
        counts.update(memberships)

    for pid, item in programs.items():
        required = item.get("required_subjects")
        if type(required) is not int or required != counts[pid]:
            raise IngestError(f"Danh mục môn: {pid} khai báo {required} môn, danh mục có {counts[pid]} môn.")

    orders = [item.get("order") for item in subjects.values()]
    if any(type(order) is not int for order in orders) or sorted(orders) != list(range(1, len(orders) + 1)):
        raise IngestError("Danh mục môn: order phải là các số nguyên duy nhất từ 1 đến số môn.")
    return data


def subject(subject_id: str) -> dict | None:
    return next((item for item in load_registry()["subjects"] if item["subject_id"] == subject_id), None)


def programs_for(subject_id: str) -> list[str]:
    item = subject(subject_id)
    return list(item["programs"]) if item is not None else []


def program_names() -> dict[str, str]:
    return {p["program_id"]: p["name"] for p in load_registry()["programs"]}
