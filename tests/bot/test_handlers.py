"""Offline handler coverage for every catalog and simulated-quote outcome."""

from datetime import UTC, datetime

import pytest
from aiogram.types import InlineKeyboardMarkup

from nyan_shop_bot.bot.callbacks import (
    decode_callback,
    encode_detail_callback,
    encode_quote_callback,
    encode_source_callback,
)
from nyan_shop_bot.bot.handlers import (
    MAX_BUTTON_TEXT_CHARS,
    MAX_MESSAGE_CHARS,
    SAFE_REFRESH_MESSAGE,
    build_dispatcher,
    build_router,
    callback_handler,
    catalog_handler,
    orders_handler,
    start_handler,
    support_handler,
)
from nyan_shop_bot.catalog.mock import (
    FakeCatalogReader,
    FakeCatalogScenario,
    fake_catalog_scenarios,
)
from nyan_shop_bot.catalog.models import (
    ApprovedMappingApproval,
    CapabilityStatus,
    CatalogDetailFound,
    CatalogDetailNotFound,
    CatalogDetailResponse,
    CatalogDetailUnsupported,
    CatalogError,
    CatalogErrorCode,
    CatalogProduct,
    CatalogResponse,
    CatalogState,
    CatalogVariant,
    Money,
    SupplierMapping,
    SupplierProductIdentity,
    SupplierVariantIdentity,
)
from nyan_shop_bot.catalog.registry import CatalogRegistry


class FakeMessage:
    def __init__(self) -> None:
        self.answers: list[tuple[str, dict[str, object]]] = []

    async def answer(self, text: str, **kwargs: object) -> object:
        self.answers.append((text, kwargs))
        return object()

    @property
    def text(self) -> str:
        return self.answers[-1][0]

    @property
    def markup(self) -> InlineKeyboardMarkup | None:
        value = self.answers[-1][1].get("reply_markup")
        return value if isinstance(value, InlineKeyboardMarkup) else None


class FakeCallback:
    def __init__(self, data: str | None, message: FakeMessage | None = None) -> None:
        self.data = data
        self.message = message
        self.answers = 0

    async def answer(self) -> object:
        self.answers += 1
        return object()


def _assert_seller_facing(*values: str) -> None:
    rendered = " ".join(values).casefold()
    assert "khommo" not in rendered
    assert "vietshare" not in rendered


class StubCatalogReader:
    capabilities = FakeCatalogReader.capabilities

    def __init__(
        self,
        *,
        catalog_response: CatalogResponse | None = None,
        details: dict[str, CatalogDetailResponse] | None = None,
        catalog_error: Exception | None = None,
    ) -> None:
        self.catalog_response = catalog_response
        self.details = details or {}
        self.catalog_error = catalog_error
        self.catalog_reads = 0
        self.product_reads: list[str] = []

    async def read_catalog(self) -> CatalogResponse:
        self.catalog_reads += 1
        if self.catalog_error is not None:
            raise self.catalog_error
        if self.catalog_response is None:
            raise AssertionError("test did not configure a catalog response")
        return self.catalog_response

    async def get_product(self, product_id: str) -> CatalogDetailResponse:
        self.product_reads.append(product_id)
        return self.details.get(
            product_id,
            CatalogDetailNotFound(state="not_found", product_id=product_id),
        )


def _mapping(suffix: str) -> SupplierMapping:
    return SupplierMapping(
        supplier_product=SupplierProductIdentity(
            supplier_id="secret-supplier-identity",
            supplier_product_id=f"secret-product-{suffix}",
        ),
        supplier_variant=SupplierVariantIdentity(
            supplier_id="secret-supplier-identity",
            supplier_variant_id=f"secret-variant-{suffix}",
        ),
        approval=ApprovedMappingApproval(
            status="approved",
            approved_by_admin_id="secret-approver",
            approved_at=datetime(2026, 9, 20, tzinfo=UTC),
        ),
    )


