# Backlog đề xuất — dùng mã ổn định, không đoán số issue GitHub

Codex tạo issue thật nếu có quyền. Dùng mã NSB trong title/body để chạy seed lại không trùng. Thêm marker `<!-- nyan-task:NSB-... -->` và lưu mapping mã → URL thật. Các số bên dưới là mã công việc, không phải issue # đã tồn tại.

Mỗi issue cần mục tiêu, in/out of scope, phụ thuộc, area/owner role, allowed files hoặc module boundary, acceptance criteria, test bắt buộc, risk, evidence khi xong. Không đóng issue khi chỉ mở PR.

## Milestone M0 — Foundation

### NSB-001 — Bootstrap repo, agent workflow và CI/container delivery
Owner: coordinator. Dependency: không. Risk: high (workflow/security).
Acceptance: API health + DB migration + mock catalog nhỏ + admin gọi API + bot handler kiểm thử offline; agent instructions và mẫu issue/PR; scripts chạy trên PowerShell/Linux; một lệnh verify; CI thật có aggregate ci-gate; main xanh mới publish image; PR link và CI evidence. Không live purchase/payment. Phase 0 chỉ implement issue này.

## Milestone M1 — Catalog và các kết nối chỉ đọc

### NSB-010 — Catalog chuẩn hóa, capability model và schema sinh từ code
Owner: backend. Dependency: NSB-001.
Acceptance: currency/unit rõ, supplier_product/variant tách biệt, mapping do admin duyệt; last_synced/stale/error state; fake supplier ổn định; OpenAPI từ FastAPI + fixture/client dùng cho UI; không làm purchase. Interface tối thiểu đủ worker khác song song.

### NSB-011 — VietShare read-only adapter + kiểm thử chữ ký
Owner: supplier-backend. Dependency: NSB-010.
Acceptance: account/catalog/detail, ký raw bytes đúng query, deterministic signing tests với clock/nonce giả lập, pagination nếu docs hỗ trợ, timeout/429/backoff; không thực hiện POST orders live. Purchase capability chưa bật.

### NSB-012 — KhoMMO read-only adapter
Owner: supplier-backend. Dependency: NSB-010.
Acceptance: me/products/detail, Bearer redaction, pagination, wallet unit tách biệt, không trừ thêm 5%; parse theo schema đã có bằng chứng; schema chưa biết trả unsupported hoặc ghi gap, không pretend live test.

### NSB-013 — Roboticvn schema audit và read-only adapter
Owner: supplier-backend. Dependency: NSB-010.
Acceptance: thử tải OpenAPI qua public GET; lưu provenance/checksum nếu hợp lệ; so requestBody/required với bản Swagger; products/detail/variants/wallet, delivery chỉ theo quyền và dữ liệu test. Liệt kê cụ thể gap quote/order/topup, giữ các write disabled. Không dừng phần đọc chỉ vì purchase chưa rõ.

### NSB-014 — Admin catalog/suppliers và trạng thái môi trường
Owner: ui-antigravity. Dependency: NSB-010.
Acceptance: dùng OpenAPI/fixtures thật từ backend; tiếng Việt; catalog, supplier balance/currency, stale data, error/empty/loading; nhãn MOCK/READ-ONLY rõ; không dựng lợi nhuận thật từ seed; kiểm tra responsive, keyboard, reduced motion, không đổi backend/workflow.

### NSB-015 — Bot Telegram duyệt catalog và quote mô phỏng
Owner: backend-bot. Dependency: NSB-010.
Acceptance: /start, catalog, product detail, orders placeholder trung thực, support; aiogram transport mocked trong test; callback identity và price không tin từ client; chỉ bật bot test thủ công, không đòi token CI.

## Milestone M2 — Đơn hàng end-to-end mô phỏng

### NSB-020 — Order orchestration, dedupe và đối soát bằng fake supplier
Owner: backend. Dependency: NSB-010.
Acceptance: persisted intent/attempt, unique idempotency, duplicate click/payment callbacks, crash recovery, UNKNOWN/RECONCILING, không retry/failover khi outcome chưa rõ; delivery retry tách purchase; giá đổi/hết hàng/thiếu supplier balance. Mỗi capability supplier khác nhau không bị ép cùng semantics.

### NSB-021 — Mock checkout và kiểm thử xuyên bot–API–admin
Owner: backend-qa phối hợp ui. Dependencies: NSB-014, NSB-015, NSB-020.
Acceptance: mock-only payment profile có access control, success/failure/unknown/order history, browser E2E + bot transport test trên cùng fixture; tiền đúng currency, dashboard dữ liệu thật của database test; docs demo để Nyan thực hiện được. Không bank payment live.

## Milestone M3 — Staging và live readiness (chưa tự mở live)

### NSB-030 — Deploy staging mock bằng artifact đã kiểm thử
Owner: release-backend. Dependencies: NSB-021 + đích deploy/secret được owner cấp.
Acceptance: health/smoke, image digest đúng SHA, access control, deploy serial, log release, rollback image và chiến lược migration không phá dữ liệu. Chưa có host thì blocked; container publish không được gọi là staging deployment.

### NSB-031 — Live readiness, Stars test và supplier conformance
Owner: coordinator; Nyan phê duyệt. Dependencies: NSB-011/012/013/021, supplier gaps, điều kiện phân phối hàng, payment decision.
Acceptance: checklist chứng cứ nguồn, rate limit, price cap, safe retry/unknown, secret separation, backup/restore, Stars test environment, spend cap+allowlist+kill switch. Live credentials chỉ do owner cấp; acceptance của issue không tự cho phép mua thật.

## Milestone M4 — Unattended agent dispatch (backlog, không enable)

### NSB-040 — Owner-gated agent runner và giới hạn chi phí
Owner: coordinator. Dependencies: vài PR hoàn chỉnh đã chạy đúng loop + lựa chọn runtime/auth/budget của Nyan.
Acceptance: owner-authorized trigger, exact issue+base SHA, permission checks, no secrets in PR execution, bounded retries/concurrency, no automatic merge, dry-run first; kiểm thử GitHub event recursion/trigger. Không giả định label tự điều khiển desktop Antigravity; không chép Codex auth.json lên runner; API billing riêng phải được owner duyệt.

## Ready wave

Ban đầu chỉ NSB-001 đang làm. Sau merge: NSB-010. Sau NSB-010: coordinator chọn tối đa một supplier/backend issue và NSB-014 cho UI, còn lại xếp ready/backlog. NSB-015/020 có thể được lên lịch sau mà không đợi mọi adapter live hoàn thiện. Reviewer không tự claim implementation issue để sửa thay author.
