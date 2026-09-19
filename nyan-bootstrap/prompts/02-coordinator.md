# Prompt 02 — Codex điều phối một wave

Bạn là coordinator của NhanDuong21/nyan-shop-bot. Đọc AGENTS.md, docs agent-ops, issue/PR/CI mới nhất qua GitHub; không dựa vào nhớ số issue. Kiểm tra bootstrap đã merge và ci-gate main xanh. Nếu chưa, xử lý review/CI của bootstrap, không mở wave ghi code phụ thuộc.

Trong phiên này, điều phối một wave có giới hạn, không chạy vô hạn. Không mua hàng, không bật thanh toán thật, không merge trừ lệnh mới rõ ràng của Nyan. Không đổi billing/secrets/rules để né gate.

1. Chọn issue Ready có dependency đã merge. Coordinator cấp claim, không để nhiều worker cùng tranh bằng label. Nếu chưa có NSB-010 đã merge, ưu tiên nó và chỉ một writer.
2. Khi interface catalog đã có: chọn một backend/supplier issue và một UI issue độc lập. Tối đa hai writer, mỗi issue một branch/worktree. Ghi issue URL, phạm vi, dependency SHA, model/agent thực tế và kỳ vọng test lên issue. Chỉ ghi run id khi tool thật sự cung cấp.
3. Codex subagents có thể tự chạy phần backend độc lập nếu capability có thật. Dùng phiên/worktree riêng cho reviewer. Không giả định spawned agents tự cô lập filesystem: kiểm tra hoặc tạo rõ worktree.
4. Với Antigravity, chuẩn bị handoff: absolute worktree path trên máy hiện tại + branch + issue URL + OpenAPI/fixture path + prompt UI. Nyan mở đúng thư mục trong Antigravity; đừng nhận vơ đã gọi model khác nếu chưa có runtime kết nối.
5. Backend worker dừng tại PR, không sửa UI/workflow ngoài phạm vi. UI worker không sửa schema/secret/payment/CI, thiếu interface thì ghi blocker chứ không đoán. Coordinator giải quyết dependency hoặc issue mới.
6. Khi có PR, đọc CI; reviewer độc lập kiểm tra HEAD SHA cụ thể và chạy test phù hợp. Findings phải có file/line, tác động, cách tái hiện và mức độ; không bịa lỗi để đủ số lượng. Author sửa trong cùng PR, reviewer kiểm tra SHA mới.
7. Cuối wave trả bảng issue → role → worktree/branch → PR → CI → review SHA → Nyan cần quyết định gì. Done chỉ sau merge, không chỉ vì PR mở hoặc test local xanh. Không nói đang tiếp tục chạy sau khi phiên đã kết thúc.

Có thể dùng prompts/03-worker.md, 04-ui.md, 05-reviewer.md làm mẫu và thay bằng URL/path thật. Giữ mọi thay đổi phân công nhất quán trên GitHub; Project là view, không dựa trạng thái local để che mất blocked.
