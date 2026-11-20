# Thiết kế: kho tri thức gốc và luồng nội dung lên LMS

Trạng thái: **đề xuất, chờ duyệt** (2026-11-20). Đã chốt: kho gốc đặt trên SharePoint; LMS chưa có ngân hàng câu hỏi nào, câu có sẵn (legacy) được nhập vào kho rồi mới lên LMS. Ví dụ trong tài liệu là dữ liệu giả lập.

## 1. Mục tiêu

Số hoá nội dung đào tạo của 8 môn chuyên môn (PDF, slide, văn bản, giáo trình, video bài giảng) thành **điểm kiến thức có nguồn kiểm chứng**. Từ đó sinh ngân hàng câu hỏi, bài chữa và nội dung ôn tập, rồi đưa lên **YSVN LMS** để người vận hành nhập và bảo trì.

## 2. Nguyên tắc

1. **Điểm kiến thức trước, câu hỏi sau.** AI không sinh câu hỏi thẳng từ file. Câu hỏi, bài chữa và kiến thức cần nhớ chỉ sinh từ điểm kiến thức **đã duyệt**.
2. **Một nguồn sự thật.** Kho tri thức gốc giữ nội dung. LMS nhận **bản xuất**. Sửa nội dung thì sửa ở kho gốc rồi xuất lại. Trên LMS chỉ sửa cấu hình vận hành như thời gian thi hay số lần thi.
3. **Mọi nội dung đều trích được nguồn**, gồm trang PDF, slide, mục văn bản, mốc giờ video. Công cụ kiểm tra nguồn trước khi người duyệt đọc.
4. **Mã ổn định.** Mã điểm kiến thức và mã câu hỏi được cấp một lần, không đổi khi sửa tiêu đề hay nội dung.
5. **Có phiên bản.** Nguồn, văn bản pháp luật và điểm kiến thức đều có phiên bản. Khi một thứ thay đổi, hệ thống chỉ ra những gì cần duyệt lại.
6. **Người duyệt cuối.** AI chỉ soạn nháp. HCNS hoặc giảng viên duyệt trước khi xuất lên LMS.

## 3. Luồng tổng thể

```
Nguồn: PDF · slide (.pdf/.pptx) · văn bản (.docx) · giáo trình · video
  │
  ▼ 1. extract        chữ theo trang/slide/mục, OCR (file kèm), phiên âm, keyframe
  ▼ 2. draft          AI soạn nháp điểm kiến thức (FPT GLM-5.3-Flash / Claude)
  ▼ 3. validate       kiểm nguồn, trang, mốc giờ, cờ số liệu/thời hạn/điều luật
  ▼ 4. kb-merge       đưa vào kho gốc: khớp điểm đã có → sửa đổi, chưa có → cấp mã mới
  ▼ 5. review         HCNS duyệt bằng file Excel → review-apply cập nhật trạng thái
  ▼ 6. questions      AI sinh câu hỏi + giải thích từng phương án từ điểm đã duyệt → validate → duyệt
  ▼ 7. learning       kiến thức cần nhớ, ví dụ, lỗi thường gặp theo mục/chương → duyệt
  ▼ 8. export-lms     file Excel đúng mẫu nhập LMS + tai-lieu/ (+ video/) → .zip
  ▼
YSVN LMS (khoá ở trạng thái NHÁP → người soạn kiểm → gửi duyệt → xuất bản)

impact: khi nguồn / văn bản pháp luật / điểm kiến thức đổi → danh sách điểm, câu hỏi, bài học cần duyệt lại
```

## 4. Kho tri thức gốc

### 4.1 Vị trí: SharePoint (đã chốt 2026-11-20)

Nội dung đào tạo hiện lưu trên SharePoint, nên kho gốc cũng đặt ở đó: thư mục `learning-content` trong thư viện SharePoint của nhóm đào tạo, đồng bộ về máy người bảo trì bằng OneDrive. Công cụ đọc và ghi qua đường dẫn cấu hình `LEARNING_CONTENT_DIR`, không gắn cứng đường dẫn.

