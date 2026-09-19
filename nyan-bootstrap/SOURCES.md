# Nguồn và phạm vi sử dụng

## Tài liệu supplier do Nyan cung cấp

- `supplier-sources/vietshare.original.md`: giữ nguyên file upload `Đã dán markdown (1)(20260919-063134).md`. Source URL: https://token.vietshare.site/docs
- `supplier-sources/roboticvn.original.md`: giữ nguyên file upload `Đã dán markdown (2)(20260919-063152).md`. OpenAPI được nguồn dẫn: https://api.roboticvn.com/api/v2/docs/openapi.json
- `supplier-sources/khommo.user-excerpt.md`: chép các phần nghiệp vụ từ nội dung dán trong hội thoại. Source URL: https://api.khommo.vn/docs/partner

Không có API key được dùng, không có giao dịch thật được thực hiện để tạo bộ này. Độ đầy đủ tài liệu không chứng minh độ tin cậy supplier.

## Tài liệu chính thức tham khảo ngày 19/09/2026

- Codex subagents: https://developers.openai.com/codex/multi-agent/
- Codex worktrees: https://developers.openai.com/codex/app/worktrees/
- Codex GitHub code review: https://developers.openai.com/codex/integrations/github/
- Codex GitHub Action: https://developers.openai.com/codex/github-action/
- Codex authentication/billing methods: https://developers.openai.com/codex/auth/
- GitHub workflow triggers và GITHUB_TOKEN: https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow
- GitHub review/self-approval: https://docs.github.com/en/pull-requests/how-tos/review-pull-requests/reviewing-proposed-changes-in-a-pull-request
- Actions secure use: https://docs.github.com/en/actions/reference/security/secure-use
- Container publishing: https://docs.github.com/en/actions/tutorials/publish-packages/publish-docker-images
- Telegram digital goods/Stars: https://core.telegram.org/bots/payments-stars

Đây là link để Codex kiểm tra đúng version khi cấu hình, không phải cam kết mọi capability đã enabled trên tài khoản Nyan. Riêng behavior GITHUB_TOKEN hiện được docs mô tả: push từ token không tự khởi phát push workflow; PR opened/synchronize/reopened có ngoại lệ tạo run chờ approve. Phải xác minh lại khi làm unattended dispatcher, không áp dụng khẩu quyết cũ “mọi event đều không trigger”.

## Quyết định thiết kế của bộ khởi động (không phải nguồn supplier)

Phân vai, giới hạn hai writer, milestone/issues NSB, mock-first, owner merge, container-first CD và các guard là đề xuất cho dự án. Cấu trúc thư mục ứng dụng để Codex lựa chọn. Chưa tạo issue, PR, Project, Actions hay cấu hình remote trong lần soạn bộ tài liệu này.
