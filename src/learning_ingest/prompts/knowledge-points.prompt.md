# Yêu cầu: tạo điểm kiến thức từ một gói học liệu (bản chờ HCNS rà soát)

Mã gói: `{{package_id}}` · Phần {{part_number}}/{{part_count}}

Bạn hỗ trợ bộ phận Hành chính Nhân sự (HCNS) soạn tài liệu ôn thi chứng chỉ hành nghề chứng khoán. Đầu vào gồm một hoặc nhiều nguồn: transcript bài giảng (nếu gói có video; có mã đoạn và mốc thời gian), slide (PDF theo trang, PowerPoint theo slide), văn bản Word theo mục và phần giáo trình liên quan. Nhiệm vụ: rút ra các **điểm kiến thức** để HCNS rà soát. Kết quả chưa phải tài liệu chính thức. HCNS là người quyết định cuối cùng.

## Thông tin gói học

- Môn: `{{subject_id}}` ({{subject_name}}). Lộ trình: {{programs}}.
- Khoá: `{{course_id}}`. Buổi: `{{session_id}}` ({{session_label}}).
- Video: {{video_source}}
- Transcript: {{transcript_note}}
- Slide:
{{slide_sources}}
- Văn bản:
{{document_sources}}
- Giáo trình: {{syllabus_source}}

### Danh sách chương giáo trình (chỉ được dùng các chapter_id này)

{{chapters}}

{{selection_note}}

{{part_note}}

## Quy tắc bắt buộc

1. **Chỉ dùng nội dung có trong gói.** Không thêm kiến thức bên ngoài. Không bịa số liệu, số hiệu văn bản, điều khoản hay tên người. Nếu một ý cần thêm ngữ cảnh mới hiểu được, ghi vào `review_notes`.
2. **Mỗi điểm kiến thức là một ý kiểm tra được**, đủ để ra câu hỏi ôn thi. `title` ngắn, dưới 120 ký tự. `summary` dài 2–5 câu, nói đúng như nguồn.
3. **Mỗi điểm có ít nhất một nguồn hợp lệ** trong `sources`:
   - Video: `{"type": "video", "source_id": "{{video_source_id}}", "segment_id": "seg-…"}`. Mã segment lấy từ các dòng `[seg-… | mốc]` trong transcript. Nếu ghi `start_ms`/`end_ms`, phải khớp mốc của chính segment đó.
   - Slide: `{"type": "slide", "source_id": "<mã slide>", "pdf_page": <số trang>}`. Slide PowerPoint (.pptx) cũng trích bằng `pdf_page`, giá trị là **số thứ tự slide**.
   - Văn bản: `{"type": "document", "source_id": "<mã văn bản>", "section_id": "<mã mục>"}`. Mã mục lấy từ các dòng `mục `sec-…`` trong phần Văn bản; không dùng `pdf_page` cho văn bản.
   - Giáo trình: `{"type": "syllabus", "source_id": "{{syllabus_source_id}}", "pdf_page": <số trang>, "section_id": "<mã mục hoặc null>"}`. Số trang lấy theo mốc `[trang N]` trong phần giáo trình.
   - Không tạo mã segment, mã nguồn, số trang hay mã mục không có trong gói. Không trích nội dung từ trang / slide ghi "cần rà/OCR".
4. **chapter_id**:
   - Chỉ dùng mã trong danh sách chương ở trên. **Không suy chương từ số buổi**: {{session_label}} không có nghĩa là Chương 2.
   - Nếu không chắc chương nào, để `chapter_id: null` và ghi lý do vào `chapter_id_reason`.
   - Khi đã có `chapter_id`, đặt `chapter_id_reason: null`.
5. **Điểm kiến thức đã có**:
   - Nếu ý trùng một mục trong danh mục điểm kiến thức đã có, ghi mã vào `existing_knowledge_point_id` và giải thích ngắn trong `existing_match_reason`.
   - Không chắc thì để cả hai là `null`.
6. **Cần đối chiếu**: mọi số liệu (tiền, tỷ lệ, số lượng), thời hạn (ngày, tháng, năm, hạn chót) và điều khoản / số hiệu văn bản phải có một mục trong `verification_flags`:
   - `kind`: `number`, `deadline`, `legal_reference` hoặc `other`;
   - `text`: chép nguyên văn;
   - `sources`: nguồn chứa nội dung đó.
7. **Mâu thuẫn**:
   - Nếu các nguồn nói khác nhau (ví dụ slide và giáo trình ghi khác số), thêm một mục vào `conflicts`, liệt kê từng nguồn kèm nội dung nó nói.
   - **Không tự chọn bên đúng.** HCNS quyết định.
8. **Nếu gói có transcript, làm theo hướng dẫn ở dòng Transcript.** Đối chiếu thuật ngữ với slide, văn bản và giáo trình, đồng thời giữ nguyên văn nguồn trong `quote` nếu trích dẫn. Gói không có video thì chỉ dùng slide, văn bản và giáo trình.
9. `review_status` luôn là `"pending_review"`. `review_notes` ghi điều HCNS cần lưu ý; không có gì thì để `""`.
10. `local_id` đánh số theo thứ tự `kp-001`, `kp-002`, … trong câu trả lời của bạn.
11. **Chỉ trả về một JSON object** đúng schema bên dưới. Không bọc trong markdown, không giải thích thêm. Trường `package_id` phải là `{{package_id}}`.

## Schema đầu ra (JSON Schema)

```json
{{output_schema}}
```

## Ví dụ hình dạng (dữ liệu minh hoạ, không phải nội dung thật)

```json
{{example}}
```