def _product(*, second_quantity: int = 4, long_text: bool = False) -> CatalogProduct:
    name = "Sản phẩm do máy chủ trả về"
    description = "Mô tả tổng hợp an toàn"
    if long_text:
        name = "Tên" * 2_000
        description = "Mô tả" * 2_000
    basic = CatalogVariant(
        id="basic",
        name="Gói cơ bản",
        mapping=_mapping("basic"),
        price=Money(amount_minor=111, currency="VND", unit="minor"),
        available_quantity=8,
    )
    premium = CatalogVariant(
        id="premium",
        name="Gói máy chủ cao cấp",
        mapping=_mapping("premium"),
        price=Money(amount_minor=777, currency="JPY", unit="minor"),
        available_quantity=second_quantity,
    )
    return CatalogProduct(
        id="server-product",
        name=name,
        description=description,
        price=basic.price,
        available_quantity=basic.available_quantity,
        variants=(basic, premium),
    )


async def test_start_is_honest_and_contains_the_static_menu() -> None:
    message = FakeMessage()

    await start_handler(message)

    assert "LOCAL / CHỈ ĐỌC" in message.text
    assert "vô hiệu hóa" in message.text
    assert all(command in message.text for command in ("/catalog", "/orders", "/support"))
    assert "chọn nguồn" not in message.text


@pytest.mark.parametrize(
    ("scenario", "expected", "has_keyboard"),
    [
        (FakeCatalogScenario.FRESH, "Dữ liệu mới", True),
        (FakeCatalogScenario.STALE, "dữ liệu bộ nhớ đệm đã cũ", True),
        (FakeCatalogScenario.EMPTY, "Danh mục hiện trống", False),
        (FakeCatalogScenario.ERROR, "Không thể tải danh mục chỉ đọc", False),
    ],
)
async def test_catalog_renders_all_envelope_states_honestly(
    scenario: FakeCatalogScenario,
    expected: str,
    has_keyboard: bool,
) -> None:
    message = FakeMessage()
    reader = FakeCatalogReader(scenario)

    await catalog_handler(message, reader)

    assert expected in message.text
    assert (message.markup is not None) is has_keyboard
    assert "fake-supplier" not in message.text
    assert "supplier-learning-pass" not in message.text
    if scenario is FakeCatalogScenario.STALE:
        assert "làm mới" in message.text


async def test_live_partial_catalog_uses_seller_brand_and_exact_omission_count() -> None:
    fresh = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    live_product = _product().model_copy(update={"supplier": "khommo", "mode": "khommo-readonly"})
    response = CatalogResponse(
        supplier="khommo",
        mode="khommo-readonly",
        state=CatalogState.FRESH,
        freshness=fresh.freshness,
        items=(live_product,),
        error=None,
        partial=True,
        omitted_count=3,
    )
    message = FakeMessage()

    await catalog_handler(message, StubCatalogReader(catalog_response=response))

    assert "DANH MỤC — NYAN SHOP / CHỈ ĐỌC" in message.text
    assert "CATALOG PARTIAL" in message.text
    assert "3 sản phẩm bị loại" in message.text
    assert "không cấp quyền mua" in message.text
    assert "Sản phẩm do máy chủ trả về" not in message.text
    assert "amount_minor" not in message.text
    assert "currency=" not in message.text
    assert message.markup is not None
    assert message.markup.inline_keyboard[0][0].text == "Sản phẩm do máy chủ trả về · 111đ · Còn 8"
    _assert_seller_facing(message.text, message.markup.inline_keyboard[0][0].text)
    for forbidden in ("secret-supplier-identity", "secret-product", "secret-variant"):
        assert forbidden not in message.text


async def test_catalog_uses_compact_vnd_stock_buttons_without_repeating_products() -> None:
    message = FakeMessage()

    await catalog_handler(message, FakeCatalogReader(FakeCatalogScenario.FRESH))

    assert message.markup is not None
    button_texts = [row[0].text for row in message.markup.inline_keyboard]
    button_styles = [row[0].style for row in message.markup.inline_keyboard]
    assert button_texts == [
        "Synthetic learning pass · 49.000đ · Còn 12",
        "Synthetic design seat · 25.000đ · Còn 5",
        "Synthetic toolkit · 79.000đ · Hết hàng",
    ]
    assert button_styles == ["success", "success", "danger"]
    assert all(
        product_name not in message.text
        for product_name in (
            "Synthetic learning pass",
            "Synthetic design seat",
            "Synthetic toolkit",
        )
    )
    assert "amount_minor" not in message.text
    assert "available_quantity" not in message.text