- Repo code này vẫn ở GitHub và **không chứa nội dung thật**.
- **Không đặt repo Git nào trong thư mục OneDrive**, kể cả repo code. OneDrive đồng bộ từng file trong `.git` nên dễ làm hỏng repo.
- Không có Git thì không có diff. Công cụ tự bù phần này, xem mục 4.3.

Trước khi chuyển lên SharePoint, mỗi loại dữ liệu chạy thử ở một chỗ khác nhau:

| Dữ liệu | `LEARNING_CONTENT_DIR` | Git |
|---|---|---|
| Thật | `data/kho/` trong repo này | Bị bỏ qua (`.gitignore` có `data/`) |
| Giả lập cho test | `tests/fixtures/kho-fake/` | Được commit |

Khi lên SharePoint chỉ cần đổi đường dẫn, code giữ nguyên. Khoá `.lock` và kiểm tra bản sao xung đột vẫn chạy ở thư mục thường, chỉ là không có gì để bắt.

### 4.2 Cấu trúc thư mục

Mỗi mục một file, để đồng bộ từng phần, khôi phục được từng mục và ít xung đột:

```
<SharePoint>/learning-content/
  registry/
    legal.yaml                 # danh mục văn bản pháp luật + hiệu lực
    lms-map.yaml               # mã khoá, mã ngân hàng LMS theo môn/chương
  <subject_id>/                # ví dụ phap-luat-chung-khoan
    subject.yaml               # chương, mục giáo trình (mã chương ↔ STT chương LMS)
    sources.yaml               # nguồn + phiên bản (sha256)
    knowledge-points/<kp_id>.yaml
    questions/<q_id>.yaml
    learning/<chapter_id>.yaml # kiến thức cần nhớ, ví dụ, lỗi thường gặp theo chương/mục
    exports/<ngày>-<lô>.yaml   # câu hỏi/bài học đã xuất lên LMS ở lô nào
  changelog/<ngày>-<giờ>-<lệnh>.md   # công cụ ghi mỗi lần đổi kho
  duyet/                       # file Excel review-export để HCNS điền
  xuat-lms/                    # file nhập LMS đã xuất (.xlsx, .zip)
  .lock                        # có người đang chạy lệnh ghi
```

Danh mục môn và lộ trình vẫn lấy từ `src/learning_ingest/registry/subjects.yaml` trong repo code. File nguồn gốc (PDF, slide, video) giữ nguyên chỗ hiện tại trên SharePoint. `sources.yaml` chỉ ghi đường dẫn và sha256.

### 4.3 Vận hành trên SharePoint

- **Chỉ công cụ ghi file YAML.** Người duyệt sửa qua file Excel bằng `review-apply`, không mở YAML ra sửa tay. Ít người ghi thì ít xung đột đồng bộ.
- **Mỗi lúc chỉ một người chạy lệnh ghi** (`kb-merge`, `review-apply`, `questions-import`):
  - Lệnh ghi tạo `.lock` có tên người chạy và giờ chạy. Lệnh khác thấy khoá thì dừng.
  - Chỉ chạy khi OneDrive đã đồng bộ xong.
- **Xem trước rồi mới ghi.** Mặc định lệnh ghi chỉ in thay đổi dự kiến. Thêm `--apply` thì mới ghi.
- **Nhật ký thay đổi thay cho diff.** Mỗi lần ghi, công cụ tạo `changelog/…md` liệt kê điểm và câu được thêm, được sửa (kèm nội dung trước → sau) hoặc bị bỏ, cùng tên người chạy. Mỗi file YAML vẫn giữ `history`.
- **`kb-check`** kiểm cả kho. Còn lỗi thì lệnh ghi từ chối chạy. Các điều kiện:
  - đúng schema;
  - tên file trùng với mã;
  - không có mã trùng;
  - tham chiếu hợp lệ: `kp_refs`, `legal_id`, phiên bản nguồn;
  - không có **bản sao xung đột của OneDrive**, ví dụ `kp-0a1b2c3d4e5f-TEN-MAY.yaml`.
