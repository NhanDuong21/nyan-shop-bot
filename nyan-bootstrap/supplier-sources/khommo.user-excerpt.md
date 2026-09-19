# KhoMMO Partner API — nội dung nghiệp vụ người dùng dán

Nguồn do Nyan cung cấp: https://api.khommo.vn/docs/partner#top
Bản này giữ thông tin endpoint/request/lưu ý trong nội dung dán; bỏ menu ngôn ngữ, nút Copy và curl bị hỏng dấu nháy khi copy. Không phải OpenAPI schema đầy đủ; không có response mẫu mua thành công đầy đủ. Không tự suy đoán phần thiếu.

## Tổng quan

Partner API cho phép lấy số dư, đồng bộ sản phẩm, đặt hàng và tra cứu đơn hàng bằng Bearer Token.

Base URL: `https://api.khommo.vn/api/partner/v1`

## Xác thực

Gửi header Bearer Token trong mọi request. Không đưa token vào URL, mã nguồn frontend công khai hoặc log.
Lấy token tại Bot Telegram → Kết nối API.

`Authorization: Bearer YOUR_TOKEN`

## Endpoint

- `GET /me`: Trả về username, firstName và số dư wallet.credit/wallet.vnd.
- `GET /products`: Trả về id, sku, name, description, giá, paymentMode, deliveryType, stock và inStock.
- `GET /products/:id`: Trả về thông tin đầy đủ của sản phẩm, bao gồm stock và inStock.
- `POST /orders`: Tạo đơn bằng productId, quantity và paymentMode. Giá đã bao gồm chiết khấu Partner API 5%.
- `GET /orders/:orderNo`: Chỉ xem được đơn hàng thuộc tài khoản đang xác thực, kèm nội dung giao hàng nếu có.
- `GET /orders`: Trả về danh sách đơn mới nhất trước cùng pagination.

## Query parameters

- products: page mặc định 1; limit mặc định 20, tối đa 500; search tìm theo tên hoặc SKU.
- orders: page mặc định 1; limit mặc định 20, tối đa 50.

## Request body

- paymentMode nhận CREDIT hoặc VND và phải phù hợp với sản phẩm.
- quantity là số nguyên dương, mặc định 1 và không có giới hạn kinh doanh cố định; số lượng thực tế phụ thuộc tồn kho.

## Lưu ý

- priceCredit và priceVnd đã giảm 5%; không giảm lần nữa.
- inStock là trạng thái tại thời điểm kiểm tra; vẫn phải xử lý lỗi hết hàng khi đặt đơn.

## Mã lỗi thường gặp

| HTTP | Trả về |
|---|---|
| 401 | Thiếu hoặc sai Bearer Token. |
| 400 | Body, tham số, số dư, phương thức thanh toán hoặc tồn kho không hợp lệ. |
| 404 | Không tìm thấy sản phẩm hoặc đơn hàng thuộc tài khoản. |
| 502 | Nhà cung cấp tạm thời không phản hồi hoặc đặt đơn thất bại; quy trình hoàn tiền hiện tại vẫn áp dụng. |

## Những điều bản dán KHÔNG xác nhận

Phần này là ghi chú của người soạn, không phải lời supplier: chưa có schema response đầy đủ, idempotency guarantee, client reference lookup, giá trần lúc mua, định nghĩa transaction outcome 502 và vòng đời hoàn tiền. Không hiểu CREDIT thành postpaid và không retry mù khi timeout.
