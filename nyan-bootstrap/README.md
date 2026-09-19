# Nyan Shop Bot — bộ khởi động multi-agent

Ngày soạn: 19/09/2026. Repo đích: `NhanDuong21/nyan-shop-bot`.
Đây là tài liệu giao việc, **không phải code ứng dụng hay workflow đã được triển khai**.
Lúc kiểm tra repo chỉ có README.md; chưa có issue/PR trong kết quả API.

## Dùng ngay

Giải nén để thư mục `nyan-bootstrap/` nằm trong thư mục local của repo. Mở repo trong Codex.
Gửi: “Đọc nyan-bootstrap/prompts/01-bootstrap.md và thực hiện Phase 0 trong tài liệu đó.”
Codex phải ignore bộ đầu vào này trước khi staging. Không đưa nguyên bộ nguồn đối tác lên repo public.

Prompt 01 yêu cầu Codex tạo thật issue, milestone, Project nếu có quyền; triển khai bootstrap trong một PR; chạy kiểm thử; không tự merge. Thiếu quyền phải báo rõ và vẫn hoàn thành phần local.

Sau PR bootstrap được review và Nyan merge, dùng prompt 02 ở phiên Codex điều phối. Các prompt 03, 04, 05 dùng cho worker backend, Antigravity UI và reviewer ở phiên/worktree riêng.

## Vai trò

| Vai trò | Công cụ | Quyền theo quy trình |
|---|---|---|
| Nyan | GitHub + Codex/Antigravity | Chọn mục tiêu, duyệt merge, cấp secret và duyệt giao dịch thật |
| Coordinator | Codex | Đọc issue, phân việc có phụ thuộc, quản lý claim, tích hợp |
| Backend/Supplier Worker | Codex | Một issue + một branch/worktree; test và mở PR |
| UI Worker | Antigravity | UI admin trên interface đã có; không sửa nghiệp vụ tiền |
| Reviewer | Phiên Codex độc lập | Đọc diff/kiểm thử và ghi findings theo HEAD SHA; không tự sửa rồi tự duyệt |
| CI/CD | GitHub Actions | Kiểm thử, build, publish; không phải LLM và không tự mở app trên PC |

Giới hạn ban đầu: tối đa hai luồng ghi code đồng thời; reviewer có thể chạy riêng. Một agent không cần tương ứng một model khác. Không cài thêm Claude hay dịch vụ trả phí mới.

## Mức tự động hóa

- Có ngay sau bootstrap được merge/cấu hình: CI theo PR, kiểm tra lại main, build và publish container sau main xanh.
- Có thể bật bằng tích hợp chính thức: Codex automatic code review sau khi cấu hình Codex cloud cho repo.
- Chỉ có sau khi có đích triển khai: deploy môi trường staging dùng mock. Thiếu host/secret phải báo BLOCKED, không báo deploy thành công.
- Không mặc định có: gắn label là Codex/Antigravity trên PC tự mở và làm việc. Điều phối local cần phiên agent đang chạy; unattended dispatch cần runner/integration thực sự.
- Không tự bật: thanh toán thật, mua supplier thật, top-up, hoàn tiền thật, deploy production, trả phí API LLM.

## Nguồn và độ chắc chắn

` supplier-sources/ ` chứa hai file người dùng gửi được giữ nguyên byte, và bản chép có ghi rõ phạm vi từ nội dung KhoMMO người dùng dán. Các file này là bằng chứng tài liệu, không phải kết quả API live.
`CONSTRAINTS.md` và `BACKLOG.md` là đề xuất thiết kế/giao việc, không phải đặc tả do supplier cam kết.
`SOURCES.md` ghi các tài liệu chính thức đã tham khảo. Codex phải kiểm tra version/capability thực tế trước khi dùng config hoặc CLI.

## Điểm đặc biệt khi chỉ có một GitHub identity

Nhiều phiên AI dùng cùng `gh` login vẫn là một GitHub user, không phải nhiều reviewer độc lập về quyền. Tác giả PR không thể tự APPROVE PR. Phiên review có thể COMMENT bằng chứng; Nyan xem và merge thủ công sau CI. Không tạo rule đòi một approval bất khả thi, không dùng --admin để lách gate. Hạn chế agent không merge là quy ước quy trình, không phải ranh giới quyền thật nếu cùng dùng token có quyền merge.

## Hồ sơ đầu ra cần đòi từ Codex

Bảng có link thật: issue, PR, Actions run, commit SHA, Project; kiểm thử đã chạy và kết quả; phần chưa chạy/thiếu quyền; thư mục worktree cho UI; hai issue độc lập đầu tiên cho wave tiếp theo.
Không chấp nhận “đã có CI/CD” chỉ vì đã tạo file YAML.