- **Sao lưu** dựa vào lịch sử phiên bản và thùng rác của SharePoint. Khả năng khôi phục cả thư viện về một thời điểm trước cần IT xác nhận.

## 5. Mô hình dữ liệu

### 5.1 Nguồn (`sources.yaml`)

```yaml
- source_id: slide-ngay-01
  type: slide                  # video | slide | document | syllabus
  title: "Ngày 1 (giả lập)"
  path: "Nguon/Ngay 01.pdf"    # tương đối với thư mục nguồn trên SharePoint
  versions:
    - version: 1
      sha256: "3f2a…"
      added_at: 2026-11-19
  sharepoint_url: null
```

Cùng `source_id` mà `sha256` mới thì tạo phiên bản mới. Điểm kiến thức trích phiên bản cũ chuyển sang `needs_review`, vì số trang có thể đã lệch.

### 5.2 Văn bản pháp luật (`registry/legal.yaml`)

```yaml
- legal_id: luat-mau-01        # mã do kho cấp
  so_hieu: "00/2000/QH00"      # giả lập
  ten: "Luật mẫu (giả lập)"
  hieu_luc_tu: 2000-01-01
  trang_thai: con_hieu_luc     # con_hieu_luc | sua_doi_mot_phan | het_hieu_luc
  sua_doi_boi: []              # legal_id của văn bản sửa đổi/thay thế
  kiem_tra_lan_cuoi: 2026-11-20
```

Pháp chế hoặc HCNS giữ danh mục này. Khi `trang_thai` hoặc `sua_doi_boi` đổi, mọi điểm kiến thức có `legal_basis` trỏ tới văn bản đó chuyển sang `needs_review`.

### 5.3 Điểm kiến thức (`knowledge-points/<kp_id>.yaml`)

```yaml
kp_id: kp-0a1b2c3d4e5f          # cấp một lần, giữ nguyên mãi
revision: 3                     # tăng khi nội dung đổi
status: approved                # draft | approved | needs_review | retired
subject_id: phap-luat-chung-khoan
chapter_id: plck-c09            # null nếu chưa xác định chương
section_id: sec-3-2             # mục giáo trình, nếu có
title: "Thời hạn công bố thông tin mẫu (giả lập)"
summary: "…"
legal_basis:
  - {legal_id: luat-mau-01, dieu: "Điều 00", khoan: "1"}
sources:
  - {source_id: slide-ngay-01, version: 1, type: slide, pdf_page: 5, excerpt: "…"}
  - {source_id: video-ngay-01, version: 1, type: video, start_ms: 750000, end_ms: 920000}
  - {source_id: giao-trinh, version: 1, type: syllabus, pdf_page: 340}
verification_flags: [{kind: deadline, text: "…", note: "…"}]
review: {by: "hcns-01", at: 2026-11-21, note: null}
history:
  - {revision: 1, at: 2026-11-19, by: ai-draft, extract_id: ext-…}
  - {revision: 3, at: 2026-11-21, by: hcns-01, change: "sửa tóm tắt"}
superseded_by: null             # khi gộp hai điểm: điểm bị gộp trỏ sang điểm còn lại
```

### 5.4 Câu hỏi (`questions/<q_id>.yaml`)

