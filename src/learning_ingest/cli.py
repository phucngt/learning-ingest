"""learning-ingest CLI.

  learning-ingest subjects
  learning-ingest extract          --manifest M --out D [--clip-start T] [--clip-end T] [--model X] [--no-cache]
  learning-ingest prepare-review   --manifest M --out D [--max-chars N]
  learning-ingest validate-export  --input ai-output.json [--input part2.json] --out D

Mã thoát: 0 xong; 1 đầu ra AI không hợp lệ (chưa xuất); 2 cấu hình / dữ liệu
đầu vào sai; 3 thiếu thư viện tuỳ chọn.
"""
from __future__ import annotations

import argparse
import dataclasses
import sys
from pathlib import Path

from . import __version__
from .errors import IngestError
from .timeutil import parse_timestamp


def _utf8_console() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def _timestamp(value: str) -> int:
    try:
        return parse_timestamp(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="learning-ingest",
                                description="Recording đào tạo -> điểm kiến thức có nguồn, chờ HCNS rà soát.")
    p.add_argument("--version", action="version", version=f"learning-ingest {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("subjects", help="Liệt kê 8 môn chuyên môn và các lộ trình.")

    e = sub.add_parser("extract", help="Trích transcript, slide theo trang, giáo trình.")
    e.add_argument("--manifest", required=True, type=Path)
    e.add_argument("--out", required=True, type=Path, help="Thư mục làm việc của buổi (dùng chung cho 3 lệnh).")
    e.add_argument("--cache-dir", type=Path, help="Mặc định <out>/.cache")
    e.add_argument("--clip-start", type=_timestamp, help="Chạy thử từ mốc này, ví dụ 00:10:00")
    e.add_argument("--clip-end", type=_timestamp, help="Chạy thử tới mốc này, ví dụ 00:20:00")
    e.add_argument("--model", help="Ghi đè transcription.model, ví dụ small, medium, large-v3")
    e.add_argument("--no-cache", action="store_true", help="Bỏ qua cache, làm lại từ đầu")

    r = sub.add_parser("prepare-review", help="Xuất gói đầu vào cho AI được công ty duyệt.")
    r.add_argument("--manifest", required=True, type=Path)
    r.add_argument("--out", required=True, type=Path)
    r.add_argument("--max-chars", type=int, help="Ghi đè review.max_chars_per_part")

    v = sub.add_parser("validate-export", help="Kiểm tra đầu ra JSON của AI rồi xuất gói import.")
    v.add_argument("--input", required=True, type=Path, action="append",
                   help="File JSON AI trả về. Gói nhiều phần: lặp lại --input cho từng phần.")
    v.add_argument("--out", required=True, type=Path, help="Thư mục làm việc đã chạy extract / prepare-review.")
    return p


def _cmd_subjects(_args) -> int:
    from .registry import load_registry, program_names

    registry = load_registry()
    names = program_names()
    print(registry["terminology"]["subjects"])
    for entry in sorted(registry["subjects"], key=lambda item: item["order"]):
        programs = ", ".join(names[pid] for pid in entry["programs"])
        detail = programs or entry.get("supplementary", "")
        print(f"{entry['order']}. {entry['subject_id']} [{entry['id_status']}] · {entry['name']} · {detail}")
    print("\nLộ trình")
    for program in registry["programs"]:
        print(f"- {program['name']} · {program['required_subjects']} môn")
    return 0


def _cmd_extract(args) -> int:
    from .extract import run_extract
    from .manifest import load_manifest
    m = load_manifest(args.manifest)
    if args.model:
        m = dataclasses.replace(m, transcription=dataclasses.replace(m.transcription, model=args.model))
    res = run_extract(m, args.out, args.cache_dir, clip_start_ms=args.clip_start, clip_end_ms=args.clip_end,
                      use_cache=not args.no_cache)
    print(f"Đã trích vào {res.out_dir}")
    print(f"  transcript: {res.segments} segment (nguồn: {'phụ đề' if res.transcript_origin == 'subtitle' else 'faster-whisper'}"
          + (f", chép mới {res.asr_chunks_run} khúc" if res.transcript_origin == "asr" else "") + ")")
    print(f"  slide: {res.slide_pages} trang, {res.pages_needing_ocr} trang cần rà/OCR")
    print(f"  giáo trình: {res.syllabus_sections} mục")
    print(f"  cache: {res.cache}")
    print(f"  extract_id: {res.extract_id}")
    for w in res.warnings:
        print(f"  ! {w}")
    return 0


def _cmd_review(args) -> int:
    from .manifest import load_manifest
    from .review import run_prepare_review
    m = load_manifest(args.manifest)
    res = run_prepare_review(m, args.out, max_chars=args.max_chars)
    print(f"Gói review: {res.review_dir}  (package_id {res.package_id})")
    for part in res.parts:
        print(f"  {part.name}")
    print(f"  tổng {res.total_chars:,} ký tự; giáo trình chọn theo: "
          f"{'chương HCNS khai báo' if res.syllabus_method == 'declared' else 'độ trùng từ ngữ'}")
    for w in res.warnings:
        print(f"  ! {w}")
    print("Đưa từng file package*.md vào AI được công ty duyệt; lưu JSON trả về rồi chạy validate-export.")
    return 0


def _cmd_validate(args) -> int:
    from .export import run_validate_export
    res = run_validate_export(args.input, args.out)
    if res.ok:
        print(f"Hợp lệ: {res.knowledge_points} điểm kiến thức, {res.warnings} cảnh báo.")
        for f in res.files:
            print(f"  {f}")
        return 0
    print(f"KHÔNG hợp lệ: {res.errors} lỗi, {res.warnings} cảnh báo. Chưa xuất gói import.")
    print(f"  Chi tiết: {res.export_dir / 'validation-report.md'}")
    for f in res.removed_stale:
        print(f"  Đã xoá gói cũ để tránh nhầm: {f}")
    return 1


def main(argv: list[str] | None = None) -> int:
    _utf8_console()
    args = build_parser().parse_args(argv)
    try:
        return {"subjects": _cmd_subjects, "extract": _cmd_extract, "prepare-review": _cmd_review,
                "validate-export": _cmd_validate}[args.command](args)
    except IngestError as exc:
        print(f"Lỗi: {exc}", file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        print("Đã dừng. Chạy lại cùng lệnh sẽ dùng cache của phần đã xong.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