async def test_legacy_source_selection_redirects_to_seller_aggregate() -> None:
    fresh = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    khommo_product = _product().model_copy(update={"supplier": "khommo", "mode": "khommo-readonly"})
    vietshare_product = _product().model_copy(
        update={"supplier": "vietshare", "mode": "vietshare-readonly"}
    )
    khommo_response = CatalogResponse(
        supplier="khommo",
        mode="khommo-readonly",
        state=CatalogState.FRESH,
        freshness=fresh.freshness,
        items=(khommo_product,),
        error=None,
    )
    vietshare_response = CatalogResponse(
        supplier="vietshare",
        mode="vietshare-readonly",
        state=CatalogState.FRESH,
        freshness=fresh.freshness,
        items=(vietshare_product,),
        error=None,
    )
    khommo = StubCatalogReader(
        catalog_response=khommo_response,
        details={
            khommo_product.id: CatalogDetailFound(state="found", item=khommo_product),
        },
    )
    vietshare = StubCatalogReader(
        catalog_response=vietshare_response,
        details={
            vietshare_product.id: CatalogDetailFound(state="found", item=vietshare_product),
        },
    )
    catalogs = CatalogRegistry({"khommo": khommo, "vietshare": vietshare})
    catalog_message = FakeMessage()

    await callback_handler(
        FakeCallback(encode_source_callback("khommo"), catalog_message),
        catalogs,
    )

    assert "DANH MỤC — NYAN SHOP / CHỈ ĐỌC" in catalog_message.text
    assert khommo.catalog_reads == 1
    assert vietshare.catalog_reads == 1
    assert catalog_message.markup is not None
    detail_data = catalog_message.markup.inline_keyboard[0][0].callback_data
    decoded = decode_callback(detail_data)
    assert decoded.source == "khommo"
    assert decoded.product_id == khommo_product.id
    _assert_seller_facing(
        catalog_message.text,
        *(row[0].text for row in catalog_message.markup.inline_keyboard),
    )

    detail_message = FakeMessage()
    await callback_handler(FakeCallback(detail_data, detail_message), catalogs)

    assert "CHI TIẾT SẢN PHẨM — NYAN SHOP / CHỈ ĐỌC" in detail_message.text
    assert khommo.product_reads == [khommo_product.id]
    assert vietshare.product_reads == []
    _assert_seller_facing(detail_message.text)
    assert detail_message.markup is not None
    assert decode_callback(detail_message.markup.inline_keyboard[0][0].callback_data).source == (
        "khommo"
    )


async def test_aggregate_catalog_keeps_duplicate_ids_bound_to_their_original_source() -> None:
    fresh = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    khommo_product = _product().model_copy(update={"supplier": "khommo", "mode": "khommo-readonly"})
    vietshare_product = _product().model_copy(
        update={"supplier": "vietshare", "mode": "vietshare-readonly"}
    )
    khommo = StubCatalogReader(
        catalog_response=CatalogResponse(
            supplier="khommo",
            mode="khommo-readonly",
            state=CatalogState.FRESH,
            freshness=fresh.freshness,
            items=(khommo_product,),
            error=None,
        ),
        details={khommo_product.id: CatalogDetailFound(state="found", item=khommo_product)},
    )
    vietshare = StubCatalogReader(
        catalog_response=CatalogResponse(
            supplier="vietshare",
            mode="vietshare-readonly",
            state=CatalogState.FRESH,
            freshness=fresh.freshness,
            items=(vietshare_product,),
            error=None,
        ),
        details={vietshare_product.id: CatalogDetailFound(state="found", item=vietshare_product)},
    )
    catalogs = CatalogRegistry({"khommo": khommo, "vietshare": vietshare})
    aggregate_message = FakeMessage()

    await callback_handler(
        FakeCallback(encode_source_callback("all"), aggregate_message),
        catalogs,
    )

    assert "DANH MỤC — NYAN SHOP / CHỈ ĐỌC" in aggregate_message.text
    assert "chưa được tự động hợp nhất" in aggregate_message.text
    assert aggregate_message.markup is not None
    buttons = [row[0] for row in aggregate_message.markup.inline_keyboard]
    assert [decode_callback(button.callback_data).source for button in buttons] == [
        "khommo",
        "vietshare",
    ]
    _assert_seller_facing(aggregate_message.text, *(button.text for button in buttons))

    detail_message = FakeMessage()
    await callback_handler(FakeCallback(buttons[1].callback_data, detail_message), catalogs)

    assert "CHI TIẾT SẢN PHẨM — NYAN SHOP / CHỈ ĐỌC" in detail_message.text
    assert khommo.product_reads == []
    assert vietshare.product_reads == [vietshare_product.id]
    _assert_seller_facing(detail_message.text)

    assert detail_message.markup is not None
    quote_message = FakeMessage()
    quote_data = detail_message.markup.inline_keyboard[0][0].callback_data
    await callback_handler(FakeCallback(quote_data, quote_message), catalogs)

    assert "THÔNG TIN GIÁ — NYAN SHOP / CHỈ ĐỌC" in quote_message.text
    _assert_seller_facing(quote_message.text)