```yaml
q_id: q-9f8e7d6c5b4a
status: approved                # draft | approved | needs_review | retired
kp_refs: [{kp_id: kp-0a1b2c3d4e5f, revision: 3}]   # điểm kiến thức + phiên bản lúc soạn
type: mot_lua_chon              # mot_lua_chon | nhieu_lua_chon | dung_sai
difficulty: trung_binh          # de | trung_binh | kho
stem: "… (giả lập)"
options:
  - {text: "…", correct: false, explanation: "Sai vì …"}
  - {text: "…", correct: true,  explanation: "Đúng theo …"}
explanation: "Giải thích chung + nguồn"   # ô "Giải thích" khi xuất LMS
shuffle_safe: true              # false nếu có phương án kiểu "Cả a và b"
origin: ai                      # ai | import (câu có sẵn, mục 8)
legacy_refs: []                 # câu import: [{file, sha256, vi_tri: "slide 4", ma_cu}], gộp trùng thì có nhiều dòng
flags: []                       # missing_answer | answer_conflict | possible_duplicate | chua_gan_kp | …
```

`kp_refs.revision` nhỏ hơn `revision` hiện tại của điểm kiến thức thì câu hỏi tự chuyển sang `needs_review`.

### 5.5 Nội dung học (`learning/<chapter_id>.yaml`)

Theo từng mục: `key_points` (kiến thức cần nhớ), `worked_examples` (ví dụ có lời giải), `common_mistakes` (lỗi thường gặp, lấy từ câu học viên hay sai khi đã có dữ liệu), `video_clips` (đoạn video theo mốc giờ). Mỗi mục đều có `kp_refs`.

## 6. Mã ổn định, phiên bản và phân tích ảnh hưởng

- **Cấp mã:**
  - Nháp AI có mã tạm.
  - Khi `kb-merge`, nếu nháp khớp một điểm đã có thì thành **sửa đổi** của điểm đó, tăng `revision`. Khớp được xét theo gợi ý `existing_knowledge_point_id` của AI, sau này thêm tìm theo nghĩa bằng embedding.
  - Nếu không khớp thì cấp `kp_id` mới. Định dạng giữ như schema hiện tại `kp-` + 12 hex, nên app không phải đổi.
  - Mã không phụ thuộc tiêu đề hay mã môn tạm, nên đổi mã môn hay mã chương không làm đổi mã điểm.
- **Gộp hoặc bỏ:** điểm bị gộp đặt `status: retired` và `superseded_by`, không xoá cứng. Câu hỏi trỏ vào nó chuyển sang `needs_review`.
- **Lệnh `impact`:** so kho hiện tại với lần chạy trước, liệt kê:
  - nguồn có phiên bản mới, kéo theo các điểm kiến thức trích nó;
  - văn bản pháp luật đổi hiệu lực, kéo theo các điểm có `legal_basis` trỏ tới nó;
  - điểm kiến thức tăng `revision`, kéo theo câu hỏi và nội dung học trỏ tới nó;
  - mục nào **đã xuất lên LMS** (tra `exports/`) để người vận hành cập nhật.

## 7. Duyệt nội dung (HCNS)

HCNS duyệt bằng **Excel**, không cần học công cụ mới:

- `review-export` tạo `duyet-<gói>.xlsx`, mỗi dòng một điểm kiến thức. Các cột:
  - mã, tiêu đề, tóm tắt, chương, nguồn kèm link;
  - cờ ⚠, gồm căn cứ pháp lý và tình trạng hiệu lực;
  - **Trạng thái** (Duyệt / Cần sửa / Loại), Sửa tiêu đề, Sửa tóm tắt, Ghi chú, Người duyệt.
- `review-apply` đọc file đã điền và cập nhật kho: trạng thái, `revision`, `history`.
- Câu hỏi duyệt theo cùng cách, file có thêm cột đáp án đúng và giải thích từng phương án.
- File `…-tri-thuc.md` hiện có vẫn dùng để đọc liền mạch, kèm `validation-report.md`.

## 8. Nhập câu hỏi có sẵn (legacy)

LMS chưa có ngân hàng nào. Mọi câu có sẵn, như đề cũ, Quick test hay file Excel/Word của giảng viên, đều vào kho gốc trước rồi mới lên LMS, giống câu do AI soạn.

