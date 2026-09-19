[**VVietShare Warehouse API**](https://token.vietshare.site/docs)[Tài liệu tích hợp v1](https://token.vietshare.site/docs)

**API đang hoạt động**[**Kiểm tra health ↗**](https://token.vietshare.site/v1/health)

**Warehouse integration · Version 1**

# Đấu kho tài khoản, giao hàng tự động.

Đồng bộ sản phẩm, giá bán và tồn kho; đặt đơn bằng ví Telegram; nhận tài khoản ngay trong phản hồi API. Giá nguồn được cập nhật động nhưng đối tác chỉ thấy giá bán của shop.

[**Tích hợp từ đầu**](https://token.vietshare.site/docs#bat-dau)[**Xem code mẫu**](https://token.vietshare.site/docs#code-mau)[**Lấy API ID trong bot ↗**](https://t.me/phptool_bot)

**PRODUCTION BASE URL**

`https://token.vietshare.site/v1`**Sao chép**

**HMAC**SHA-256 signature

**60/phút**Giới hạn mặc định

**VND**Số nguyên, không dấu chấm

**Mục lục**[Bắt đầu](https://token.vietshare.site/docs#bat-dau)[Xác thực HMAC](https://token.vietshare.site/docs#xac-thuc)[Endpoint](https://token.vietshare.site/docs#endpoint)[Sản phẩm & tồn](https://token.vietshare.site/docs#san-pham)[Đặt đơn](https://token.vietshare.site/docs#don-hang)[Code mẫu](https://token.vietshare.site/docs#code-mau)[Mã lỗi](https://token.vietshare.site/docs#ma-loi)[Bảo mật](https://token.vietshare.site/docs#bao-mat)

**01**

## Bắt đầu trong 4 bước

**1Mở bot Telegram**Vào @phptool_bot và bấm mục *API đấu kho*.

**2Lưu thông tin**Bot tự tạo một API ID cố định và API Secret chỉ hiện một lần.

**3Nạp số dư trong bot**Dùng mục Nạp tiền của bot như người dùng bình thường. API không tạo giao dịch nạp.

**4Ký và gọi API**Tạo timestamp, nonce mới, ký raw body rồi gọi endpoint cần dùng.

**Mỗi nick Telegram chỉ có một API client.** API ID không đổi. Khi đổi API Secret trong bot, secret cũ mất hiệu lực ngay.

**02**

## Xác thực HMAC-SHA256

Tất cả endpoint nghiệp vụ yêu cầu bốn header xác thực. Hai endpoint công khai là `GET /v1` và `GET /v1/health`.

### X-Shop-API-ID

API ID lấy trong bot, dạng `VS...`.

### X-Timestamp

Unix timestamp tính bằng giây. Độ lệch tối đa 300 giây.

### X-Nonce

Chuỗi ngẫu nhiên 12-128 ký tự và không được dùng lại trong cửa sổ xác thực.

### X-Signature

Chuỗi hex viết thường của HMAC-SHA256 bằng API Secret.

**Chuỗi canonical chính xác:**

`timestamp|nonce|METHOD|PATH_WITH_QUERY|sha256(raw_body)`

**PATH_WITH_QUERY phải gồm \`/v1\`.**
Ví dụ: `/v1/orders?limit=20`. Thứ tự query phải giống URL thực tế.

**Hash đúng raw body gửi đi.**
Body rỗng dùng SHA-256 của chuỗi byte rỗng. Không stringify JSON lại sau khi ký.

**Sao chép**

```
timestamp = "1784319000"
nonce    = "a06f8c44d0fe01a4c25028df"
method   = "POST"
path     = "/v1/orders"
body     = {"product_id":1,"quantity":2,"max_unit_price":25000}

body_hash = sha256(body)
canonical = timestamp|nonce|POST|/v1/orders|body_hash
signature = hmac_sha256(API_SECRET, canonical)
```

**Lưu ý khi retry:** nếu gửi lại một đơn, hãy giữ nguyên `Idempotency-Key` nhưng tạo timestamp, nonce và chữ ký mới.

**03**

## Danh sách endpoint

**GET****`/v1`**Thông tin phiên bản, xác thực và link tài liệu. Không cần ký.

**GET****`/v1/health`**Kiểm tra dịch vụ hoạt động. Không cần ký.

**GET****`/v1/account`**Số dư ví, trạng thái client và giới hạn request.

**GET****`/v1/products`**Danh sách sản phẩm, giá bán, mô tả và tồn kho.

**GET****`/v1/catalog`**Alias của `/products`.

**GET****`/v1/products/{product_id}`**Chi tiết một sản phẩm.

**GET****`/v1/stock/{product_id}`**Alias chi tiết sản phẩm, phù hợp tác vụ kiểm tra tồn.

**POST****`/v1/orders`**Đặt mua và nhận tài khoản. Bắt buộc Idempotency-Key.

**GET****`/v1/orders?limit=20`**Lấy 1-100 đơn API hoàn thành gần nhất.

**GET****`/v1/orders/{order_code}`**Lấy lại đầy đủ tài khoản của một đơn.

**Nạp tiền thực hiện trong bot Telegram.** API đấu kho không có endpoint tạo QR hoặc kiểm tra nạp tiền; mọi đơn chỉ sử dụng số dư ví hiện có.

**04**

## Sản phẩm, giá và tồn kho

`GET /v1/products` trả danh mục tài khoản đang bán. Giá là số nguyên VND và là **giá bán của VietShare đã gồm phần chênh**, không phải giá vốn nhà cung cấp. Với hàng đấu nguồn, giá này được cập nhật động theo giá vốn hiện tại cộng markup của shop. Nếu chủ API được gán giá seller, catalog tự trả giá riêng bằng giá vốn cộng mức lời seller.

**Sao chép**

```
{
  "count": 1,
  "products": [
    {
      "id": 7,
      "name": "Tài khoản mẫu",
      "description": "Thông tin bảo hành và định dạng tài khoản",
      "price": 25000,
      "flash_sale_id": null,
      "stock": 18,
      "allow_quantity": true,
      "max_quantity": 10
    }
  ]
}
```

| TrườngKiểuÝ nghĩa |              |                                                                                                           |
| ----------------- | ------------ | --------------------------------------------------------------------------------------------------------- |
| `id`              | integer      | ID dùng cho `POST /v1/orders`.                                                                            |
| `price`           | integer      | Giá bán hiện tại cho một tài khoản, đơn vị VND.                                                           |
| `flash_sale_id`   | integer/null | Nếu có Flash Sale, gửi lại ID này khi đặt đơn để khóa đúng chiến dịch và không bị chuyển sang giá thường. |
| `stock`           | integer      | Tồn khả dụng tại lúc truy vấn. Khi mua hệ thống kiểm tra lại lần cuối.                                    |
| `allow_quantity`  | boolean      | Có cho phép mua nhiều tài khoản trong một đơn hay không.                                                  |
| `max_quantity`    | integer      | Số lượng tối đa trong một request.                                                                        |

Ví API hỗ trợ riêng VND và USD. Mặc định đơn dùng VND; gửi `"currency":"USD"` để trừ ví USD (đơn vị ví USD là 0,1 USD). `max_unit_price` vẫn là giá VND để khóa giá nguồn.

**Khuyến nghị đồng bộ 10-30 giây/lần.** Không gọi catalog liên tục theo từng request của khách; hệ thống vẫn kiểm tra lại giá và tồn trong transaction mua.

**05**

## Đặt đơn và nhận tài khoản

Gửi JSON tới `POST /v1/orders`. Tiền được trừ từ ví Telegram của chủ API client trong cùng transaction giao hàng.

| TrườngBắt buộcKiểuQuy tắc |        |                |                                                                                                                  |
| ------------------------- | ------ | -------------- | ---------------------------------------------------------------------------------------------------------------- |
| `product_id`              | **Có** | integer        | ID sản phẩm từ catalog.                                                                                          |
| `quantity`                | Không  | integer        | Mặc định 1; tối đa theo sản phẩm và không quá 100.                                                               |
| `max_unit_price`          | **Có** | integer        | Giá tối đa VND chấp nhận cho mỗi tài khoản. Gửi `price` vừa đọc từ catalog.                                      |
| `currency`                | Không  | `VND` \| `USD` | Ví bị trừ. Mặc định `VND`; chọn `USD` để trừ số dư đô riêng.                                                     |
| `supplier_emails`         | Không  | array\<string> | Email theo từng tài khoản cho sản phẩm nhà cung cấp yêu cầu email (ví dụ Claude); số email phải bằng `quantity`. |
| `coupon_code`             | Không  | string         | Mã giảm giá dành riêng cho sản phẩm, tối đa 64 ký tự. Không cộng dồn khi tài khoản API đang được áp giá seller.  |
| `flash_sale_id`           | Không  | integer        | ID từ catalog. Nên gửi khi khác null để đơn thất bại an toàn nếu Flash Sale vừa hết hoặc giá vốn tăng.           |

**Header riêng bắt buộc:** `Idempotency-Key` dài 8-128 ký tự, chỉ gồm chữ, số và `._:-`.

**Sao chép**

```
POST /v1/orders
Idempotency-Key: reseller-order-20260718-00001
Content-Type: application/json

{"product_id":7,"quantity":2,"max_unit_price":25000,"currency":"USD","flash_sale_id":123}
```

**Sao chép**

```
{
  "success": true,
  "order": {
    "order_code": "B8D52E11A2C",
    "status": "completed",
    "channel": "api",
    "product": {"id": 7, "name": "Tài khoản mẫu"},
    "quantity": 2,
    "unit_price": null,
    "unit_prices": [22000, 23000],
    "price_breakdown": [
      {"quantity": 1, "unit_price": 22000, "subtotal": 22000},
      {"quantity": 1, "unit_price": 23000, "subtotal": 23000}
    ],
    "total_amount": 45000,
    "discount_amount": 5000,
    "accounts": [
      "email1@example.com|password1",
      "email2@example.com|password2"
    ],
    "idempotency_key": "reseller-order-20260718-00001",
    "created_at": "2026-07-18T03:15:22+00:00",
    "delivered_at": "2026-07-18T03:15:22+00:00"
  }
}
```

`unit_price` chỉ có giá trị khi mọi tài khoản trong đơn có cùng giá. Với đơn lấy từ nhiều lô hoặc nhiều nguồn, trường này là `null`; dùng `unit_prices`, `price_breakdown` và `total_amount` để đối soát chính xác.

**Retry an toàn.**
Cùng Idempotency-Key và cùng payload sẽ trả lại đơn cũ, không trừ tiền hoặc lấy hàng lần hai. Nếu nhận HTTP 202, request đang được đối soát; hãy tiếp tục retry đúng key đó.

**Không đổi payload.**
Dùng lại Idempotency-Key với payload khác sẽ nhận `409 IDEMPOTENCY_MISMATCH`.

**06**

## Code mẫu hoàn chỉnh

### Python

**Sao chép**

```
import hashlib
import hmac
import json
import secrets
import time

import requests

BASE_URL = "https://token.vietshare.site/v1"
API_ID = "VS_YOUR_API_ID"
API_SECRET = "vs_live_YOUR_SECRET"


def call_api(method, endpoint, payload=None, idempotency_key=None):
    body = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        if payload is not None
        else b""
    )
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(16)
    path_with_query = f"/v1{endpoint}"
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = "|".join(
        (timestamp, nonce, method.upper(), path_with_query, body_hash)
    )
    signature = hmac.new(
        API_SECRET.encode(), canonical.encode(), hashlib.sha256
    ).hexdigest()

    headers = {
        "X-Shop-API-ID": API_ID,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": signature,
    }
    if body:
        headers["Content-Type"] = "application/json"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key

    response = requests.request(
        method, f"{BASE_URL}{endpoint}", data=body, headers=headers, timeout=30
    )
    response.raise_for_status()
    return response.json()


catalog = call_api("GET", "/products")
product = catalog["products"][0]
payload = {
    "product_id": product["id"],
    "quantity": 1,
    "max_unit_price": product["price"],
}
if product.get("flash_sale_id"):
    payload["flash_sale_id"] = product["flash_sale_id"]
order = call_api(
    "POST",
    "/orders",
    payload,
    idempotency_key=f"my-shop-{secrets.token_hex(12)}",
)
print(order)
```

### Node.js 18+

**Sao chép**

```
import crypto from "node:crypto";

const BASE_URL = "https://token.vietshare.site/v1";
const API_ID = "VS_YOUR_API_ID";
const API_SECRET = "vs_live_YOUR_SECRET";

async function callApi(method, endpoint, payload = null, idempotencyKey = null) {
  const normalizedMethod = method.toUpperCase();
  const body = payload === null ? "" : JSON.stringify(payload);
  const timestamp = Math.floor(Date.now() / 1000).toString();
  const nonce = crypto.randomBytes(16).toString("hex");
  const bodyHash = crypto.createHash("sha256").update(body).digest("hex");
  const canonical = [timestamp, nonce, normalizedMethod, `/v1${endpoint}`, bodyHash].join("|");
  const signature = crypto
    .createHmac("sha256", API_SECRET)
    .update(canonical)
    .digest("hex");

  const headers = {
    "X-Shop-API-ID": API_ID,
    "X-Timestamp": timestamp,
    "X-Nonce": nonce,
    "X-Signature": signature,
  };
  if (body) headers["Content-Type"] = "application/json";
  if (idempotencyKey) headers["Idempotency-Key"] = idempotencyKey;

  const response = await fetch(`${BASE_URL}${endpoint}`, {
    method: normalizedMethod,
    headers,
    body: body || undefined,
  });
  const data = await response.json();
  if (!response.ok) throw new Error(JSON.stringify(data));
  return data;
}

const catalog = await callApi("GET", "/products");
const product = catalog.products[0];
const payload = {
  product_id: product.id,
  quantity: 1,
  max_unit_price: product.price,
};
if (product.flash_sale_id) payload.flash_sale_id = product.flash_sale_id;
const order = await callApi(
  "POST",
  "/orders",
  payload,
  `my-shop-${crypto.randomUUID()}`,
);
console.log(order);
```

**07**

## Mã lỗi cần xử lý

Lỗi nghiệp vụ có cấu trúc `{"detail":{"code":"...","message":"..."}}`.

| HTTPCode phổ biếnCách xử lý |                                                                                                  |                                                                                                                    |
| --------------------------- | ------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| 400                         | `INVALID_IDEMPOTENCY_KEY`<br>`MAX_UNIT_PRICE_REQUIRED`<br>`INVALID_COUPON`<br>`INVALID_QUANTITY` | Sửa dữ liệu request rồi gửi lại với key mới.                                                                       |
| 401                         | `AUTH_REQUIRED`<br>`INVALID_API_ID`<br>`INVALID_SIGNATURE`<br>`EXPIRED_REQUEST`                  | Kiểm tra credentials, đồng hồ máy chủ và canonical string.                                                         |
| 402                         | `INSUFFICIENT`                                                                                   | Nạp thêm số dư vào ví Telegram, sau đó tạo request mới với Idempotency-Key mới.                                    |
| 403                         | `API_CLIENT_BLOCKED`<br>`IP_NOT_ALLOWED`<br>`BLOCKED`                                            | Mở lại API trong bot hoặc liên hệ admin.                                                                           |
| 404                         | `PRODUCT_NOT_FOUND`<br>`ORDER_NOT_FOUND`                                                         | Đồng bộ lại catalog hoặc kiểm tra mã đơn thuộc đúng API client.                                                    |
| 409                         | `OUT_OF_STOCK`<br>`PRICE_CHANGED`                                                                | Đọc lại giá/tồn; nếu muốn đặt lại thì tạo payload và Idempotency-Key mới.                                          |
| 409                         | `REPLAYED_REQUEST`<br>`IDEMPOTENCY_MISMATCH`<br>`REQUEST_IN_PROGRESS`                            | Dùng nonce mới. Riêng `REQUEST_IN_PROGRESS` phải giữ nguyên payload và Idempotency-Key rồi chờ theo `Retry-After`. |
| 422                         | `Request validation`                                                                             | Kiểm tra đúng kiểu dữ liệu và tên trường; API từ chối trường JSON không được tài liệu định nghĩa.                  |
| 429                         | `RATE_LIMITED`                                                                                   | Giảm tần suất và retry có backoff.                                                                                 |
| 503                         | `SUPPLIER_UNAVAILABLE`<br>`AUTH_STORE_UNAVAILABLE`                                               | Retry sau; không tự coi đơn là thành công.                                                                         |

**08**

## Bảo mật và vận hành đúng

**Giữ Secret ở backend**Không nhúng API Secret vào web frontend, app mobile, ảnh chụp hoặc repository công khai.

**Đồng bộ thời gian**Bật NTP cho máy chủ tích hợp. Timestamp lệch quá 300 giây sẽ bị từ chối.

**Nonce mới mỗi request**Không dùng lại nonce, kể cả khi retry cùng một Idempotency-Key.

**Lưu đơn của bạn**Lưu Idempotency-Key và order_code để đối soát và lấy lại tài khoản khi mất kết nối.

**Bảo vệ dữ liệu giao hàng**Response chứa tài khoản thật. Không log plaintext lâu dài và không gửi sang dịch vụ phân tích bên thứ ba.

**Chỉ tin HTTP 200**Khi timeout hoặc nhận HTTP 202, đọc `Retry-After` rồi gọi lại bằng cùng Idempotency-Key, cùng payload nhưng nonce/chữ ký mới.

Hệ thống khóa ví theo user, khóa tồn local bằng PostgreSQL, tuần tự hóa luồng mua nguồn và dùng unique idempotency. Nhiều đối tác mua đồng thời không được nhận trùng cùng tài khoản.

VietShare Warehouse API · v1 · Tài liệu cập nhật theo API productionHỗ trợ: [**@phptool_bot**](https://t.me/phptool_bot)