async def test_aggregate_catalog_reports_a_failed_source_without_leaking_its_exception() -> None:
    fresh = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    product = _product().model_copy(update={"supplier": "khommo", "mode": "khommo-readonly"})
    khommo = StubCatalogReader(
        catalog_response=CatalogResponse(
            supplier="khommo",
            mode="khommo-readonly",
            state=CatalogState.FRESH,
            freshness=fresh.freshness,
            items=(product,),
            error=None,
        )
    )
    vietshare = StubCatalogReader(catalog_error=RuntimeError("token=NEVER-PRINT raw supplier body"))
    message = FakeMessage()

    await callback_handler(
        FakeCallback(encode_source_callback("all"), message),
        CatalogRegistry({"khommo": khommo, "vietshare": vietshare}),
    )

    assert "danh mục đang hiển thị một phần" in message.text
    assert "Một phần dữ liệu tạm thời không khả dụng" in message.text
    assert message.markup is not None
    _assert_seller_facing(message.text)
    assert "NEVER-PRINT" not in message.text
    assert "raw supplier body" not in message.text


async def test_aggregate_catalog_identifies_fresh_partial_source_and_omissions() -> None:
    fresh = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    khommo_product = _product().model_copy(update={"supplier": "khommo", "mode": "khommo-readonly"})
    vietshare_product = _product().model_copy(
        update={"supplier": "vietshare", "mode": "vietshare-readonly"}
    )
    khommo = StubCatalogReader(
        catalog_response=CatalogResponse(
            supplier="khommo",
            mode="khommo-readonly",
            state=CatalogState.FRESH,
            freshness=fresh.freshness,
            items=(khommo_product,),
            error=None,
            partial=True,
            omitted_count=3,
        )
    )
    vietshare = StubCatalogReader(
        catalog_response=CatalogResponse(
            supplier="vietshare",
            mode="vietshare-readonly",
            state=CatalogState.FRESH,
            freshness=fresh.freshness,
            items=(vietshare_product,),
            error=None,
        )
    )
    message = FakeMessage()

    await callback_handler(
        FakeCallback(encode_source_callback("all"), message),
        CatalogRegistry({"khommo": khommo, "vietshare": vietshare}),
    )

    assert "3 sản phẩm bị loại vì thiếu dữ liệu bắt buộc" in message.text
    _assert_seller_facing(message.text)


async def test_aggregate_catalog_preserves_stale_and_partial_evidence_together() -> None:
    fresh = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    stale = fake_catalog_scenarios()[FakeCatalogScenario.STALE]
    khommo_product = _product().model_copy(update={"supplier": "khommo", "mode": "khommo-readonly"})
    vietshare_product = _product().model_copy(
        update={"supplier": "vietshare", "mode": "vietshare-readonly"}
    )
    khommo = StubCatalogReader(
        catalog_response=CatalogResponse(
            supplier="khommo",
            mode="khommo-readonly",
            state=CatalogState.STALE,
            freshness=stale.freshness,
            items=(khommo_product,),
            error=stale.error,
            partial=True,
            omitted_count=2,
        )
    )
    vietshare = StubCatalogReader(
        catalog_response=CatalogResponse(
            supplier="vietshare",
            mode="vietshare-readonly",
            state=CatalogState.FRESH,
            freshness=fresh.freshness,
            items=(vietshare_product,),
            error=None,
        )
    )
    message = FakeMessage()

    await callback_handler(
        FakeCallback(encode_source_callback("all"), message),
        CatalogRegistry({"khommo": khommo, "vietshare": vietshare}),
    )

    assert "2 sản phẩm bị loại vì thiếu dữ liệu bắt buộc" in message.text
    assert "Một phần danh mục đang sử dụng dữ liệu cache đã cũ" in message.text
    _assert_seller_facing(message.text)


