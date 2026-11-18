"""learning-ingest: recording đào tạo -> điểm kiến thức có nguồn, chờ HCNS rà soát.

Ba bước, mỗi bước một lệnh CLI (xem cli.py):
  extract          video/phụ đề, slide PDF, giáo trình MD -> dữ liệu đã trích
  prepare-review   dữ liệu đã trích -> gói đầu vào cho AI được công ty duyệt
  validate-export  đầu ra JSON của AI -> kiểm tra nguồn -> gói import + bản đọc duyệt
"""

__version__ = "0.1.0"
