# learning-ingest

## Mục đích

Công cụ nội bộ giúp HCNS chuyển video hoặc phụ đề, slide PDF và giáo trình Markdown của một buổi đào tạo thành các điểm kiến thức có nguồn để rà soát trước khi đưa vào ứng dụng ôn thi.

Phạm vi thí điểm là **Luật 2025 / Buổi 02**. Môn Pháp luật chứng khoán (`phap-luat-chung-khoan`) dùng chung cho Môi giới, Phân tích tài chính và Quản lý quỹ. Mã buổi học và mã chương giáo trình độc lập. Dùng bảng ánh xạ chương trong manifest và đối chiếu với tiêu đề giáo trình. Tuyệt đối không suy ra Buổi 02 là Chương 2.

## Danh mục môn chuyên môn và lộ trình

Người học hoàn thành các môn chuyên môn theo lộ trình đã chọn để lấy chứng chỉ chuyên môn, sau đó dự **kỳ thi sát hạch cấp chứng chỉ hành nghề** khi đáp ứng điều kiện của lộ trình.

| Số | Môn chuyên môn | Mã môn | Trạng thái mã | Lộ trình |
| --- | --- | --- | --- | --- |
| 1 | Pháp luật về chứng khoán và thị trường chứng khoán | `phap-luat-chung-khoan` | `confirmed` | MG, PTTC, QLQ |
| 2 | Những vấn đề cơ bản về chứng khoán và thị trường chứng khoán | `co-ban-chung-khoan` | `proposed` | MG, PTTC, QLQ |
| 3 | Phân tích và đầu tư chứng khoán | `phan-tich-dau-tu-chung-khoan` | `proposed` | MG, PTTC, QLQ |
| 4 | Môi giới chứng khoán và tư vấn đầu tư chứng khoán | `moi-gioi-tu-van-dau-tu` | `proposed` | MG, PTTC, QLQ |
| 5 | Tư vấn tài chính và bảo lãnh phát hành chứng khoán | `tu-van-tai-chinh-bao-lanh-phat-hanh` | `proposed` | PTTC, QLQ |
| 6 | Phân tích báo cáo tài chính doanh nghiệp | `phan-tich-bao-cao-tai-chinh` | `proposed` | PTTC, QLQ |
| 7 | Quản lý quỹ và tài sản | `quan-ly-quy-va-tai-san` | `proposed` | QLQ |
| 8 | Chứng khoán phái sinh và thị trường chứng khoán phái sinh | `chung-khoan-phai-sinh` | `proposed` | Bổ sung để hành nghề nghiệp vụ phái sinh tương ứng |

Trong **8 môn chuyên môn**, lộ trình Môi giới chứng khoán (MG) yêu cầu 4 môn, Phân tích tài chính (PTTC) yêu cầu 6 môn và Quản lý quỹ (QLQ) yêu cầu 7 môn. Quản lý quỹ còn có điều kiện kinh nghiệm. HCNS xác nhận các mã `proposed` trước khi app sử dụng. [Danh mục YAML](src/learning_ingest/registry/subjects.yaml).

Công cụ kiểm tra `subject_id` của mọi manifest với danh mục. Có thể bỏ `subject_name` và `programs` để dùng giá trị từ danh mục. Nếu khai báo, tên môn phải khớp chính xác và tập mã lộ trình phải khớp, có thể khác thứ tự. Chạy `learning-ingest subjects` để xem mã, tên và số môn theo từng lộ trình.

## Dữ liệu và bảo mật

Repo chỉ lưu mã nguồn, mẫu cấu hình và dữ liệu giả lập. Đặt video, phụ đề, slide, giáo trình và JSON AI thật trong `data/`. Giữ bản chép lời, gói rà soát, cache và kết quả trong `output/`. Git bỏ qua cả hai thư mục. Quy trình này không dùng dữ liệu khách hàng.