async def test_aggregate_catalog_error_keeps_empty_and_failed_source_evidence() -> None:
    fresh = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    khommo = StubCatalogReader(
        catalog_response=CatalogResponse(
            supplier="khommo",
            mode="khommo-readonly",
            state=CatalogState.EMPTY,
            freshness=fresh.freshness,
            items=(),
            error=None,
        )
    )
    vietshare = StubCatalogReader(catalog_error=RuntimeError("token=NEVER-PRINT"))
    message = FakeMessage()

    await callback_handler(
        FakeCallback(encode_source_callback("all"), message),
        CatalogRegistry({"khommo": khommo, "vietshare": vietshare}),
    )

    assert "Không thể tải danh mục sản phẩm dùng được" in message.text
    assert "Một phần dữ liệu tạm thời không khả dụng" in message.text
    assert message.markup is None
    assert "NEVER-PRINT" not in message.text
    _assert_seller_facing(message.text)


async def test_legacy_callback_in_multi_mode_fails_closed_without_guessing_source() -> None:
    response = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    khommo = StubCatalogReader(catalog_response=response)
    vietshare = StubCatalogReader(catalog_response=response)
    catalogs = CatalogRegistry({"khommo": khommo, "vietshare": vietshare})
    message = FakeMessage()

    await callback_handler(
        FakeCallback(encode_detail_callback("learning-pass"), message),
        catalogs,
    )

    assert message.text == SAFE_REFRESH_MESSAGE
    assert khommo.product_reads == []
    assert vietshare.product_reads == []


async def test_legacy_or_wrong_source_callback_cannot_cross_single_live_modes() -> None:
    response = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    vietshare = StubCatalogReader(catalog_response=response)
    catalogs = CatalogRegistry({"vietshare": vietshare})

    legacy_message = FakeMessage()
    await callback_handler(
        FakeCallback(encode_detail_callback("learning-pass"), legacy_message),
        catalogs,
    )
    wrong_source_message = FakeMessage()
    await callback_handler(
        FakeCallback(
            encode_detail_callback("learning-pass", "khommo"),
            wrong_source_message,
        ),
        catalogs,
    )

    assert legacy_message.text == SAFE_REFRESH_MESSAGE
    assert wrong_source_message.text == SAFE_REFRESH_MESSAGE
    assert vietshare.product_reads == []


async def test_catalog_error_never_echoes_upstream_details() -> None:
    secret_error = CatalogError(
        code=CatalogErrorCode.SOURCE_UNAVAILABLE,
        message="upstream body: token=NEVER-PRINT traceback supplier-name",
        retryable=True,
    )
    response = CatalogResponse(
        mode="mock",
        state=CatalogState.ERROR,
        freshness=None,
        items=(),
        error=secret_error,
    )
    message = FakeMessage()

    await catalog_handler(message, StubCatalogReader(catalog_response=response))

    assert "Không thể tải danh mục chỉ đọc" in message.text
    for forbidden in ("upstream body", "NEVER-PRINT", "traceback", "supplier-name"):
        assert forbidden not in message.text


async def test_stale_catalog_never_echoes_refresh_error_details() -> None:
    stale = fake_catalog_scenarios()[FakeCatalogScenario.STALE]
    response = CatalogResponse(
        mode="mock",
        state=CatalogState.STALE,
        freshness=stale.freshness,
        items=stale.items,
        error=CatalogError(
            code=CatalogErrorCode.SOURCE_UNAVAILABLE,
            message="private refresh body and secret supplier identity",
            retryable=True,
        ),
    )
    message = FakeMessage()

    await catalog_handler(message, StubCatalogReader(catalog_response=response))

    assert "đã cũ" in message.text
    assert "làm mới" in message.text
    assert "private refresh body" not in message.text
    assert "secret supplier identity" not in message.text


async def test_catalog_reader_exception_is_rendered_as_a_safe_error() -> None:
    message = FakeMessage()
    reader = StubCatalogReader(catalog_error=RuntimeError("token and upstream body"))

    await catalog_handler(message, reader)

    assert "Không thể tải danh mục chỉ đọc" in message.text
    assert "token and upstream body" not in message.text