`questions-import <file> --subject <id>` gồm các bước sau.

1. **Đọc file**
   - Excel đúng mẫu `CauHoi` của LMS: đọc thẳng.
   - Excel khác mẫu: khai báo cột trong một file cấu hình nhỏ (cột câu hỏi, các cột phương án, cột đáp án đúng).
   - Word, PDF, .pptx: `extract` lấy chữ, rồi AI tách thành câu hỏi và phương án. Bước này dễ sai nên người duyệt phải đối chiếu với file gốc.
2. **Chuẩn hoá**
   - Bỏ số thứ tự kiểu "Câu 5:".
   - Tách "a. / b) / c:" thành từng phương án.
   - Chuẩn Unicode và khoảng trắng.
   - Ghi `origin: import` và `legacy_refs`.
3. **Chống trùng**, so với kho và giữa các file với nhau:

   | Trường hợp | Xử lý |
   |---|---|
   | Cùng câu hỏi, cùng phương án, cùng đáp án đúng | Gộp thành một `q_id`, thêm dòng vào `legacy_refs` |
   | Cùng câu hỏi và phương án, **khác đáp án đúng** | Cờ `answer_conflict`, HCNS quyết |
   | Gần giống (khác vài chữ, đảo thứ tự phương án) | Cờ `possible_duplicate` kèm mã câu nghi trùng. HCNS chọn Gộp / Giữ cả hai / Loại |

   - Khớp chính xác bằng hash nội dung đã chuẩn hoá, phương án sắp theo thứ tự.
   - Câu gần giống: giai đoạn 3 so theo độ giống chữ, giai đoạn 5 thêm Vietnamese_Embedding + bge-reranker-v2-m3.
4. **Gắn điểm kiến thức.** AI gợi ý `kp_refs` trong các điểm đã duyệt của môn. Câu không gắn được vẫn duyệt được nhưng mang cờ `chua_gan_kp`, và `impact` không theo dõi được câu đó khi luật đổi.
5. **Cờ kiểm tra**
   - `missing_answer`: thiếu đáp án đúng. Ví dụ 20 câu Quick test CBTT chưa đánh dấu đáp án.
   - `verification_flags`: có số liệu, thời hạn hoặc điều luật, giống cờ của điểm kiến thức.
   - Trích văn bản không có trong `legal.yaml` hoặc đã hết hiệu lực.
   - `shuffle_safe: false`: có phương án kiểu "Cả a và b".
6. **Duyệt** bằng cùng file Excel như câu AI soạn, thêm các cột: file legacy, câu nghi trùng, cờ.

Câu legacy chưa duyệt thì không được xuất lên LMS.

## 9. Xuất lên LMS (`export-lms`)

Theo mẫu `mau-nhap-khoa-hoc.xlsx` của YSVN LMS:

| Trang LMS | Lấy từ kho gốc |
|---|---|
| KhoaHoc | Mỗi môn một khoá, mã trong `lms-map.yaml` (ví dụ `PLCK-2025`, cần HR chốt) |
| Chuong | Các chương trong `subject.yaml` (STT 1..N) |
| BaiHoc (Văn bản) | Mỗi **mục** một bài "Kiến thức cần nhớ", gồm các điểm đã duyệt của mục đó. Tài liệu đính kèm là slide nguồn (≤ 20 MB) |
| BaiHoc (Video), CauHoiGiuaVideo | Video + câu hỏi tại mốc giây từ điểm kiến thức có nguồn video (khi HR mở lại phần video) |
| NganHang | Mỗi chương một ngân hàng (`NH-<khoá>-C01`…), cộng các ngân hàng nhập sẵn |
| CauHoi | Câu hỏi `approved`. Ô Giải thích gồm giải thích chung và nguồn. Giải thích từng phương án chỉ lưu ở kho, vì LMS chỉ có một ô giải thích |
| BaiThi, CauTrucDe | Cấu hình đề (kiểm tra cuối chương, thi thử theo lộ trình). Số câu và điểm do HR chốt |

