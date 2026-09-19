## Roboticvn Customer API

```
 2.2.0 
```

```
OAS 3.0
```

[/api/v2/docs/openapi.json](https://api.roboticvn.com/api/v2/docs/openapi.json)

Minimal, allowlisted customer API for Roboticvn.

Send **`x-api-key`** on every data request. Responses support Vietnamese and English through **`?locale=vi-VN|en-US`** or **`Accept-Language`**.

List endpoints return only fields needed to select a resource. Sensitive delivery credentials are isolated under the delivery endpoint, and provider-internal payment data is never returned.

**Servers**

**/ - Same originhttps\://api.roboticvn.com - Production**

**Authorizesvg**

### [Account](https://api.roboticvn.com/api/v2/docs#/Account)svg

**GET**

[**/api/v2/me**](https://api.roboticvn.com/api/v2/docs#/Account/getMeV2)

Get the current customer

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |            |               |   |
| ------------------- | ---------- | ------------- | - |
| locale              | **string** | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

**ExecuteClear**

#### Responses

#### Curl

```bash
curl -X 'GET' \
  'https://api.roboticvn.com/api/v2/me?locale=vi-VN' \
  -H 'accept: application/json'
```

#### Request URL

```
https://api.roboticvn.com/api/v2/me?locale=vi-VN
```

#### Server response

| **Code** | **Details** |
| :------- | :---------- |
| 401      |             |

Error: response status is 401

##### Response body

**Download**

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Missing x-api-key header. Provide a valid API key to access this endpoint."
  }
}
```

##### Response headers

```
 alt-svc: h3=":443"; ma=86400  cf-cache-status: DYNAMIC  cf-ray: a3d68aeefc1f3883-SIN  content-length: 120  content-type: application/json; charset=utf-8  date: Sat,19 Sep 2026 06:30:36 GMT  etag: W/"78-dqknHzHyZsV5SEuaS3lG00UawFE"  nel: {"report_to":"cf-nel","success_fraction":0.0,"max_age":604800}  priority: u=1,i  report-to: {"group":"cf-nel","max_age":604800,"endpoints":[{"url":"https://a.nel.cloudflare.com/report/v4?s=MH61pbXHsU2Un5TlmTp1I%2B7iytXDM%2FXgxfUgft7JcGGIEXZZ0xvsoibWS2aZZTktZKg3JRMDYlzjvwItyUQleHqp%2BsWNObiO7HyM4sK1WsJqUElo1LwpIhsR0G8M2MPVCKnnHK86Kxfd2pF45eZz6g%3D%3D"}]}  server: cloudflare  server-timing: cfExtPri  x-powered-by: Express 
```

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": {
    "first_name": "string",
    "last_name": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

### [Products](https://api.roboticvn.com/api/v2/docs#/Products)svg

**GET**

[**/api/v2/products**](https://api.roboticvn.com/api/v2/docs#/Products/listProductsV2)

List product names and IDs

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |             |               |   |
| ------------------- | ----------- | ------------- | - |
| limit               | **integer** | ***(query)*** |   |
| offset              | **integer** | ***(query)*** |   |
| search              | **string**  | ***(query)*** |   |
| category_id         | **string**  | ***(query)*** |   |
| locale              | **string**  | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

**ExecuteClear**

#### Responses

#### Curl

```bash
curl -X 'GET' \
  'https://api.roboticvn.com/api/v2/products?limit=20&offset=0&locale=vi-VN' \
  -H 'accept: application/json'
```

#### Request URL

```
https://api.roboticvn.com/api/v2/products?limit=20&offset=0&locale=vi-VN
```

#### Server response

| **Code** | **Details** |
| :------- | :---------- |
| 401      |             |

Error: response status is 401

##### Response body

**Download**

```json
{
  "error": {
    "code": "unauthorized",
    "message": "Missing x-api-key header. Provide a valid API key to access this endpoint."
  }
}
```

##### Response headers

```
 alt-svc: h3=":443"; ma=86400  cf-cache-status: DYNAMIC  cf-ray: a3d68b196c2e3883-SIN  content-length: 120  content-type: application/json; charset=utf-8  date: Sat,19 Sep 2026 06:30:43 GMT  etag: W/"78-dqknHzHyZsV5SEuaS3lG00UawFE"  nel: {"report_to":"cf-nel","success_fraction":0.0,"max_age":604800}  priority: u=1,i  report-to: {"group":"cf-nel","max_age":604800,"endpoints":[{"url":"https://a.nel.cloudflare.com/report/v4?s=BByirOr2lPdqsG7xyObl%2BUT3xtJ3TVSN%2BECVBaU2b4YA78IiEJm5AHBbsI4ZtsAr0P9eIcvhL1AQvHWjYVWWk6j49NZ%2FuymkRFB440jZKtoq8zR8ZNxL9StK%2BYez5Nyo83PG%2BYisuISlseep%2FeI4YQ%3D%3D"}]}  server: cloudflare  server-timing: cfExtPri  x-powered-by: Express 
