"""Offline-testable aiogram catalog handlers with no transport startup."""

from __future__ import annotations

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
    CatalogDetailFound,
    CatalogDetailNotFound,
    CatalogDetailResponse,
    CatalogDetailUnsupported,
    CatalogProduct,
    CatalogResponse,
    CatalogState,
    CatalogVariant,
    Money,
)
from nyan_shop_bot.catalog.ports import CatalogReader

MAX_MESSAGE_CHARS: Final = 3_500
MAX_BUTTON_TEXT_CHARS: Final = 64
MAX_CATALOG_ITEMS: Final = 20
MAX_DETAIL_VARIANTS: Final = 20

SAFE_REFRESH_MESSAGE: Final = (
    "Nút này không còn hợp lệ hoặc dữ liệu đã thay đổi. "
    "Vui lòng dùng /catalog để làm mới; không có thao tác nào được tạo."
)
SAFE_CATALOG_ERROR_MESSAGE: Final = (
    "Không thể tải danh mục MOCK lúc này. Vui lòng thử lại bằng /catalog sau. "
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


def _bounded_display(value: str, limit: int, *, fallback: str) -> str:
    visible = "".join(
        " " if unicodedata.category(character).startswith("C") else character for character in value
    )
    visible = " ".join(visible.split())
    if not visible:
        return fallback
    if len(visible) <= limit:
        return visible
    return f"{visible[: limit - 1].rstrip()}…"


def _bounded_message(lines: Sequence[str]) -> str:
    text = "\n".join(lines)
    if len(text) <= MAX_MESSAGE_CHARS:
        return text
    return f"{text[: MAX_MESSAGE_CHARS - 1].rstrip()}…"


def _format_money(money: Money) -> str:
    """Render the stored integer and its contract metadata without conversion."""
    return f"amount_minor={money.amount_minor}; currency={money.currency}; unit={money.unit}"


def _button_text(prefix: str, value: str) -> str:
    return _bounded_display(f"{prefix}{value}", MAX_BUTTON_TEXT_CHARS, fallback=prefix.rstrip())


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
    """Explain the honest MOCK/read-only state and static command menu."""
    await _send(
        message,
        (
            "Nyan Shop Bot — MOCK / CHỈ ĐỌC.",
            "Bot chỉ cho phép xem dữ liệu mô phỏng; thanh toán và mua hàng thật "
            "hiện bị vô hiệu hóa.",
            "Menu: /catalog xem danh mục · /orders xem trạng thái đơn · /support xem trợ giúp.",
        ),
    )


def _catalog_lines(response: CatalogResponse) -> list[str]:
    if response.state is CatalogState.EMPTY:
        return [
            "DANH MỤC — MOCK / CHỈ ĐỌC",
            "Danh mục hiện trống; không có sản phẩm mô phỏng nào để hiển thị.",
            "Không có đơn hàng hoặc giao dịch nào được tạo.",
        ]
    if response.state is CatalogState.ERROR:
        return [SAFE_CATALOG_ERROR_MESSAGE]

    lines = ["DANH MỤC — MOCK / CHỈ ĐỌC"]
    if response.state is CatalogState.STALE:
        lines.append(
            "⚠ CẢNH BÁO: đang hiển thị dữ liệu bộ nhớ đệm đã cũ; lần làm mới gần nhất thất bại."
        )
    else:
        lines.append("Dữ liệu danh mục hiện đang ở trạng thái mới.")

    visible_items = response.items[:MAX_CATALOG_ITEMS]
    for index, product in enumerate(visible_items, start=1):
        name = _bounded_display(product.name, 96, fallback="Sản phẩm không có tên hiển thị")
        lines.append(
            f"{index}. {name} — {_format_money(product.price)}; "
            f"available_quantity={product.available_quantity}"
        )
    if len(response.items) > len(visible_items):
        lines.append(
            f"Chỉ hiển thị {len(visible_items)} sản phẩm đầu tiên để giữ tin nhắn an toàn."
        )
    lines.append("Giá và tồn kho chỉ là thông tin MOCK hiện tại, không phải cam kết bán hàng.")
    return lines


def _catalog_keyboard(response: CatalogResponse) -> InlineKeyboardMarkup | None:
    if response.state not in (CatalogState.FRESH, CatalogState.STALE):
        return None

    rows: list[list[InlineKeyboardButton]] = []
    for product in response.items[:MAX_CATALOG_ITEMS]:
        try:
            callback_data = encode_detail_callback(product.id)
        except CallbackCodecError:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=_button_text("Chi tiết: ", product.name),
                    callback_data=callback_data,
                )
            ]
        )
    return _keyboard(rows)


async def catalog_handler(
    message: AnswerableMessage,
    catalog: CatalogReader | None = None,
) -> None:
    """Read and render every normalized catalog envelope state safely."""
    reader = _catalog_or_default(catalog)
    try:
        response = await reader.read_catalog()
    except Exception:
        await _send(message, (SAFE_CATALOG_ERROR_MESSAGE,))
        return

    await _send(message, _catalog_lines(response), keyboard=_catalog_keyboard(response))


