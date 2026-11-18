# learning-ingest

## Mục đích

Công cụ nội bộ giúp HCNS chuyển video hoặc phụ đề, slide PDF và giáo trình Markdown của một buổi đào tạo thành các điểm kiến thức có nguồn để rà soát trước khi đưa vào ứng dụng ôn thi.

Phạm vi thí điểm là **Luật 2025 / Buổi 02**. Môn Pháp luật chứng khoán (`phap-luat-chung-khoan`) dùng chung cho Môi giới, Phân tích tài chính và Quản lý quỹ. Mã buổi học và mã chương giáo trình độc lập. Chỉ dùng mã chương có căn cứ trong giáo trình. Tuyệt đối không suy ra Buổi 02 là Chương 2.

## Dữ liệu và bảo mật

Repo chỉ lưu mã nguồn, mẫu cấu hình và dữ liệu giả lập. Đặt video, phụ đề, slide, giáo trình và JSON AI thật trong `data/`. Giữ bản chép lời, gói rà soát, cache và kết quả trong `output/`. Git bỏ qua cả hai thư mục. Quy trình này không dùng dữ liệu khách hàng.

Công cụ xử lý tài liệu cục bộ, không gọi dịch vụ AI hay gửi dữ liệu đi. Khi cần AI để dự thảo điểm kiến thức, HCNS thao tác riêng bằng công cụ AI được công ty phê duyệt. Nếu dùng ASR, chuẩn bị model trên máy để chép lời cục bộ. Gói xuất là **BẢN NHÁP**, ở trạng thái `pending_review` cho đến khi HCNS kiểm tra nội dung và đối chiếu nguồn.

## Cài đặt

Chạy các lệnh từ thư mục gốc của repo. Dùng Python 3.11 trở lên.

PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
# Chỉ cài khi cần chép lời từ video hoặc âm thanh
python -m pip install -e ".[asr]"
```

Bash

```bash
python -m venv .venv
# Dùng .venv/Scripts/activate nếu chạy Git Bash trên Windows
source .venv/bin/activate
python -m pip install -e ".[dev]"
# Chỉ cài khi cần chép lời từ video hoặc âm thanh
python -m pip install -e ".[asr]"
```

Với phụ đề VTT hoặc SRT, chỉ cần bộ cài cơ bản. Khi chưa có phụ đề, công cụ dùng faster-whisper và PyAV để đọc MP4 và chép lời. Nếu MP4 không giải mã được, có thể tách âm thanh và khai báo `video.audio_path`. Âm thanh tách ra cần giữ nguyên mốc thời gian của video.

## Manifest của buổi học

Mỗi buổi dùng một manifest YAML hoặc JSON. Đường dẫn tương đối trong manifest được tính từ thư mục chứa manifest.

| Trường | Nội dung |
| --- | --- |
| `schema_version`, `subject_id`, `course_id`, `session_id`, `session_label` | Phiên bản manifest là số `1`. Khai báo mã môn, mã khóa, mã buổi và tên hiển thị. |
| `subject_name`, `course_name`, `programs` | Tên hiển thị và các chương trình dùng chung môn. |
| `video` | Mã nguồn, MP4 hoặc audio, phụ đề nếu có, link mở video và mẫu link theo mốc nếu đã thử. Công cụ ưu tiên phụ đề được khai báo. |
| `slides`, `syllabus` | Danh sách slide PDF và giáo trình Markdown. Mỗi nguồn có `source_id` riêng và có thể khai báo link PDF gốc. |
| `related_chapter_ids` | Mã chương HCNS đã xác nhận liên quan tới buổi học. Nếu để trống, gói rà soát chọn mục giáo trình theo độ trùng từ ngữ. |
| `catalog_path` | Danh mục điểm kiến thức đã có, dùng để phát hiện nội dung có thể trùng. |
| `transcription`, `review`, `export` | Cấu hình chép lời, giới hạn gói rà soát và tên tệp Markdown xuất. |

Xem [manifest mẫu Luật 2025 / Buổi 02](examples/luat-2025-buoi-02.manifest.yaml) và [schema manifest](src/learning_ingest/schemas/manifest.schema.json). Khi đưa vào sử dụng, lưu manifest chứa đường dẫn và link nội bộ trong `data/`, rồi sửa đường dẫn tương đối theo vị trí tệp mới.

## Chạy một buổi học

Dùng cùng một thư mục `--out` cho cả ba lệnh. Ví dụ dưới đây giả sử HCNS đã lưu manifest thật trong `data/raw/luat-2025/buoi-02/` và lưu JSON AI vào thư mục làm việc sau bước 2.

### PowerShell

```powershell
$manifest = "data/raw/luat-2025/buoi-02/manifest.yaml"
$work = "output/luat-2025/buoi-02"