Lệnh `draft` gửi gói rà soát đến dịch vụ AI đã cấu hình, mặc định là FPT AI qua API tương thích OpenAI. Các lệnh còn lại xử lý trên máy và không gửi dữ liệu đi. Nếu dùng ASR, chuẩn bị model trên máy để chép lời cục bộ. Gói xuất là **BẢN NHÁP**, ở trạng thái `pending_review` cho đến khi HCNS kiểm tra nội dung và đối chiếu nguồn.

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
| `subject_name`, `programs` | Tùy chọn. Lấy từ danh mục môn nếu bỏ trống trường, hoặc kiểm tra khớp nếu khai báo. |
| `course_name` | Tên hiển thị của khóa. |
| `video` | Mã nguồn, MP4 hoặc audio, phụ đề nếu có, link mở video và mẫu link theo mốc nếu đã thử. Công cụ ưu tiên phụ đề được khai báo. |
| `slides`, `syllabus` | Danh sách slide PDF và giáo trình Markdown. Mỗi nguồn có `source_id` riêng và có thể khai báo link PDF gốc. |
| `related_chapter_ids` | Mã chương HCNS đã xác nhận liên quan tới buổi học. Nếu để trống, gói rà soát chọn mục giáo trình theo độ trùng từ ngữ. |
| `catalog_path` | Danh mục điểm kiến thức đã có, dùng để phát hiện nội dung có thể trùng. |
| `transcription`, `review`, `export` | Cấu hình chép lời, giới hạn gói rà soát và tên tệp Markdown xuất. |

Khi đưa vào sử dụng, lưu manifest chứa đường dẫn và link nội bộ trong `data/`, rồi sửa đường dẫn tương đối theo vị trí tệp mới. [Mẫu Buổi 01](examples/luat-2025-buoi-01.manifest.yaml), [mẫu Buổi 02](examples/luat-2025-buoi-02.manifest.yaml), [schema manifest](src/learning_ingest/schemas/manifest.schema.json).

## Chạy một buổi học

Dùng cùng một thư mục `--out` cho cả ba lệnh. Ví dụ dưới đây giả sử HCNS đã lưu manifest thật trong `data/raw/luat-2025/buoi-02/` và lưu JSON AI vào thư mục làm việc sau bước 2.

### PowerShell

```powershell
$manifest = "data/raw/luat-2025/buoi-02/manifest.yaml"
$work = "output/luat-2025/buoi-02"

learning-ingest extract --manifest $manifest --out $work
learning-ingest prepare-review --manifest $manifest --out $work
# Dán gói rà soát vào AI và lưu phản hồi thành ai-output.json
learning-ingest validate-export --input "$work/ai-output.json" --out $work
```

### Bash

```bash
manifest="data/raw/luat-2025/buoi-02/manifest.yaml"
work="output/luat-2025/buoi-02"

learning-ingest extract --manifest "$manifest" --out "$work"
learning-ingest prepare-review --manifest "$manifest" --out "$work"
# Dán gói rà soát vào AI và lưu phản hồi thành ai-output.json
learning-ingest validate-export --input "$work/ai-output.json" --out "$work"
```

Nếu đã có các thư viện cần thiết, có thể đặt `$env:PYTHONPATH = "src"` trong PowerShell hoặc `export PYTHONPATH=src` trong Bash và dùng `python -m learning_ingest` thay cho `learning-ingest`. Trên Git Bash cho Windows, đặt thêm `export PYTHONIOENCODING=utf-8`.

1. **`extract`** tạo `transcript.vtt`, `transcript.jsonl`, `slides.jsonl`, `slides-index.json`, `syllabus.json`, `catalog.json` và `extract-manifest.json`. Các tệp chứa mã đoạn, mốc thời gian, mã nguồn, số trang và dữ liệu dùng để kiểm tra trích dẫn.
2. **`prepare-review`** tạo `review/package.md`, `review/prompt.md` và `review/review-manifest.json` có `package_id`. Nếu gói dài, công cụ chia thành `package-part-NN-of-MM.md`. Có thể điều chỉnh ngưỡng chia bằng `--max-chars`. Chạy **`draft`** để gửi các phần đến dịch vụ AI đã cấu hình, hoặc dán từng phần vào AI khác và tự lưu JSON trả về, giữ nguyên `package_id`.
3. **`validate-export`** kiểm tra JSON AI với dữ liệu đã trích và ghi báo cáo. Nếu có nhiều phần, lặp `--input` theo thứ tự, ví dụ `--input part1.json --input part2.json`.

### Soạn nháp bằng AI (`draft`)