Quy tắc xuất:
- Chỉ xuất mục `approved`.
- Câu `shuffle_safe: false` thì bài thi chứa nó phải tắt trộn đáp án, hoặc phải sửa phương án.
- Ghi `exports/<lô>.yaml` để biết câu nào đã lên LMS ở lô nào. Lần xuất sau chỉ gồm phần mới hoặc đã đổi, kèm danh sách câu cần gỡ trên LMS.

**Mẫu `CauHoi` không có cột mã câu hỏi**, chỉ có mã ngân hàng. LMS nhận ra câu trùng bằng cờ trùng của nó. Công cụ bổ sung mã câu để người vận hành biết câu nào thay câu nào.

LMS làm được ba việc sau (xác nhận 2026-11-20):
- nhập vào một mã ngân hàng đã có thì LMS thêm câu và gắn cờ trùng để người duyệt;
- sửa, xoá và tìm từng câu trên giao diện;
- đổi `CauTrucDe` của bài thi đã xuất bản sang ngân hàng khác.

Cách cập nhật:
- **Thẻ mã ở cuối ô Giải thích**, ví dụ `[q-9f8e7d6c5b4a · r4]`: mã câu cộng phiên bản.
  - Khi LMS gắn cờ trùng, người vận hành giữ câu có số `r` lớn hơn và xoá câu kia.
  - Học viên báo lỗi cũng dẫn được mã này.
- **Mặc định cập nhật từng phần:**
  - `export-lms` chỉ xuất câu mới và câu đã đổi, vào đúng mã ngân hàng cũ.
  - Câu không đổi thì không xuất lại, nên không sinh cờ trùng thừa.
  - Kèm theo là `phieu-cap-nhat.xlsx`, liệt kê từng câu cần xoá trên LMS: câu đã có phiên bản mới thay thế và câu đã `retired`. Mỗi dòng có mã, phiên bản và đoạn đầu nội dung.
  - Phiếu này không dựa vào cờ trùng của LMS, vì một câu sửa nhiều có thể không bị LMS coi là trùng.
- **Khi đổi lớn**, ví dụ luật đổi làm phần lớn câu trong một chương bị ảnh hưởng (ngưỡng cấu hình được, mặc định 30%):
  - xuất ngân hàng mới, ví dụ `NH-<khoá>-C01-V2`;
  - đổi `CauTrucDe` sang ngân hàng mới;
  - tắt ngân hàng cũ.
- **Theo dõi lô xuất:**
  - `exports/<lô>.yaml` có trạng thái `cho_ap_dung`, đổi thành `da_ap_dung` khi người vận hành xác nhận đã làm xong phiếu.
  - Nếu còn lô chưa áp dụng thì `export-lms` cảnh báo trước khi xuất lô mới.

## 10. Lệnh dự kiến

| Lệnh | Việc | Giai đoạn |
|---|---|---|
| `extract`, `prepare-review`, `validate-export` | Đã có | — |
| slide `ocr_path` | Nhận chữ OCR kèm theo cho slide scan | 1 |
| `draft --provider fpt` | Gọi LLM soạn nháp điểm kiến thức (OpenAI-compatible, key trong `.env`) | 1 |
| `kb-merge` | Đưa gói đã kiểm vào kho gốc, khớp hoặc cấp mã | 2 |
| `review-export`, `review-apply` | Duyệt bằng Excel | 2 |
| `impact` | Phân tích ảnh hưởng khi nguồn, luật hoặc điểm kiến thức đổi | 2 |
| `kb-check` | Kiểm cả kho: schema, mã, tham chiếu, bản sao xung đột OneDrive | 2 |
| `questions-draft`, `questions-validate` | Sinh và kiểm câu hỏi | 3 |
| `questions-import` | Nhập câu có sẵn, chống trùng, gắn điểm kiến thức | 3 |
| `learning-draft` | Kiến thức cần nhớ, ví dụ, lỗi thường gặp | 3 |
| `export-lms` | Excel + zip đúng mẫu LMS | 3 |
| `frames` | Keyframe video ghép với transcript và slide | 4 (khi HR mở video) |
| `embed`, `search` | Tìm theo nghĩa, chống trùng, chatbot | 5 |

