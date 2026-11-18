"""Lỗi người dùng tự sửa được (manifest sai, thiếu file, thiếu thư viện).

CLI in thông điệp của các lỗi này và thoát với mã tương ứng, không in traceback.
"""


class IngestError(Exception):
    """Cấu hình hoặc dữ liệu đầu vào không dùng được. Mã thoát 2."""

    exit_code = 2


class MissingDependency(IngestError):
    """Thiếu thư viện tuỳ chọn (ví dụ faster-whisper). Mã thoát 3."""

    exit_code = 3