```

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": [
    {
      "id": "string",
      "title": "string"
    }
  ],
  "meta": {
    "count": 0,
    "limit": 0,
    "offset": 0
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

**GET**

[**/api/v2/products/{id}**](https://api.roboticvn.com/api/v2/docs#/Products/getProductV2)

Get purchasable product detail

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |            |               |   |
| ------------------- | ---------- | ------------- | - |
| **id \***           | **string** | ***(path)***  |   |
| locale              | **string** | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

Please correct the following validation errors and try again.

- For 'id': Required field is not provided.

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": {
    "id": "string",
    "title": "string",
    "description": "string",
    "thumbnail": "string",
    "in_stock": true,
    "variants": [
      {
        "id": "string",
        "title": "string",
        "description": "string",
        "delivery_instructions": "string",
        "reseller_notes": "string",
        "prices": {
          "additionalProp1": 0,
          "additionalProp2": 0,
          "additionalProp3": 0
        },
        "in_stock": true,
        "available_quantity": 0
      }
    ]
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

**POST**

[**/api/v2/products/{id}/quote**](https://api.roboticvn.com/api/v2/docs#/Products/quoteProductV2)

Quote a quantity with realtime stock

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |            |               |   |
| ------------------- | ---------- | ------------- | - |
| **id \***           | **string** | ***(path)***  |   |
| locale              | **string** | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

#### Request body

**application/json**

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": {
    "product_id": "string",
    "variant_id": "string",
    "quantity": 0,
    "currency_code": "vnd",
    "unit_price": 0,
    "total": 0,
    "available_quantity": 0,
    "can_purchase": true,
    "realtime": true
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

### [Orders](https://api.roboticvn.com/api/v2/docs#/Orders)svg

**GET**

[**/api/v2/orders**](https://api.roboticvn.com/api/v2/docs#/Orders/listOrdersV2)

List orders

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |             |               |   |
| ------------------- | ----------- | ------------- | - |
| limit               | **integer** | ***(query)*** |   |
| offset              | **integer** | ***(query)*** |   |
| locale              | **string**  | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": [
    {
      "id": "string",
      "display_id": 0,
      "status": "string",
      "payment_status": "string",
      "total": 0,
      "currency_code": "string",
      "created_at": "2026-09-19T06:31:00.537Z"
    }
  ],
  "meta": {
    "count": 0,
    "limit": 0,
    "offset": 0
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

**POST**

[**/api/v2/orders**](https://api.roboticvn.com/api/v2/docs#/Orders/createOrderV2)

Create an order paid from wallet balance

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |            |               |   |
| ------------------- | ---------- | ------------- | - |
| locale              | **string** | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

#### Request body

**application/json**

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 201      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": {
    "checkout_id": "string",
    "order_id": "string",
    "order_display_id": 0,
    "status": "string",
    "payment": {
      "method": "bank_transfer",
      "amount": 0,
      "currency_code": "string",
      "bank_code": "string",
      "account_number": "string",
      "account_name": "string",
      "reference": "string",
      "qr_url": "string",
      "expires_at": "string"
    }
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

**GET**

[**/api/v2/orders/{id}**](https://api.roboticvn.com/api/v2/docs#/Orders/getOrderV2)

Get order detail without credentials

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |            |               |   |
| ------------------- | ---------- | ------------- | - |
| **id \***           | **string** | ***(path)***  |   |
| locale              | **string** | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": {
    "id": "string",
    "display_id": 0,
    "status": "string",
    "payment_status": "string",
    "total": 0,
    "currency_code": "string",
    "created_at": "2026-09-19T06:31:00.552Z",
    "items": [
      {
        "id": "string",
        "title": "string",
        "quantity": 0,
        "unit_price": 0,
        "variant_id": "string",
        "variant_title": "string",
        "product_id": "string",
        "product_title": "string"
      }
    ]
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

**GET**

[**/api/v2/orders/{id}/payment-status**](https://api.roboticvn.com/api/v2/docs#/Orders/getOrderPaymentStatusV2)

Get order payment status

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |            |               |   |
| ------------------- | ---------- | ------------- | - |
| **id \***           | **string** | ***(path)***  |   |
| locale              | **string** | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": {
    "order_id": "string",
    "status": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

**GET**

[**/api/v2/orders/{id}/delivery**](https://api.roboticvn.com/api/v2/docs#/Orders/getOrderDeliveryV2)

Get delivered digital credentials

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |            |               |   |
| ------------------- | ---------- | ------------- | - |
| **id \***           | **string** | ***(path)***  |   |
| locale              | **string** | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "deliveredAccount": [
    {
      "item_id": "string",
      "title": "string",
      "product_title": "string",
      "variant_title": "string",
      "quantity": 0,
      "display_title": "string",
      "account": "string",
      "password": "string",
      "additional_info": "string"
    }
  ],
  "delivered_accounts": [
    {
      "item_id": "string",
      "title": "string",
      "product_title": "string",
      "variant_title": "string",
      "quantity": 0,
      "display_title": "string",
      "account": "string",
      "password": "string",
      "additional_info": "string"
    }
  ]
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

### [Wallet](https://api.roboticvn.com/api/v2/docs#/Wallet)svg

**GET**

[**/api/v2/wallet/balance**](https://api.roboticvn.com/api/v2/docs#/Wallet/getWalletBalanceV2)

Get totals by currency

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |            |               |   |
| ------------------- | ---------- | ------------- | - |
| locale              | **string** | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": {
    "vnd": 500000,
    "usd": 25
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

**POST**

[**/api/v2/wallet/topup**](https://api.roboticvn.com/api/v2/docs#/Wallet/topupWalletV2)

Create a wallet top-up checkout

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |            |               |   |
| ------------------- | ---------- | ------------- | - |
| locale              | **string** | ***(query)*** |   |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

#### Request body

**application/json**

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 201      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": {
    "checkout_id": "string",
    "order_id": "string",
    "order_display_id": 0,
    "status": "string",
    "payment": {
      "method": "bank_transfer",
      "amount": 0,
      "currency_code": "string",
      "bank_code": "string",
      "account_number": "string",
      "account_name": "string",
      "reference": "string",
      "qr_url": "string",
      "expires_at": "string"
    }
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

**GET**

[**/api/v2/wallet/transactions**](https://api.roboticvn.com/api/v2/docs#/Wallet/listWalletTransactionsV2)

List sanitized wallet transactions

svg

svgsvg

#### Parameters

**Cancel**

| **NameDescription** |             |               |              |
| ------------------- | ----------- | ------------- | ------------ |
| currency_code       | **string**  | ***(query)*** | **--vndusd** |
| limit               | **integer** | ***(query)*** |              |
| offset              | **integer** | ***(query)*** |              |
| locale              | **string**  | ***(query)*** |              |

Response language. The Accept-Language header is used when omitted.

**--vi-VNen-US**

**Execute**

#### Responses

| **Code** | **Description** | **Links** |
| :------- | :-------------- | :-------- |
| 200      |                 |           |

Success

Media type

**application/json**

Controls `Accept` header.

- **Example Value**
- Schema

```json
{
  "data": [
    {
      "type": "credit",
      "reason": "topup",
      "description": "string",
      "amount": 0,
      "currency_code": "string",
      "created_at": "2026-09-19T06:31:00.573Z"
    }
  ],
  "meta": {
    "count": 0,
    "limit": 0,
    "offset": 0
  }
}
```

| *No links* |   |
| ---------- | - |
| 400        |   |

Invalid request

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 401        |   |

Missing or invalid API key

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 404        |   |

Resource not found

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 429        |   |

Rate limit exceeded

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |   |
| ---------- | - |
| 500        |   |

Unexpected server error

Media type

**application/json**

- **Example Value**
- Schema

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

| *No links* |
| ---------- |

#### Schemas