## 11. Lộ trình

| GĐ | Nội dung | Xong khi |
|---|---|---|
| 1 | OCR kèm theo, `draft` qua FPT, soạn gói Ngày 1 | HCNS audit gói Ngày 1, tỷ lệ lỗi `validate-export` chấp nhận được |
| 2 | Kho gốc trên SharePoint, mã ổn định, phiên bản, `legal.yaml`, duyệt bằng Excel, `impact`, `kb-check` | Sửa tiêu đề không đổi mã. Đổi một nguồn giả lập thì `impact` liệt kê đúng điểm bị ảnh hưởng. Chạy `kb-merge` hai lần liên tiếp trên thư mục SharePoint thật không sinh file trùng. `kb-check` bắt được bản sao xung đột giả lập |
| 3 | Câu hỏi + bài chữa + `questions-import` + `export-lms` | Nhập Quick test CBTT và ít nhất một file legacy khác: câu trùng được gộp đúng, câu thiếu đáp án bị gắn cờ. File nhập LMS thử của môn Pháp luật được LMS nhận ở trạng thái nháp |
| 4 | Video: phiên âm, keyframe, câu hỏi giữa video | Khi HR mở lại |
| 5 | Embedding + tìm kiếm / chatbot (pgvector khi cần) | Khi có nhu cầu tìm kiếm hoặc nhiều người cùng sửa |

## 12. Chưa làm, có lý do

- **PostgreSQL + pgvector:** file YAML trên SharePoint đủ cho giai đoạn 1–3 và dễ bảo trì hơn. Chuyển sang DB khi có chatbot hoặc nhiều người cùng sửa.
- **Docling / MinerU:** nặng. Slide có chữ thì pypdf đã đủ, slide scan thì Vision LLM xử lý được. Chỉ cân nhắc khi bảng trong giáo trình bị đọc sai nhiều.
- **Embedding toàn bộ video:** transcript + keyframe là đủ làm nền.

## 13. Đã chốt

- **2026-11-20:**
  - Kho gốc đặt trên SharePoint (mục 4).
  - LMS chưa có ngân hàng câu hỏi nào. Câu legacy nhập vào kho rồi mới lên LMS (mục 8).
  - Khả năng của LMS:
    - nhập trùng mã ngân hàng thì thêm câu và gắn cờ trùng;
    - sửa, xoá, tìm từng câu;
    - đổi ngân hàng của bài thi đã xuất bản.
  - Cách cập nhật mặc định: cập nhật từng phần + phiếu cập nhật (mục 9).

## 14. Cần chốt

1. **SharePoint:**
   - thư mục nào làm `learning-content`?
   - ai có quyền ghi?
   - có bật lịch sử phiên bản không? (cần trước giai đoạn 2)
2. **Câu hỏi legacy:** hiện có những file nào, định dạng gì, đã có đáp án đúng chưa?
3. **LMS** (chưa gấp, cần từ giai đoạn 4):
   - LMS có xuất ngược dữ liệu ra được không? Ví dụ kết quả làm bài, để lấy "lỗi thường gặp".
   - Ô Giải thích có gắn link tới mốc giây video được không?
4. **Người duyệt:** HCNS, giảng viên hay pháp chế duyệt phần nào? Ai giữ `legal.yaml`?
5. **Bài văn bản** trên LMS: mỗi mục giáo trình một bài (đề xuất), hay mỗi điểm kiến thức một bài?
6. **Mã khoá LMS** cho 8 môn và **cấu trúc đề thi mô phỏng** (HR).
