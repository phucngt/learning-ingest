"""learning-ingest: recording đào tạo -> điểm kiến thức có nguồn, chờ HCNS rà soát.

Các lệnh CLI (xem cli.py):
  extract          video/phụ đề, slide PDF, giáo trình MD -> dữ liệu đã trích
  prepare-review   dữ liệu đã trích -> gói rà soát cho AI
  draft            gói rà soát -> dịch vụ AI đã cấu hình -> JSON nháp
  validate-export  đầu ra JSON của AI -> kiểm tra nguồn -> gói import + bản đọc duyệt
"""

__version__ = "0.1.0"