async def orders_handler(message: AnswerableMessage) -> None:
    """State that the read-only trial has no checkout or real orders."""
    await _send(
        message,
        (
            "ĐƠN HÀNG — MOCK / CHỈ ĐỌC",
            "Checkout và đơn hàng thật hiện không khả dụng.",
            "Bot không tạo, lưu, gửi hoặc thanh toán bất kỳ đơn hàng nào.",
        ),
    )


async def support_handler(message: AnswerableMessage) -> None:
    """Provide static offline help without inventing contact details."""
    await _send(
        message,
        (
            "HỖ TRỢ TĨNH / NGOẠI TUYẾN — MOCK",
            "Dùng /catalog để tải lại danh mục, /orders để xem giới hạn đơn hàng, "
            "hoặc /start để xem menu.",
            "Chưa có thông tin liên hệ hỗ trợ nào được cấu hình trong bot này.",
        ),
    )


def _detail_lines(product: CatalogProduct) -> list[str]:
    lines = [
        "CHI TIẾT SẢN PHẨM — MOCK / CHỈ ĐỌC",
        f"Tên: {_bounded_display(product.name, 120, fallback='Sản phẩm không có tên hiển thị')}",
        f"Mô tả: {_bounded_display(product.description, 500, fallback='Không có mô tả hiển thị')}",
        "Các biến thể hiện tại:",
    ]
    visible_variants = product.variants[:MAX_DETAIL_VARIANTS]
    for variant in visible_variants:
        name = _bounded_display(variant.name, 96, fallback="Biến thể không có tên hiển thị")
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


def _detail_keyboard(product: CatalogProduct) -> InlineKeyboardMarkup | None:
    rows: list[list[InlineKeyboardButton]] = []
    for variant in product.variants[:MAX_DETAIL_VARIANTS]:
        try:
            callback_data = encode_quote_callback(product.id, variant.id)
        except CallbackCodecError:
            continue
        rows.append(
            [
                InlineKeyboardButton(
                    text=_button_text("Báo giá mô phỏng: ", variant.name),
                    callback_data=callback_data,
                )
            ]
        )
    return _keyboard(rows)


def _quote_lines(product: CatalogProduct, variant: CatalogVariant) -> list[str]:
    product_name = _bounded_display(
        product.name,
        120,
        fallback="Sản phẩm không có tên hiển thị",
    )
    variant_name = _bounded_display(
        variant.name,
        96,
        fallback="Biến thể không có tên hiển thị",
    )
    lines = [
        "BÁO GIÁ MÔ PHỎNG — MOCK / CHỈ ĐỌC",
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
            "Đây chỉ là thông tin mô phỏng, không phải lời hứa về giá hoặc khả dụng.",
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
) -> None:
    response = await _read_detail(catalog, product_id)
    if isinstance(response, CatalogDetailFound):
        if response.item.id != product_id:
            await _send(message, (SAFE_REFRESH_MESSAGE,))
            return
        await _send(
            message,
            _detail_lines(response.item),
            keyboard=_detail_keyboard(response.item),
        )
        return
    if isinstance(response, CatalogDetailNotFound):
        await _send(
            message,
            (
                "Không tìm thấy sản phẩm này trong danh mục MOCK hiện tại. "
                "Vui lòng dùng /catalog để làm mới; không có dữ liệu nào được suy đoán.",
            ),
        )
        return
    if isinstance(response, CatalogDetailUnsupported):
        await _send(
            message,
            (
                "Chi tiết sản phẩm này hiện không được hỗ trợ trong chế độ MOCK / CHỈ ĐỌC. "
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
    catalog: CatalogReader | None = None,
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

    reader = _catalog_or_default(catalog)
    if payload.action is CallbackAction.DETAIL:
        await _handle_detail_callback(message, reader, payload.product_id)
        return
    await _handle_quote_callback(message, reader, payload.product_id, payload.variant_id)


def build_router(catalog: CatalogReader | None = None) -> Router:
    """Build handlers around an injected read-only catalog, without a Bot or token."""
    reader = _catalog_or_default(catalog)
    router = Router(name="foundation")

    async def injected_catalog_handler(message: AnswerableMessage) -> None:
        await catalog_handler(message, reader)

    async def injected_callback_handler(callback: AnswerableCallbackQuery) -> None:
        await callback_handler(callback, reader)

    router.message(CommandStart())(start_handler)
    router.message(Command("catalog"))(injected_catalog_handler)
    router.message(Command("orders"))(orders_handler)
    router.message(Command("support"))(support_handler)
    router.callback_query()(injected_callback_handler)
    return router


def build_dispatcher(catalog: CatalogReader | None = None) -> Dispatcher:
    """Build a dispatcher only; never read a token or start polling/webhooks."""
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(catalog))
    return dispatcher
