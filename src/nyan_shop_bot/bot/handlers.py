"""Offline-testable aiogram catalog handlers with no transport startup."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Final, Protocol

from aiogram import Dispatcher, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from nyan_shop_bot.bot.callbacks import (
    CallbackAction,
    CallbackCodecError,
    decode_callback,
    encode_detail_callback,
    encode_quote_callback,
)
from nyan_shop_bot.catalog.mock import FakeCatalogReader
from nyan_shop_bot.catalog.models import (
    AggregateCatalogResponse,
    AggregateCatalogState,
    CatalogDetailFound,
    CatalogDetailNotFound,
    CatalogDetailResponse,
    CatalogDetailUnsupported,
    CatalogProduct,
    CatalogResponse,
    CatalogState,
    CatalogVariant,
    LiveCatalogSupplier,
    Money,
)
from nyan_shop_bot.catalog.ports import CatalogReader
from nyan_shop_bot.catalog.registry import (
    CatalogRegistry,
    CatalogSourceSelectionRequired,
    CatalogSourceUnavailable,
)
from nyan_shop_bot.catalog.storefront.models import (
    StorefrontAvailability,
    StorefrontCatalogResponse,
    StorefrontCatalogState,
    StorefrontDetailFound,
    StorefrontDetailNotFound,
    StorefrontProduct,
)
from nyan_shop_bot.catalog.storefront.ports import StorefrontCatalogReader

MAX_MESSAGE_CHARS: Final = 3_500
MAX_BUTTON_TEXT_CHARS: Final = 64
MAX_CATALOG_ITEMS: Final = 20
MAX_DETAIL_VARIANTS: Final = 20
SELLER_CATALOG_LABEL: Final = "NYAN SHOP / CHỈ ĐỌC"
_UPSTREAM_BRAND_PATTERN: Final = re.compile(
    r"(?:kho[\s._-]*mmo|viet[\s._-]*share)",
    flags=re.IGNORECASE,
)

SAFE_REFRESH_MESSAGE: Final = (
    "Nút này không còn hợp lệ hoặc dữ liệu đã thay đổi. "
    "Vui lòng dùng /catalog để làm mới; không có thao tác nào được tạo."
)
SAFE_CATALOG_ERROR_MESSAGE: Final = (
    "Không thể tải danh mục chỉ đọc lúc này. Vui lòng thử lại bằng /catalog sau. "
    "Không có đơn hàng hoặc giao dịch nào được tạo."
)


class AnswerableMessage(Protocol):
    """Narrow message boundary that is easy to exercise with an offline fake."""

    async def answer(self, text: str, **kwargs: object) -> object: ...


class AnswerableCallbackQuery(Protocol):
    """Only the callback surface used by these handlers."""

    data: str | None
    message: AnswerableMessage | None

    async def answer(self) -> object: ...


def _catalog_or_default(catalog: CatalogReader | None) -> CatalogReader:
    """Use deterministic synthetic data only when no reader is injected."""
    return catalog if catalog is not None else FakeCatalogReader()


def _catalog_access_or_default(
    catalog: CatalogReader | CatalogRegistry | None,
) -> CatalogReader | CatalogRegistry:
    if isinstance(catalog, CatalogRegistry):
        return catalog
    return _catalog_or_default(catalog)


def _normalized_display(value: str) -> str:
    visible_parts: list[str] = []
    for character in value:
        category = unicodedata.category(character)
        if category == "Cf":
            continue
        visible_parts.append(" " if category.startswith("C") else character)
    visible = "".join(visible_parts)
    return " ".join(visible.split())


def _bounded_display(value: str, limit: int, *, fallback: str) -> str:
    visible = _normalized_display(value)
    if not visible:
        return fallback
    if len(visible) <= limit:
        return visible
    return f"{visible[: limit - 1].rstrip()}…"


def _seller_display(value: str, limit: int, *, fallback: str) -> str:
    """White-label known upstream brands only in customer-visible copy."""
    branded = _UPSTREAM_BRAND_PATTERN.sub("Nyan Shop", _normalized_display(value))
    return _bounded_display(branded, limit, fallback=fallback)


def _bounded_message(lines: Sequence[str]) -> str:
    text = "\n".join(lines)
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return f"{text[: MAX_MESSAGE_CHARS - 1].rstrip()}…"


def _format_money(money: Money) -> str:
    """Render the stored integer and its contract metadata without conversion."""
    return f"amount_minor={money.amount_minor}; currency={money.currency}; unit={money.unit}"


def _format_catalog_button_price(money: Money) -> str:
    """Render a compact price without converting or hiding its source currency."""
    if money.currency == "VND":
        return f"{money.amount_minor:,}".replace(",", ".") + "đ"
    return f"{money.amount_minor:,} {money.currency}"


def _live_source(supplier: str) -> LiveCatalogSupplier | None:
    if supplier == "khommo":
        return "khommo"
    if supplier == "vietshare":
        return "vietshare"
    return None


def _button_text(prefix: str, value: str) -> str:
    return _bounded_display(f"{prefix}{value}", MAX_BUTTON_TEXT_CHARS, fallback=prefix.rstrip())


def _catalog_button_text(product: CatalogProduct) -> str:
    price = _format_catalog_button_price(product.price)
    availability = (
        "Hết hàng" if product.available_quantity == 0 else f"Còn {product.available_quantity}"
    )
    suffix = f" · {price} · {availability}"
    if len(suffix) >= MAX_BUTTON_TEXT_CHARS:
        return _bounded_display(
            f"{price} · {availability}",
            MAX_BUTTON_TEXT_CHARS,
            fallback="Xem chi tiết",
        )
    name = _seller_display(
        product.name,
        MAX_BUTTON_TEXT_CHARS - len(suffix),
        fallback="Sản phẩm",
    )
    return f"{name}{suffix}"


def _keyboard(rows: list[list[InlineKeyboardButton]]) -> InlineKeyboardMarkup | None:
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


async def _send(
    message: AnswerableMessage,
    lines: Sequence[str],
    *,
    keyboard: InlineKeyboardMarkup | None = None,
) -> None:
    text = _bounded_message(lines)
    if keyboard is None:
        await message.answer(text)
    else:
        await message.answer(text, reply_markup=keyboard)


async def start_handler(message: AnswerableMessage) -> None:
    """Explain the local read-only state without assuming the configured source."""
    await _send(
        message,
        (
            "Nyan Shop Bot — LOCAL / CHỈ ĐỌC.",
            "Bot chỉ cho phép xem danh mục; thanh toán và mua hàng thật hiện bị vô hiệu hóa.",
            "Menu: /catalog xem danh mục · /orders xem trạng thái đơn · /support xem trợ giúp.",
        ),
    )


def _catalog_lines(response: CatalogResponse) -> list[str]:
    if response.state is CatalogState.EMPTY:
        return [
            f"DANH MỤC — {SELLER_CATALOG_LABEL}",
            "Danh mục hiện trống; không có sản phẩm nào để hiển thị.",
            "Không có đơn hàng hoặc giao dịch nào được tạo.",
        ]
    if response.state is CatalogState.ERROR:
        return [SAFE_CATALOG_ERROR_MESSAGE]

    lines = [f"DANH MỤC — {SELLER_CATALOG_LABEL}"]
    if response.state is CatalogState.STALE:
        lines.append(
            "⚠ CẢNH BÁO: đang hiển thị dữ liệu bộ nhớ đệm đã cũ; lần làm mới gần nhất thất bại."
        )
    else:
        lines.append("Dữ liệu mới · Chọn một sản phẩm để xem chi tiết.")

    if response.partial:
        lines.append(
            "⚠ CATALOG PARTIAL: "
            f"{response.omitted_count} sản phẩm bị loại vì nguồn dữ liệu thiếu mô tả hoặc tồn kho; "
            "bot không suy đoán giá trị."
        )

    visible_items = response.items[:MAX_CATALOG_ITEMS]
    if len(response.items) > len(visible_items):
        lines.append(f"Chỉ hiển thị {len(visible_items)} sản phẩm đầu tiên trong menu này.")
    if response.supplier == "mock":
        lines.append("Giá và tồn kho chỉ là thông tin MOCK hiện tại, không phải cam kết bán hàng.")
    else:
        lines.append(
            "Giá và tồn kho là snapshot chỉ đọc tại thời điểm hiện tại; "
            "không phải cam kết bán hàng và không cấp quyền mua."
        )
    return lines


def _catalog_keyboard(
    response: CatalogResponse,
    *,
    source: LiveCatalogSupplier | None = None,
) -> InlineKeyboardMarkup | None:
    if response.state not in (CatalogState.FRESH, CatalogState.STALE):
        return None

    rows: list[list[InlineKeyboardButton]] = []
    for product in response.items[:MAX_CATALOG_ITEMS]:
        try:
            callback_data = encode_detail_callback(product.id, source)
        except CallbackCodecError:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=_catalog_button_text(product),
                    callback_data=callback_data,
                    style="danger" if product.available_quantity == 0 else "success",
                )
            ]
        )
    return _keyboard(rows)


async def catalog_handler(
    message: AnswerableMessage,
    catalog: CatalogReader | None = None,
    *,
    source: LiveCatalogSupplier | None = None,
) -> None:
    """Read and render every normalized catalog envelope state safely."""
    reader = _catalog_or_default(catalog)
    try:
        response = await reader.read_catalog()
    except Exception:
        await _send(message, (SAFE_CATALOG_ERROR_MESSAGE,))
        return

    await _send(
        message,
        _catalog_lines(response),
        keyboard=_catalog_keyboard(response, source=source),
    )


def _storefront_button_text(product: StorefrontProduct) -> str:
    price = _format_catalog_button_price(product.price)
    availability = {
        StorefrontAvailability.IN_STOCK: "Còn hàng",
        StorefrontAvailability.OUT_OF_STOCK: "Hết hàng",
        StorefrontAvailability.UNKNOWN: "Đang cập nhật",
    }[product.availability]
    suffix = f" · {price} · {availability}"
    if len(suffix) >= MAX_BUTTON_TEXT_CHARS:
        return _bounded_display(
            f"{price} · {availability}",
            MAX_BUTTON_TEXT_CHARS,
            fallback="Xem chi tiết",
        )
    name = _seller_display(
        product.name,
        MAX_BUTTON_TEXT_CHARS - len(suffix),
        fallback="Sản phẩm",
    )
    return f"{name}{suffix}"


def _storefront_catalog_lines(response: StorefrontCatalogResponse) -> list[str]:
    lines = ["DANH MỤC — NYAN SHOP / CHỈ ĐỌC"]
    if response.state is StorefrontCatalogState.EMPTY:
        lines.extend(
            (
                "Danh mục chưa có sản phẩm Nyan nào được đăng.",
                "Không có đơn hàng hoặc giao dịch nào được tạo.",
            )
        )
        return lines
    if response.state is StorefrontCatalogState.PARTIAL:
        lines.append("⚠ CẢNH BÁO: một phần trạng thái hàng đang được cập nhật.")
        if response.unresolved_offer_count:
            lines.append(
                f"{response.unresolved_offer_count} liên kết hàng chưa có bằng chứng hiện tại; "
                "bot không suy đoán còn hàng."
            )
    else:
        lines.append("Chọn một sản phẩm để xem thông tin chi tiết.")
    visible_items = response.items[:MAX_CATALOG_ITEMS]
    if len(response.items) > len(visible_items):
        lines.append(f"Chỉ hiển thị {len(visible_items)} sản phẩm đầu tiên trong menu này.")
    lines.append(
        "Giá là giá bán Nyan bằng VND; trạng thái hàng chỉ là dữ liệu đọc hiện tại và "
        "không cấp quyền mua."
    )
    return lines


def _storefront_catalog_keyboard(
    response: StorefrontCatalogResponse,
) -> InlineKeyboardMarkup | None:
    if response.state is StorefrontCatalogState.EMPTY:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for product in response.items[:MAX_CATALOG_ITEMS]:
        try:
            callback_data = encode_detail_callback(product.id)
        except CallbackCodecError:
            continue
        style = {
            StorefrontAvailability.IN_STOCK: "success",
            StorefrontAvailability.OUT_OF_STOCK: "danger",
            StorefrontAvailability.UNKNOWN: "primary",
        }[product.availability]
        rows.append(
            [
                InlineKeyboardButton(
                    text=_storefront_button_text(product),
                    callback_data=callback_data,
                    style=style,
                )
            ]
        )
    return _keyboard(rows)


async def storefront_catalog_handler(
    message: AnswerableMessage,
    storefront: StorefrontCatalogReader,
) -> None:
    """Render only the persisted customer-safe Nyan projection."""
    try:
        response = await storefront.read_storefront()
    except Exception:
        await _send(message, (SAFE_CATALOG_ERROR_MESSAGE,))
        return
    await _send(
        message,
        _storefront_catalog_lines(response),
        keyboard=_storefront_catalog_keyboard(response),
    )


def _aggregate_catalog_lines(response: AggregateCatalogResponse) -> list[str]:
    title = f"DANH MỤC — {SELLER_CATALOG_LABEL}"
    lines = [title]
    if response.state is AggregateCatalogState.ERROR:
        lines.append("Không thể tải danh mục sản phẩm dùng được lúc này.")
    elif response.state is AggregateCatalogState.EMPTY:
        lines.append("Danh mục hiện trống; không có sản phẩm nào để hiển thị.")
    elif response.state is AggregateCatalogState.PARTIAL:
        lines.append("⚠ CẢNH BÁO: danh mục đang hiển thị một phần dữ liệu hiện có.")
    else:
        lines.append("Dữ liệu mới · Chọn một sản phẩm để xem chi tiết.")

    if response.omitted_count:
        lines.append(
            f"{response.omitted_count} sản phẩm bị loại vì thiếu dữ liệu bắt buộc; "
            "bot không suy đoán giá trị."
        )
    if any(report.state is CatalogState.STALE for report in response.sources):
        lines.append("Một phần danh mục đang sử dụng dữ liệu cache đã cũ.")
    if any(report.state is CatalogState.ERROR for report in response.sources):
        lines.append(
            "Một phần dữ liệu tạm thời không khả dụng; sản phẩm bị thiếu không được suy đoán."
        )
    if response.state in {AggregateCatalogState.ERROR, AggregateCatalogState.EMPTY}:
        lines.append("Không có đơn hàng hoặc giao dịch nào được tạo.")
        return lines

    visible_items = response.items[:MAX_CATALOG_ITEMS]
    if len(response.items) > len(visible_items):
        lines.append(f"Chỉ hiển thị {len(visible_items)} sản phẩm đầu tiên trong menu này.")
    lines.extend(
        (
            "Các mục có tên hoặc giá giống nhau chưa được tự động hợp nhất.",
            "Giá và tồn kho là snapshot chỉ đọc tại thời điểm hiện tại; không cấp quyền mua.",
        )
    )
    return lines


def _aggregate_catalog_keyboard(
    response: AggregateCatalogResponse,
) -> InlineKeyboardMarkup | None:
    if response.state not in {AggregateCatalogState.COMPLETE, AggregateCatalogState.PARTIAL}:
        return None
    rows: list[list[InlineKeyboardButton]] = []
    for product in response.items[:MAX_CATALOG_ITEMS]:
        source = _live_source(product.supplier)
        if source is None:
            continue
        try:
            callback_data = encode_detail_callback(product.id, source)
        except CallbackCodecError:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=_catalog_button_text(product),
                    callback_data=callback_data,
                    style="danger" if product.available_quantity == 0 else "success",
                )
            ]
        )
    return _keyboard(rows)


async def aggregate_catalog_handler(
    message: AnswerableMessage,
    catalogs: CatalogRegistry,
) -> None:
    """Render a seller-facing combined view while preserving source-qualified routing."""
    try:
        response = await catalogs.read_aggregate()
    except Exception:
        await _send(message, (SAFE_CATALOG_ERROR_MESSAGE,))
        return
    await _send(
        message,
        _aggregate_catalog_lines(response),
        keyboard=_aggregate_catalog_keyboard(response),
    )


async def orders_handler(message: AnswerableMessage) -> None:
    """State that the read-only trial has no checkout or real orders."""
    await _send(
        message,
        (
            "ĐƠN HÀNG — KHÔNG KHẢ DỤNG / CHỈ ĐỌC",
            "Checkout và đơn hàng thật hiện không khả dụng.",
            "Bot không tạo, lưu, gửi hoặc thanh toán bất kỳ đơn hàng nào.",
        ),
    )


async def support_handler(message: AnswerableMessage) -> None:
    """Provide static offline help without inventing contact details."""
    await _send(
        message,
        (
            "HỖ TRỢ TĨNH / NGOẠI TUYẾN",
            "Dùng /catalog để tải lại danh mục, /orders để xem giới hạn đơn hàng, "
            "hoặc /start để xem menu.",
            "Chưa có thông tin liên hệ hỗ trợ nào được cấu hình trong bot này.",
        ),
    )


def _detail_lines(product: CatalogProduct) -> list[str]:
    lines = [
        f"CHI TIẾT SẢN PHẨM — {SELLER_CATALOG_LABEL}",
        f"Tên: {_seller_display(product.name, 120, fallback='Sản phẩm không có tên hiển thị')}",
        f"Mô tả: {_seller_display(product.description, 500, fallback='Không có mô tả hiển thị')}",
        "Các biến thể hiện tại:",
    ]
    visible_variants = product.variants[:MAX_DETAIL_VARIANTS]
    for variant in visible_variants:
        name = _seller_display(variant.name, 96, fallback="Biến thể không có tên hiển thị")
        lines.append(
            f"• {name} — {_format_money(variant.price)}; "
            f"available_quantity={variant.available_quantity}"
        )
    if len(product.variants) > len(visible_variants):
        lines.append(
            f"Chỉ hiển thị {len(visible_variants)} biến thể đầu tiên để giữ tin nhắn an toàn."
        )
    lines.append("Thông tin này không tạo đơn, không giữ chỗ và không cam kết còn hàng.")
    return lines


def _storefront_detail_lines(product: StorefrontProduct) -> list[str]:
    availability = {
        StorefrontAvailability.IN_STOCK: "Còn hàng",
        StorefrontAvailability.OUT_OF_STOCK: "Hết hàng",
        StorefrontAvailability.UNKNOWN: "Đang cập nhật",
    }[product.availability]
    lines = [
        "CHI TIẾT SẢN PHẨM — NYAN SHOP / CHỈ ĐỌC",
        f"Tên: {_seller_display(product.name, 120, fallback='Sản phẩm không có tên hiển thị')}",
        f"Mô tả: {_seller_display(product.description, 500, fallback='Không có mô tả hiển thị')}",
    ]
    if product.category is not None:
        lines.append(
            f"Danh mục: {_seller_display(product.category, 96, fallback='Chưa phân loại')}"
        )
    lines.extend(
        (
            f"Giá bán: {_format_catalog_button_price(product.price)}",
            f"Tình trạng: {availability}",
            "Thông tin này không tạo đơn, không giữ chỗ và không cam kết còn hàng.",
        )
    )
    return lines


def _detail_keyboard(
    product: CatalogProduct,
    *,
    source: LiveCatalogSupplier | None = None,
) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    for variant in product.variants[:MAX_DETAIL_VARIANTS]:
        try:
            callback_data = encode_quote_callback(product.id, variant.id, source)
        except CallbackCodecError:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=_button_text(
                        "Báo giá mô phỏng: " if product.supplier == "mock" else "Xem giá: ",
                        _seller_display(
                            variant.name,
                            96,
                            fallback="Biến thể không có tên hiển thị",
                        ),
                    ),
                    callback_data=callback_data,
                )
            ]
        )
    return _keyboard(rows)


def _quote_lines(product: CatalogProduct, variant: CatalogVariant) -> list[str]:
    product_name = _seller_display(
        product.name,
        120,
        fallback="Sản phẩm không có tên hiển thị",
    )
    variant_name = _seller_display(
        variant.name,
        96,
        fallback="Biến thể không có tên hiển thị",
    )
    title = (
        "BÁO GIÁ MÔ PHỎNG — MOCK / CHỈ ĐỌC"
        if product.supplier == "mock"
        else f"THÔNG TIN GIÁ — {SELLER_CATALOG_LABEL}"
    )
    lines = [
        title,
        f"Sản phẩm: {product_name}",
        f"Biến thể: {variant_name}",
        f"Giá hiện tại: {_format_money(variant.price)}",
    ]
    if variant.available_quantity == 0:
        lines.append("Tình trạng hiện tại: hết hàng (available_quantity=0).")
    else:
        lines.append(
            "Tồn kho tham khảo hiện tại: "
            f"available_quantity={variant.available_quantity}; không bảo đảm sẽ còn hàng."
        )
    lines.extend(
        (
            "Đây chỉ là thông tin đọc tại thời điểm hiện tại, không phải lời hứa "
            "về giá hoặc khả dụng.",
            "Không tạo hay giữ chỗ, đơn hàng, thanh toán, mua hàng, nạp tiền, "
            "hoàn tiền hoặc giao hàng.",
        )
    )
    return lines


async def _read_detail(
    catalog: CatalogReader,
    product_id: str,
) -> CatalogDetailResponse | None:
    try:
        return await catalog.get_product(product_id)
    except Exception:
        return None


async def _handle_detail_callback(
    message: AnswerableMessage,
    catalog: CatalogReader,
    product_id: str,
    source: LiveCatalogSupplier | None,
) -> None:
    response = await _read_detail(catalog, product_id)
    if isinstance(response, CatalogDetailFound):
        if response.item.id != product_id:
            await _send(message, (SAFE_REFRESH_MESSAGE,))
            return
        await _send(
            message,
            _detail_lines(response.item),
            keyboard=_detail_keyboard(response.item, source=source),
        )
        return
    if isinstance(response, CatalogDetailNotFound):
        await _send(
            message,
            (
                "Không tìm thấy sản phẩm này trong danh mục chỉ đọc hiện tại. "
                "Vui lòng dùng /catalog để làm mới; không có dữ liệu nào được suy đoán.",
            ),
        )
        return
    if isinstance(response, CatalogDetailUnsupported):
        await _send(
            message,
            (
                "Chi tiết sản phẩm này hiện không được hỗ trợ trong chế độ chỉ đọc. "
                "Bot không suy đoán dữ liệu; vui lòng quay lại /catalog.",
            ),
        )
        return
    await _send(message, (SAFE_REFRESH_MESSAGE,))


async def _handle_quote_callback(
    message: AnswerableMessage,
    catalog: CatalogReader,
    product_id: str,
    variant_id: str | None,
) -> None:
    if variant_id is None:
        await _send(message, (SAFE_REFRESH_MESSAGE,))
        return

    response = await _read_detail(catalog, product_id)
    if not isinstance(response, CatalogDetailFound) or response.item.id != product_id:
        await _send(message, (SAFE_REFRESH_MESSAGE,))
        return

    product = response.item
    variant = next((item for item in product.variants if item.id == variant_id), None)
    if variant is None:
        await _send(message, (SAFE_REFRESH_MESSAGE,))
        return
    await _send(message, _quote_lines(product, variant))


async def callback_handler(
    callback: AnswerableCallbackQuery,
    catalog: CatalogReader | CatalogRegistry | None = None,
) -> None:
    """Clear the callback spinner, validate IDs, and re-resolve all server data."""
    await callback.answer()
    message = callback.message
    if message is None:
        return

    try:
        payload = decode_callback(callback.data)
    except CallbackCodecError:
        await _send(message, (SAFE_REFRESH_MESSAGE,))
        return

    access = _catalog_access_or_default(catalog)
    if isinstance(access, CatalogRegistry):
        if payload.action is CallbackAction.SOURCE:
            if access.aggregate_available:
                await aggregate_catalog_handler(message, access)
                return
            if payload.source is None or payload.source == "all":
                await _send(message, (SAFE_REFRESH_MESSAGE,))
                return
            try:
                reader = access.resolve(payload.source)
            except (CatalogSourceSelectionRequired, CatalogSourceUnavailable):
                await _send(message, (SAFE_REFRESH_MESSAGE,))
                return
            await catalog_handler(message, reader, source=payload.source)
            return
        if payload.source == "all":
            await _send(message, (SAFE_REFRESH_MESSAGE,))
            return
        if payload.source is None and access.sources != ("mock",):
            await _send(message, (SAFE_REFRESH_MESSAGE,))
            return
        try:
            reader = access.resolve(payload.source)
        except (CatalogSourceSelectionRequired, CatalogSourceUnavailable):
            await _send(message, (SAFE_REFRESH_MESSAGE,))
            return
    else:
        if payload.source is not None:
            await _send(message, (SAFE_REFRESH_MESSAGE,))
            return
        reader = access

    if payload.action is CallbackAction.SOURCE:
        await _send(message, (SAFE_REFRESH_MESSAGE,))
        return
    if payload.product_id is None:
        await _send(message, (SAFE_REFRESH_MESSAGE,))
        return
    if payload.action is CallbackAction.DETAIL:
        await _handle_detail_callback(
            message,
            reader,
            payload.product_id,
            payload.source,
        )
        return
    await _handle_quote_callback(message, reader, payload.product_id, payload.variant_id)


async def storefront_callback_handler(
    callback: AnswerableCallbackQuery,
    storefront: StorefrontCatalogReader,
) -> None:
    """Resolve a Nyan detail callback without accepting source or quote actions."""
    await callback.answer()
    message = callback.message
    if message is None:
        return
    try:
        payload = decode_callback(callback.data)
    except CallbackCodecError:
        await _send(message, (SAFE_REFRESH_MESSAGE,))
        return
    if (
        payload.action is not CallbackAction.DETAIL
        or payload.source is not None
        or payload.product_id is None
    ):
        await _send(message, (SAFE_REFRESH_MESSAGE,))
        return
    try:
        response = await storefront.get_storefront_product(payload.product_id)
    except Exception:
        await _send(message, (SAFE_REFRESH_MESSAGE,))
        return
    if isinstance(response, StorefrontDetailFound):
        if response.item.id != payload.product_id:
            await _send(message, (SAFE_REFRESH_MESSAGE,))
            return
        await _send(message, _storefront_detail_lines(response.item))
        return
    if isinstance(response, StorefrontDetailNotFound):
        await _send(
            message,
            (
                "Sản phẩm này không còn trong danh mục Nyan hiện tại. "
                "Vui lòng dùng /catalog để làm mới; không có thao tác nào được tạo.",
            ),
        )
        return
    await _send(message, (SAFE_REFRESH_MESSAGE,))


def build_router(
    catalog: CatalogReader | CatalogRegistry | None = None,
    *,
    storefront: StorefrontCatalogReader | None = None,
) -> Router:
    """Build handlers around an injected read-only catalog, without a Bot or token."""
    access = None if storefront is not None else _catalog_access_or_default(catalog)
    router = Router(name="foundation")

    async def injected_catalog_handler(message: AnswerableMessage) -> None:
        if storefront is not None:
            await storefront_catalog_handler(message, storefront)
            return
        assert access is not None
        if isinstance(access, CatalogRegistry):
            if access.aggregate_available:
                await aggregate_catalog_handler(message, access)
                return
            if access.selection_required:
                await _send(message, (SAFE_CATALOG_ERROR_MESSAGE,))
                return
            configured_source = access.sources[0]
            await catalog_handler(
                message,
                access.resolve(),
                source=_live_source(configured_source),
            )
            return
        await catalog_handler(message, access)

    async def injected_callback_handler(callback: AnswerableCallbackQuery) -> None:
        if storefront is not None:
            await storefront_callback_handler(callback, storefront)
            return
        assert access is not None
        await callback_handler(callback, access)

    router.message(CommandStart())(start_handler)
    router.message(Command("catalog"))(injected_catalog_handler)
    router.message(Command("orders"))(orders_handler)
    router.message(Command("support"))(support_handler)
    router.callback_query()(injected_callback_handler)
    return router


def build_dispatcher(
    catalog: CatalogReader | CatalogRegistry | None = None,
    *,
    storefront: StorefrontCatalogReader | None = None,
) -> Dispatcher:
    """Build a dispatcher only; never read a token or start polling/webhooks."""
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(catalog, storefront=storefront))
    return dispatcher