Sau khi chạy `prepare-review`, đặt các biến dưới đây trong `.env` ở thư mục hiện tại hoặc chỉ định tệp khác bằng `--env-file`. Giá trị đã đặt trong môi trường được ưu tiên hơn giá trị trong tệp.

| Biến | Cách dùng |
| --- | --- |
| `FPT_API_KEY` | Bắt buộc. Điền `FPT_API_KEY=...` bằng khóa của bạn. |
| `FPT_BASE_URL` | Mặc định `https://token-api.fpt.ai/v1`. Lệnh gửi yêu cầu đến `/chat/completions` dưới URL này. |
| `FPT_MODEL` | Mặc định `GLM-5.3-Flash`. Có thể ghi đè bằng `--model`. |
| `FPT_CA_BUNDLE` | Đường dẫn tùy chọn đến tệp CA dạng PEM. Mặc định dùng chứng chỉ CA của `certifi`. |
| `FPT_MAX_TOKENS` | Giới hạn token đầu ra, tùy chọn. |
| `FPT_TEMPERATURE` | Mặc định `0.2`. |
| `FPT_REASONING_EFFORT` | Mức suy luận, mặc định `low`. Giá trị `high` và `max` có thể kéo dài thời gian suy luận đến giới hạn khoảng 300 giây cho mỗi yêu cầu của cổng API FPT. Đặt `none` hoặc để trống để bỏ tham số này khi dùng dịch vụ không hỗ trợ. |
| `FPT_JSON_MODE` | Đặt `1` hoặc `true` để yêu cầu chế độ JSON của API. Mặc định tắt. |
| `FPT_TIMEOUT` | Mặc định `600` giây cho mỗi yêu cầu. Có thể ghi đè bằng `--timeout`. |

`draft` nhận phản hồi theo luồng (streaming) vì GLM-5.3-Flash có thể suy luận trong vài phút, khiến cổng API trả lỗi HTTP 524 nếu phải chờ toàn bộ phản hồi. Nếu FPT đóng luồng trước khi báo hoàn tất, `draft` giữ phần đã nhận và ghi trạng thái `stream_cut`; với giới hạn khoảng 300 giây của FPT, hãy giữ `FPT_REASONING_EFFORT=low` hoặc chia nhỏ gói bằng `prepare-review --max-chars`.

Ví dụ PowerShell cho gói một phần. Dùng `--dry-run` để xem dịch vụ, model, URL, mức suy luận và số ký tự từng phần trước khi gửi. Chạy lệnh `validate-export` do `draft` in ra để dùng đúng danh sách tệp.

```powershell
learning-ingest draft --out $work --dry-run
learning-ingest draft --out $work
learning-ingest validate-export --input "$work/draft/ai-output.json" --out $work
```

Trong `<out>/draft/`, `ai-output.json` là JSON của gói một phần. Gói nhiều phần dùng `ai-output-part-KK-of-NN.json`. `response-part-KK.txt` lưu phản hồi gốc để xem cả khi AI trả lời sai định dạng hoặc bị cắt. `draft-run.json` ghi thông tin lần chạy và kết quả từng phần.

Dùng `--part K` để gửi riêng phần K, đánh số từ 1. Khi tệp JSON đích đã tồn tại, thêm `--force` để ghi đè. Sau khi kiểm tra và xuất, kết quả vẫn là **BẢN NHÁP** chờ HCNS rà soát.

| Mã thoát của `draft` | Ý nghĩa |
| --- | --- |
| `0` | Đã lưu JSON cho tất cả phần được chọn, hoặc đã xem cấu hình bằng `--dry-run`. |
| `1` | Có phản hồi bị cắt hoặc không đọc được thành một đối tượng JSON. Những phần dùng được vẫn được lưu. |
| `2` | Cấu hình hoặc đầu vào không dùng được, hoặc tệp đích đã tồn tại mà chưa có `--force`. |
| `4` | Lỗi kết nối hoặc lỗi từ dịch vụ AI. |

### Chạy thử một đoạn

Thêm `--clip-start 00:10:00 --clip-end 00:12:30` vào lệnh `extract` và dùng thư mục `--out` riêng cho lần chạy thử. Có thể khai báo mốc mặc định trong `video.clip`. Mốc transcript vẫn tính từ đầu video gốc. Ví dụ, câu ở phút 10 vẫn có mốc khoảng `00:10:00` trong đoạn chạy thử.