learning-ingest extract --manifest $manifest --out $work
learning-ingest prepare-review --manifest $manifest --out $work
# HCNS đưa gói vào AI được duyệt và lưu kết quả thành ai-output.json
learning-ingest validate-export --input "$work/ai-output.json" --out $work
```

### Bash

```bash
manifest="data/raw/luat-2025/buoi-02/manifest.yaml"
work="output/luat-2025/buoi-02"

learning-ingest extract --manifest "$manifest" --out "$work"
learning-ingest prepare-review --manifest "$manifest" --out "$work"
# HCNS đưa gói vào AI được duyệt và lưu kết quả thành ai-output.json
learning-ingest validate-export --input "$work/ai-output.json" --out "$work"
```

Nếu đã có các thư viện cần thiết, có thể đặt `$env:PYTHONPATH = "src"` trong PowerShell hoặc `export PYTHONPATH=src` trong Bash và dùng `python -m learning_ingest` thay cho `learning-ingest`. Trên Git Bash cho Windows, đặt thêm `export PYTHONIOENCODING=utf-8`.

1. **`extract`** tạo `transcript.vtt`, `transcript.jsonl`, `slides.jsonl`, `slides-index.json`, `syllabus.json`, `catalog.json` và `extract-manifest.json`. Các tệp chứa mã đoạn, mốc thời gian, mã nguồn, số trang và dữ liệu dùng để kiểm tra trích dẫn.
2. **`prepare-review`** tạo `review/package.md`, `review/prompt.md` và `review/review-manifest.json` có `package_id`. Nếu gói dài, công cụ chia thành `package-part-NN-of-MM.md`. Có thể điều chỉnh ngưỡng chia bằng `--max-chars`. HCNS đưa từng gói Markdown vào AI được duyệt và lưu một tệp JSON cho mỗi phần, giữ nguyên `package_id`.
3. **`validate-export`** kiểm tra JSON AI với dữ liệu đã trích và ghi báo cáo. Nếu có nhiều phần, lặp `--input` theo thứ tự, ví dụ `--input part1.json --input part2.json`.

### Chạy thử một đoạn

Thêm `--clip-start 00:10:00 --clip-end 00:12:30` vào lệnh `extract` và dùng thư mục `--out` riêng cho lần chạy thử. Có thể khai báo mốc mặc định trong `video.clip`. Mốc transcript vẫn tính từ đầu video gốc. Ví dụ, câu ở phút 10 vẫn có mốc khoảng `00:10:00` trong đoạn chạy thử.

### Cache và chạy tiếp

Mặc định, `extract` lưu cache trong `<out>/.cache`. Công cụ dùng lại kết quả trích slide và từng khúc chép lời đã hoàn thành nếu dữ liệu và cấu hình tương ứng vẫn khớp. Sau khi dừng giữa chừng, chạy lại cùng lệnh với cùng cache để tiếp tục từ khúc chưa xong. Dùng `--cache-dir` để chọn thư mục cache và `--no-cache` để chạy lại mà không dùng cache.

## Giáo trình Markdown

Khai báo các chương trong YAML front matter. Ví dụ dưới đây minh họa cấu trúc trên dữ liệu giả lập.

```markdown
---
subject_id: phap-luat-chung-khoan
chapters:
  - chapter_id: plck-c03
    title: Chương III. Chào bán chứng khoán (giả lập)
    pdf_page_start: 40
    pdf_page_end: 59
---

<!-- page: 40 -->
# Chương III. Chào bán chứng khoán (giả lập)
## 1. Điều kiện
Nội dung ở trang 40.