async def test_found_detail_is_re_resolved_and_never_exposes_mapping() -> None:
    product = _product()
    reader = StubCatalogReader(
        details={product.id: CatalogDetailFound(state="found", item=product)}
    )
    message = FakeMessage()
    callback = FakeCallback(encode_detail_callback(product.id), message)

    await callback_handler(callback, reader)

    assert callback.answers == 1
    assert reader.product_reads == [product.id]
    assert "CHI TIẾT SẢN PHẨM" in message.text
    assert "Sản phẩm do máy chủ trả về" in message.text
    assert "amount_minor=777; currency=JPY; unit=minor" in message.text
    assert message.markup is not None
    for forbidden in ("secret-supplier-identity", "secret-product", "secret-variant"):
        assert forbidden not in message.text


async def test_not_found_detail_is_honest_without_guessing() -> None:
    reader = StubCatalogReader()
    message = FakeMessage()
    callback = FakeCallback(encode_detail_callback("unknown-product"), message)

    await callback_handler(callback, reader)

    assert callback.answers == 1
    assert reader.product_reads == ["unknown-product"]
    assert "Không tìm thấy sản phẩm" in message.text
    assert "không có dữ liệu nào được suy đoán" in message.text


async def test_unsupported_detail_is_honest_and_hides_internal_error() -> None:
    response = CatalogDetailUnsupported(
        state="unsupported",
        product_id="unsupported-product",
        error=CatalogError(
            code=CatalogErrorCode.UNSUPPORTED,
            message="private schema details supplier=secret",
            retryable=False,
        ),
    )
    reader = StubCatalogReader(details={response.product_id: response})
    message = FakeMessage()
    callback = FakeCallback(encode_detail_callback(response.product_id), message)

    await callback_handler(callback, reader)

    assert "không được hỗ trợ" in message.text
    assert "không suy đoán dữ liệu" in message.text
    assert "private schema details" not in message.text
    assert "supplier=secret" not in message.text


async def test_forged_product_callback_fails_closed_after_server_lookup() -> None:
    reader = StubCatalogReader()
    message = FakeMessage()
    callback = FakeCallback(encode_quote_callback("forged-product", "forged-variant"), message)

    await callback_handler(callback, reader)

    assert callback.answers == 1
    assert reader.product_reads == ["forged-product"]
    assert message.text == SAFE_REFRESH_MESSAGE


async def test_stale_or_forged_variant_fails_closed_after_server_lookup() -> None:
    product = _product()
    reader = StubCatalogReader(
        details={product.id: CatalogDetailFound(state="found", item=product)}
    )
    message = FakeMessage()
    callback = FakeCallback(encode_quote_callback(product.id, "removed-variant"), message)

    await callback_handler(callback, reader)

    assert callback.answers == 1
    assert reader.product_reads == [product.id]
    assert message.text == SAFE_REFRESH_MESSAGE


async def test_malformed_client_price_currency_and_title_are_rejected_before_lookup() -> None:
    product = _product()
    reader = StubCatalogReader(
        details={product.id: CatalogDetailFound(state="found", item=product)}
    )
    message = FakeMessage()
    valid = encode_quote_callback(product.id, "premium")
    callback = FakeCallback(f"{valid}:price=1:currency=USD:title=FORGED", message)

    await callback_handler(callback, reader)

    assert callback.answers == 1
    assert reader.product_reads == []
    assert message.text == SAFE_REFRESH_MESSAGE
    assert "price=1" not in message.text
    assert "USD" not in message.text
    assert "FORGED" not in message.text


async def test_quote_uses_only_the_current_server_side_variant() -> None:
    product = _product(second_quantity=4)
    reader = StubCatalogReader(
        details={product.id: CatalogDetailFound(state="found", item=product)}
    )
    message = FakeMessage()
    callback = FakeCallback(encode_quote_callback(product.id, "premium"), message)

    await callback_handler(callback, reader)

    assert reader.product_reads == [product.id]
    assert "BÁO GIÁ MÔ PHỎNG — MOCK / CHỈ ĐỌC" in message.text
    assert "Sản phẩm do máy chủ trả về" in message.text
    assert "Gói máy chủ cao cấp" in message.text
    assert "amount_minor=777; currency=JPY; unit=minor" in message.text
    assert "available_quantity=4" in message.text
    assert "amount_minor=111" not in message.text
    assert "không bảo đảm sẽ còn hàng" in message.text
    assert "Không tạo hay giữ chỗ" in message.text