### Cache và chạy tiếp

Mặc định, `extract` lưu cache trong `<out>/.cache`. Công cụ dùng lại kết quả trích slide và từng khúc chép lời đã hoàn thành nếu dữ liệu và cấu hình tương ứng vẫn khớp. Sau khi dừng giữa chừng, chạy lại cùng lệnh với cùng cache để tiếp tục từ khúc chưa xong. Dùng `--cache-dir` để chọn thư mục cache và `--no-cache` để chạy lại mà không dùng cache.

## Gói tài liệu (không có video)

Manifest không cần `video` nếu có ít nhất một trong: `slides`, `documents`, `syllabus`. Khi đó `extract` bỏ qua transcript (ghi `transcript.jsonl` rỗng, không có `.vtt`) và gói review không có phần transcript.

- `slides[].path`: `.pdf` (theo trang) hoặc `.pptx` (theo slide; nguồn trích vẫn dùng `pdf_page` = số thứ tự slide, nhãn hiển thị "slide N"). Slide ẩn vẫn được trích, ghi chú của người trình bày được thêm vào cuối dưới dạng "Ghi chú: ...".
- `slides[].ocr_path` (tùy chọn) là đường dẫn đến file Markdown OCR, tính từ thư mục chứa manifest.
  Dùng `## Trang PDF N` hoặc `<!-- page: N -->` làm mốc, với `N` là số trang PDF hoặc số thứ tự slide PowerPoint, bắt đầu từ 1.
  `extract` chỉ bổ sung chữ OCR cho trang hoặc slide được đánh dấu cần OCR và có nội dung trong file.
  Công cụ cảnh báo cả khi bỏ qua mốc OCR ở trang đã có chữ và khi trang vẫn cần OCR.
  Gói review đánh dấu phần chữ lấy từ OCR để người rà soát đối chiếu ảnh gốc.
- `documents[]`: văn bản `.docx` (`source_id`, `title`, `path`, `sharepoint_url`). Tách mục theo style Title / Heading N; chữ trước tiêu đề đầu tiên thành mục "(Mở đầu)". AI trích nguồn bằng `{"type": "document", "source_id": ..., "section_id": ...}`; mã mục không đúng báo lỗi `section_unknown`.
- `syllabus.path`: `.md` (như trước) hoặc `.pdf` có lớp chữ. Dòng bắt đầu bằng "Chương <số>" được nâng thành tiêu đề để `chapters[].heading_match` khớp; PDF scan (hơn một nửa số trang không có chữ) bị từ chối, cần OCR rồi dùng bản `.md` có mốc trang.
- `.pptx` và `.docx` cần thư viện tuỳ chọn: `pip install -e ".[office]"` (python-pptx, python-docx). Thiếu thư viện thì lệnh `extract` thoát với mã 3.

Quy ước `session_id` / `session_label` cho gói không có video:

| Loại gói | `session_id` | `session_label` |
| --- | --- | --- |
| Chương giáo trình | `<course>-giao-trinh-cNN` | `Giáo trình · Chương X` |
| Tài liệu | `<course>-tai-lieu-<slug>` | `Tài liệu · <tên>` |

`session_id` đi vào `knowledge_point_id` (cùng môn, buổi và tiêu đề cho cùng ID), nên không được đổi sau khi đã dùng.

## Giáo trình Markdown

Bản chuyển từ PDF của Giáo trình Luật dùng `## Trang PDF N` trên dòng riêng để đánh dấu trang. Tiêu đề chương ở cấp `###` và các mục đánh số như `1.1.` hoặc `1.1.1.` ở cấp `####`. Manifest có thể khai báo mã chương cho bản Markdown hiện có.

```yaml
syllabus:
  source_id: giao-trinh-luat
  path: giao-trinh-luat.md
  chapters:
    - chapter_id: plck-c01
      heading_match: '^Chương\s+I\b'
      title: Khái quát pháp luật về chứng khoán và thị trường chứng khoán
      id_status: proposed
```

