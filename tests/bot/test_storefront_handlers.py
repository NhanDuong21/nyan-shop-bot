"""Offline Telegram coverage for the customer-safe curated storefront."""

from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup

from nyan_shop_bot.bot.callbacks import encode_detail_callback, encode_quote_callback
from nyan_shop_bot.bot.handlers import (
    SAFE_CATALOG_ERROR_MESSAGE,
    SAFE_REFRESH_MESSAGE,
    storefront_callback_handler,
    storefront_catalog_handler,
)
from nyan_shop_bot.catalog.models import Money
from nyan_shop_bot.catalog.storefront.models import (
    StorefrontAvailability,
    StorefrontCatalogResponse,
    StorefrontCatalogState,
    StorefrontDetailFound,
    StorefrontDetailNotFound,
    StorefrontDetailResponse,
    StorefrontProduct,
)


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


class StubStorefront:
    def __init__(
        self,
        response: StorefrontCatalogResponse,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.catalog_reads = 0
        self.detail_reads: list[str] = []

    async def read_storefront(self) -> StorefrontCatalogResponse:
        self.catalog_reads += 1
        if self.error is not None:
            raise self.error
        return self.response

    async def get_storefront_product(self, product_id: str) -> StorefrontDetailResponse:
        self.detail_reads.append(product_id)
        if self.error is not None:
            raise self.error
        product = next((item for item in self.response.items if item.id == product_id), None)
        if product is None:
            return StorefrontDetailNotFound(state="not_found", product_id=product_id)
        return StorefrontDetailFound(state="found", item=product)


def product(
    product_id: str,
    availability: StorefrontAvailability,
    *,
    name: str,
) -> StorefrontProduct:
    return StorefrontProduct(
        id=product_id,
        name=name,
        description="Mô tả do Nyan biên tập.",
        category="Tiện ích",
        price=Money(amount_minor=30_000, currency="VND", unit="minor"),
        availability=availability,
    )


def response() -> StorefrontCatalogResponse:
    return StorefrontCatalogResponse(
        revision=3,
        state=StorefrontCatalogState.PARTIAL,
        items=(
            product("available", StorefrontAvailability.IN_STOCK, name="Gói còn hàng"),
            product("sold-out", StorefrontAvailability.OUT_OF_STOCK, name="Gói hết hàng"),
            product("unknown", StorefrontAvailability.UNKNOWN, name="Gói đang cập nhật"),
            product("x" * 30, StorefrontAvailability.IN_STOCK, name="ID callback quá dài"),
        ),
        partial=True,
        unresolved_offer_count=1,
        source_evidence_partial=True,
    )


async def test_catalog_renders_nyan_prices_stock_styles_and_no_supplier_evidence() -> None:
    message = FakeMessage()
    storefront = StubStorefront(response())

    await storefront_catalog_handler(message, storefront)

    assert storefront.catalog_reads == 1
    assert "DANH MỤC — NYAN SHOP / CHỈ ĐỌC" in message.text
    assert "một phần trạng thái hàng" in message.text
    assert "1 liên kết hàng" in message.text
    markup = message.markup
    assert markup is not None
    buttons = [row[0] for row in markup.inline_keyboard]
    assert [button.style for button in buttons] == ["success", "danger", "primary"]
    rendered = " ".join([message.text, *(button.text for button in buttons)]).lower()
    assert "30.000đ" in rendered
    assert "còn hàng" in rendered
    assert "hết hàng" in rendered
    assert "đang cập nhật" in rendered
    for forbidden in ("khommo", "vietshare", "supplier", "available_quantity"):
        assert forbidden not in rendered
    assert len(buttons) == 3  # overlong callback identity is omitted, never truncated or guessed


async def test_detail_callback_uses_same_projection_without_quote_or_source_action() -> None:
    storefront = StubStorefront(response())
    message = FakeMessage()
    detail = FakeCallback(encode_detail_callback("available"), message)

    await storefront_callback_handler(detail, storefront)

    assert detail.answers == 1
    assert storefront.detail_reads == ["available"]
    assert "CHI TIẾT SẢN PHẨM — NYAN SHOP / CHỈ ĐỌC" in message.text
    assert "Giá bán: 30.000đ" in message.text
    assert "Tình trạng: Còn hàng" in message.text
    assert message.markup is None

    stale_quote = FakeCallback(encode_quote_callback("available", "variant"), message)
    await storefront_callback_handler(stale_quote, storefront)
    assert message.text == SAFE_REFRESH_MESSAGE
    assert storefront.detail_reads == ["available"]


async def test_missing_stale_and_failure_paths_are_safe_and_redacted() -> None:
    storefront = StubStorefront(response())
    missing_message = FakeMessage()
    await storefront_callback_handler(
        FakeCallback(encode_detail_callback("missing"), missing_message),
        storefront,
    )
    assert "không còn trong danh mục Nyan" in missing_message.text

    failing = StubStorefront(
        response(),
        error=RuntimeError("token=NEVER-PRINT raw supplier body"),
    )
    catalog_message = FakeMessage()
    await storefront_catalog_handler(catalog_message, failing)
    assert catalog_message.text == SAFE_CATALOG_ERROR_MESSAGE
    assert "NEVER-PRINT" not in catalog_message.text

    detail_message = FakeMessage()
    await storefront_callback_handler(
        FakeCallback(encode_detail_callback("available"), detail_message),
        failing,
    )
    assert detail_message.text == SAFE_REFRESH_MESSAGE
    assert "supplier body" not in detail_message.text
