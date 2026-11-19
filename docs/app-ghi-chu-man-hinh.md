# Ghi chú bàn giao cho nhóm phát triển app

## Danh sách môn chuyên môn

- Mặc định mở lộ trình **Môi giới chứng khoán** với 4 môn. Giữ bộ lọc **Tất cả 8 môn**.
- Khi mới mở môn Pháp luật, hiển thị **Đã mở 1/4 môn** trong lộ trình mặc định.
- Thẻ môn Pháp luật hiển thị **11 chương · [số câu trong ngân hàng] câu luyện tập**. Lấy số câu từ ngân hàng câu hỏi.
- Bỏ nhãn **Nhiều người rớt nhất** cho đến khi HCNS có dữ liệu.

## Mạnh – yếu theo chương

- Dùng thanh ngang thay cho biểu đồ radar. Mỗi dòng hiển thị tên chương, tỷ lệ trả lời đúng và số câu đã làm.
- Hiển thị riêng **Chưa làm**, **Chưa đủ dữ liệu** và **Cần ôn**. Chương chưa có câu trả lời hiển thị **Chưa làm** thay cho 0%.
- Ví dụ, dòng **Chương 2 · 20% đúng · 9 điểm cần sửa** liên kết tới **Ôn chương 2**.
- Thống kê theo chương cần `chapter_id` từ các điểm kiến thức do công cụ ingest xuất. HCNS thay các mã tạm `plck-cNN` trong manifest bằng mã chương của app trước khi dùng cho thống kê.

## Kỳ thi sát hạch cấp chứng chỉ hành nghề

Tham khảo thời lượng, số phần và quy tắc đạt tại mục `licensing_exams` trong [danh mục môn chuyên môn](../src/learning_ingest/registry/subjects.yaml). Mục này có `verify_status: "cần xác nhận"`. Xác nhận riêng số câu và thời lượng kiểm tra cuối khóa môn Pháp luật trước khi cài cấu hình đề mô phỏng.