`heading_match` tìm trong nội dung tiêu đề, bỏ qua hoa thường. Lần khớp đầu tiên mở chương. Tiêu đề lặp trong mục lục được xử lý như tiêu đề thường. Nếu một tiêu đề khớp hai mã chương, công cụ báo lỗi. Nếu một mã không có tiêu đề khớp, công cụ cảnh báo. `syllabus.json` lưu `chapter_candidates` theo thứ tự xuất hiện, gồm tiêu đề, cấp, trang PDF và số lần gặp mã số hoặc số La Mã. HCNS có thể dùng danh sách này để lập bảng ánh xạ.

Khi có bảng ánh xạ trong manifest, công cụ ưu tiên bảng này và cảnh báo nếu giáo trình cũng khai báo `chapters` trong YAML front matter. Nếu manifest không có bảng ánh xạ, công cụ dùng `chapters` từ front matter, đối chiếu với `title`, `heading` hoặc mã `{#chapter_id}` trên tiêu đề. Khi cả hai bảng đều vắng, có thể gắn mã trực tiếp, ví dụ `### Chương I. Tổng quan {#c1}`. Công cụ giữ khoảng trang đã khai trong front matter và tính khoảng trang từ các mục thuộc chương cho hai cách còn lại. Nếu chưa xác định được chương của một điểm kiến thức, trả `chapter_id: null` kèm `chapter_id_reason`.

Công cụ cũng hỗ trợ mốc HTML `<!-- page: N -->`. Dòng chỉ chứa mốc cập nhật số trang cho nội dung tiếp theo. Có thể dùng `syllabus.page_marker_pattern` để thay cả hai mẫu mặc định. Regex tùy chỉnh cần đúng một nhóm bắt số trang. Thiếu mốc trang thì bước trích xuất cảnh báo. Khi có `pdf_page_count`, bước kiểm tra chỉ xác nhận trích dẫn nằm trong tổng số trang và vẫn cảnh báo. Nếu thiếu cả mốc lẫn tổng số trang, trích dẫn trang giáo trình sẽ bị báo lỗi.

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

Khi đầu vào và cấu hình tương ứng giữ nguyên, chạy lại giữ nguyên mã gói rà soát và mã điểm kiến thức. Dùng `draft --force` để ghi đè JSON nháp đã có. Mã điểm dựa trên mã môn, mã buổi và tiêu đề chuẩn hóa. Tiêu đề trùng sau chuẩn hóa được gộp và giữ nguồn của cả hai điểm. Các tệp metadata vẫn có thể thay đổi thời điểm tạo hoặc thống kê cache.

| Mã thoát | Ý nghĩa |
| --- | --- |
| `0` | Hoàn thành. Khi xuất, có thể còn cảnh báo cần rà. |
| `1` | Phản hồi AI không dùng được hoặc JSON AI có lỗi kiểm tra. |
| `2` | Tham số, cấu hình hoặc dữ liệu đầu vào không dùng được. |
| `3` | Thiếu thư viện tùy chọn. |
| `4` | Lỗi kết nối hoặc dịch vụ AI. |
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

Công cụ giữ nguyên transcript ASR để đối chiếu nguồn theo mã đoạn và mốc thời gian. Gói rà soát hướng dẫn AI dùng thuật ngữ đúng trong tiêu đề và tóm tắt sau khi đối chiếu slide và giáo trình, chép nguyên văn khi trích dẫn và đánh dấu chỗ chép sai có thể làm đổi nghĩa số liệu, thời hạn hoặc điều khoản. HCNS kiểm tra lại các điểm này. `transcription.initial_prompt` cung cấp từ vựng chuyên ngành cho faster-whisper khi chép lời.

Kiểm tra các mục sau trên tài liệu thí điểm thật.

1. Khả năng PyAV giải mã âm thanh của MP4 thật.
2. Chất lượng ASR. Đối chiếu với bản chép tay đã kiểm tra dài 2–3 phút rồi chọn `small`, `medium` hoặc `large-v3`.
3. Thời gian CPU cần để xử lý một giờ video.
4. Các câu có bị cắt mất hoặc lặp ở ranh giới khúc chép lời hay không.
5. Bảng ánh xạ chương và mốc trang của giáo trình Markdown có khớp bản PDF hay không.
6. Slide thật có lớp chữ dùng được ở từng trang hay cần OCR.
7. Link SharePoint có mở đúng mốc video và đúng trang PDF hay không. Thử trên các tệp thật bằng trình xem của người dùng trước khi cấu hình mẫu link.