<!-- page: 41 -->
## 2. Hồ sơ
Nội dung ở trang 41.
```

Dùng tiêu đề khớp `title`, khai báo `heading` trong front matter hoặc gắn `{#chapter_id}` lên tiêu đề. Nếu không khai báo `chapters`, có thể gắn mã trực tiếp vào tiêu đề chương như `# Chương I. Tổng quan {#c1}`. Nếu giáo trình không có mã chương rõ ràng, trả `chapter_id: null` và giải thích trong `chapter_id_reason`.

Đặt `<!-- page: N -->` tại vị trí sang trang của bản PDF, hoặc khai báo `syllabus.page_marker_pattern` trong manifest. Regex cần đúng một nhóm bắt số trang. Thiếu mốc trang thì bước trích xuất cảnh báo. Khi có `pdf_page_count`, bước kiểm tra chỉ xác nhận trích dẫn nằm trong tổng số trang và vẫn cảnh báo. Nếu thiếu cả mốc lẫn tổng số trang, trích dẫn trang giáo trình sẽ bị báo lỗi.

## Định dạng JSON AI

Đối chiếu với [schema đầu ra AI](src/learning_ingest/schemas/ai-output.schema.json) và [prompt đi kèm](src/learning_ingest/prompts/knowledge-points.prompt.md).

- Các trường cấp gói gồm `schema_version` là chuỗi `"1.0"`, `package_id`, `subject_id`, `session_id` và `knowledge_points`.
- Mỗi điểm cần `local_id`, `title`, `summary`, `subject_id`, `session_id`, `chapter_id`, `chapter_id_reason`, `existing_knowledge_point_id`, `existing_match_reason`, `sources`, `verification_flags`, `conflicts`, `review_status` và `review_notes`. Dùng `review_status: "pending_review"`.
- `sources` phải có ít nhất một nguồn. Nguồn `video` dùng `source_id` và `segment_id`, có thể kèm `start_ms` và `end_ms`. Nguồn `slide` và `syllabus` dùng `source_id` và `pdf_page` đánh số từ 1. Nguồn `syllabus` có thể kèm `section_id`.
- `verification_flags` đánh dấu số liệu (`number`), thời hạn (`deadline`), căn cứ pháp lý (`legal_reference`) hoặc nội dung khác (`other`) cần đối chiếu. Mỗi cờ có `kind` và `text`, có thể kèm ghi chú và nguồn.
- Nếu các nguồn nói khác nhau, ghi một mục trong `conflicts` với `topic` và từ hai `claims` trở lên. Mỗi ý kiến gồm `source` và `statement` để HCNS đối chiếu. Dùng mảng rỗng khi không có cờ hoặc mâu thuẫn.
- Nếu có khả năng trùng điểm trong danh mục, gắn `existing_knowledge_point_id` cùng `existing_match_reason`. Nếu không có điểm phù hợp, đặt cả hai trường thành `null`.

## Quy tắc kiểm tra

Lỗi chặn xuất gói. Cảnh báo vẫn cho phép xuất bản nháp để HCNS xem.

| Mã | Mức | Ý nghĩa |
| --- | --- | --- |
| `file_missing` | Lỗi | Không tìm thấy tệp JSON được chỉ định. |
| `json_invalid` | Lỗi | Nội dung không phải JSON hợp lệ. |
| `code_fence` | Cảnh báo | Đầu ra được bọc trong khối mã Markdown. Công cụ đã bỏ lớp bọc. |
| `schema` | Lỗi | Dữ liệu sai schema, ví dụ thiếu trường, thiếu nguồn hoặc trạng thái khác `pending_review`. |
| `subject_mismatch` | Lỗi | Mã môn khác manifest. |
| `session_mismatch` | Lỗi | Mã buổi khác manifest. |
| `package_unknown` | Cảnh báo | Chưa có metadata gói rà soát để đối chiếu. |
| `package_stale` | Cảnh báo | Mã gói AI khác mã gói rà soát hiện tại. Các nguồn vẫn được kiểm tra theo dữ liệu hiện tại. |
| `empty` | Lỗi | Gói không có điểm kiến thức. |
| `source_id_unknown` | Lỗi | Mã nguồn không có hoặc được dùng cho sai loại nguồn. |
| `segment_unknown` | Lỗi | Mã đoạn không có trong transcript. |
| `timestamp_mismatch` | Lỗi | Mốc bắt đầu phải từ đầu đoạn trừ 1.000 ms đến cuối đoạn. Mốc kết thúc phải từ đầu đoạn đến cuối đoạn cộng 1.000 ms và không được trước mốc bắt đầu. |
| `page_out_of_range` | Lỗi | Số trang vượt giới hạn PDF hoặc không có trong danh sách mốc trang giáo trình đã trích. |
| `page_needs_ocr` | Cảnh báo | Trang slide thiếu lớp chữ, cần mở PDF để rà hoặc OCR. |
| `page_unverified` | Cảnh báo | Giáo trình thiếu mốc trang, chỉ kiểm tra được theo tổng số trang. |
| `page_unverifiable` | Lỗi | Thiếu cả mốc trang và tổng số trang để kiểm tra nguồn giáo trình. |
| `section_unknown` | Lỗi | Mã mục không có trong giáo trình. |
| `page_section_mismatch` | Cảnh báo | Trang trích dẫn nằm ngoài các trang đã ghi nhận của mục. |
| `chapter_reason_missing` | Lỗi | `chapter_id` là `null` nhưng thiếu lý do. |
| `chapter_unknown` | Lỗi | Mã chương không có trong giáo trình đã trích. |
| `existing_unknown` | Lỗi | Mã điểm đề xuất trùng không có trong danh mục. |
| `existing_reason_missing` | Cảnh báo | Có mã điểm đề xuất trùng nhưng thiếu lý do. |
| `chapter_source_mismatch` | Cảnh báo | Mã chương của điểm không khớp chương từ các nguồn giáo trình chính. |
| `package_mixed` | Cảnh báo | Các tệp đầu vào mang nhiều mã gói khác nhau. |
| `duplicate_merged` | Cảnh báo | Các điểm trùng tiêu đề sau chuẩn hóa đã được gộp. |

## Tệp xuất và liên kết nguồn

`validate-export` ghi `export/validation-report.json` và `export/validation-report.md`. Khi hợp lệ, công cụ ghi thêm `export/knowledge-points.json` theo [schema gói xuất](src/learning_ingest/schemas/knowledge-points.schema.json) và bản Markdown cho HCNS rà soát, mặc định là `export/buoi-02-tri-thuc.md` với Buổi 02. Khi phát hiện lỗi kiểm tra, công cụ xóa gói JSON và Markdown cũ để tránh dùng nhầm.

- **Video** dùng `video.link_template` khi đã kiểm tra khả năng nhảy tới mốc trên SharePoint. Mẫu nhận `{url}`, `{seconds}`, `{ms}` và `{timestamp}`. Nếu SharePoint chưa nhảy đúng, để mẫu là `null`. Bản Markdown ghi link gốc nếu có và mốc chữ như **00:01:02** để người xem tự tua.
- **Slide và giáo trình** dùng `page_link_template` với `{url}` và `{page}` nếu trình xem đã được kiểm tra. Khi thiếu mẫu, công cụ ghi link gốc nếu có cùng số trang. Khi thiếu cả URL, công cụ vẫn ghi số trang và dòng “chưa có link”.

## Chạy lại và mã thoát

Khi đầu vào và cấu hình tương ứng giữ nguyên, chạy lại ghi đè tệp thay vì nối thêm, giữ nguyên mã gói rà soát và mã điểm kiến thức. Mã điểm dựa trên mã môn, mã buổi và tiêu đề chuẩn hóa. Tiêu đề trùng sau chuẩn hóa được gộp và giữ nguồn của cả hai điểm. Các tệp metadata vẫn có thể thay đổi thời điểm tạo hoặc thống kê cache.

| Mã thoát | Ý nghĩa |
| --- | --- |
| `0` | Hoàn thành. Khi xuất, có thể còn cảnh báo cần rà. |
| `1` | JSON AI có lỗi kiểm tra. |
| `2` | Tham số, cấu hình hoặc dữ liệu đầu vào không dùng được. |
| `3` | Thiếu thư viện tùy chọn. |
| `130` | Người dùng dừng lệnh. Có thể chạy tiếp với cache. |

## Kiểm thử và demo fixture

Chạy bộ kiểm thử từ thư mục gốc.

```text
python -m pytest -q
```

Chạy demo bằng PowerShell hoặc Bash.

```powershell
.\scripts\demo-fixture.ps1
```

```bash
bash scripts/demo-fixture.sh
```

Demo chạy đủ ba lệnh với phụ đề, slide, giáo trình và JSON AI giả lập có sẵn. Kết quả nằm trong `output/fixture-demo`. Cảnh báo mã gói khác `pkg-fixture` và trang thiếu lớp chữ là dự kiến. Nếu cần tạo lại slide giả lập, chạy `python tests/fixtures/make_fake_pdfs.py`.

## Bước cần MP4 thật

Kiểm tra các mục sau trên tài liệu thí điểm thật.

1. Khả năng PyAV giải mã âm thanh của MP4 thật.
2. Chất lượng ASR. Đối chiếu với bản chép tay đã kiểm tra dài 2–3 phút rồi chọn `small`, `medium` hoặc `large-v3`.
3. Thời gian CPU cần để xử lý một giờ video.
4. Các câu có bị cắt mất hoặc lặp ở ranh giới khúc chép lời hay không.
5. Front matter và mốc trang của giáo trình thật có khớp bản PDF hay không.
6. Slide thật có lớp chữ dùng được ở từng trang hay cần OCR.
7. Link SharePoint có mở đúng mốc video và đúng trang PDF hay không. Thử trên các tệp thật bằng trình xem của người dùng trước khi cấu hình mẫu link.