async def test_quote_reports_current_out_of_stock_state_without_a_promise() -> None:
    product = _product(second_quantity=0)
    reader = StubCatalogReader(
        details={product.id: CatalogDetailFound(state="found", item=product)}
    )
    message = FakeMessage()
    callback = FakeCallback(encode_quote_callback(product.id, "premium"), message)

    await callback_handler(callback, reader)

    assert "hết hàng" in message.text
    assert "available_quantity=0" in message.text
    assert "không phải lời hứa" in message.text


@pytest.mark.parametrize("payload", [None, "", "9:d:item", "1:x:item", "1:d:a:b"])
async def test_malformed_callback_is_answered_and_never_reaches_catalog(
    payload: str | None,
) -> None:
    reader = StubCatalogReader()
    message = FakeMessage()
    callback = FakeCallback(payload, message)

    await callback_handler(callback, reader)

    assert callback.answers == 1
    assert reader.product_reads == []
    assert message.text == SAFE_REFRESH_MESSAGE


async def test_callback_without_a_message_still_clears_loading_state() -> None:
    callback = FakeCallback(encode_detail_callback("product"), None)

    await callback_handler(callback, StubCatalogReader())

    assert callback.answers == 1


async def test_orders_and_support_are_static_and_do_not_invent_contacts() -> None:
    orders = FakeMessage()
    support = FakeMessage()

    await orders_handler(orders)
    await support_handler(support)

    assert "Checkout và đơn hàng thật hiện không khả dụng" in orders.text
    assert "không tạo, lưu, gửi hoặc thanh toán" in orders.text
    assert "TĨNH / NGOẠI TUYẾN" in support.text
    assert "Chưa có thông tin liên hệ" in support.text
    assert "@" not in support.text


def test_router_and_dispatcher_construct_without_token_or_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    reader = StubCatalogReader(catalog_response=fake_catalog_scenarios()[FakeCatalogScenario.FRESH])

    router = build_router(reader)
    dispatcher = build_dispatcher(reader)

    assert router.name == "foundation"
    assert dispatcher.sub_routers
    assert dispatcher.sub_routers[0].name == "foundation"


def test_catalog_capabilities_remain_write_disabled() -> None:
    capabilities = FakeCatalogReader.capabilities

    assert capabilities.catalog_read.status is CapabilityStatus.ENABLED
    assert capabilities.catalog_detail.status is CapabilityStatus.ENABLED
    assert all(
        capability.status is CapabilityStatus.DISABLED
        for capability in (
            capabilities.purchase,
            capabilities.payment,
            capabilities.top_up,
            capabilities.refund,
            capabilities.delivery,
        )
    )


async def test_messages_buttons_and_callbacks_remain_bounded() -> None:
    product = _product(long_text=True)
    response = fake_catalog_scenarios()[FakeCatalogScenario.FRESH]
    oversized_catalog = CatalogResponse(
        mode="mock",
        state=CatalogState.FRESH,
        freshness=response.freshness,
        items=(product,),
        error=None,
    )
    catalog_message = FakeMessage()

    await catalog_handler(
        catalog_message,
        StubCatalogReader(catalog_response=oversized_catalog),
    )

    assert len(catalog_message.text) <= MAX_MESSAGE_CHARS
    assert catalog_message.markup is not None
    detail_button = catalog_message.markup.inline_keyboard[0][0]
    assert len(detail_button.text) <= MAX_BUTTON_TEXT_CHARS
    assert detail_button.callback_data is not None
    assert len(detail_button.callback_data.encode("ascii")) <= 64

    detail_message = FakeMessage()
    callback = FakeCallback(detail_button.callback_data, detail_message)
    reader = StubCatalogReader(
        details={product.id: CatalogDetailFound(state="found", item=product)}
    )
    await callback_handler(callback, reader)

    assert len(detail_message.text) <= MAX_MESSAGE_CHARS
    assert detail_message.markup is not None
    assert all(
        len(button.text) <= MAX_BUTTON_TEXT_CHARS
        and button.callback_data is not None
        and len(button.callback_data.encode("ascii")) <= 64
        for row in detail_message.markup.inline_keyboard
        for button in row
    )
