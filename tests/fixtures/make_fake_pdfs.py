"""Tạo slide PDF giả lập cho test (không cần thư viện ngoài).

    python tests/fixtures/make_fake_pdfs.py

Font chuẩn Helvetica không có đủ dấu tiếng Việt, nên chữ trong PDF giả lập viết
không dấu. Trang "chỉ có hình" (một khối xám, không có lớp chữ) dùng để test
đánh dấu needs_ocr.
"""
from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).parent / "pilot-fake"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(path: Path, pages: list[list[str] | None]) -> None:
    """pages: mỗi trang là danh sách dòng chữ, hoặc None = trang chỉ có hình."""
    objs: dict[int, str] = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    }
    n, kids = 4, []
    for lines in pages:
        page_id, content_id = n, n + 1
        n += 2
        if lines is None:
            stream = "0.8 g 60 220 492 420 re f"
        else:
            stream = "BT /F1 20 Tf 60 720 Td 28 TL " + " ".join(f"({_esc(x)}) Tj T*" for x in lines) + " ET"
        objs[content_id] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
        objs[page_id] = ("<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                         f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        kids.append(page_id)
    objs[2] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(kids)} >>"
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for i in range(1, n):
        offsets[i] = len(out)
        out += f"{i} 0 obj\n{objs[i]}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {n}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offsets[i]:010d} 00000 n \n".encode() for i in range(1, n))
    out += f"trailer\n<< /Size {n} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))


def main() -> None:
    make_pdf(HERE / "fake-slide-1.pdf", [
        ["LUAT MAU - BUOI 02 (DU LIEU GIA LAP)", "Chao ban chung khoan ra cong chung"],
        ["Dieu kien chao ban (gia lap)", "- Von dieu le da gop toi thieu 99 ty dong",
         "- Kinh doanh co lai 2 nam lien truoc nam dang ky"],
        None,
    ])
    make_pdf(HERE / "fake-slide-2.pdf", [
        ["Ho so dang ky chao ban (gia lap)", "Nop cho Co quan Mau", "Thoi han xem xet: 45 ngay"],
        ["Cong bo thong tin (gia lap)", "Ban cao bach cong bo tren trang thong tin dien tu",
         "truoc khi phan phoi chung khoan"],
    ])


if __name__ == "__main__":
    main()
