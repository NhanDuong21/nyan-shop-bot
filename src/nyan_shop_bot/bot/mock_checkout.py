"""Offline-capable, explicitly allowlisted Telegram mock checkout dispatcher."""

from __future__ import annotations

import hashlib
import re

from aiogram import Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from nyan_shop_bot.catalog.mock import FakeCatalogReader
from nyan_shop_bot.config import Settings, is_loopback_host
from nyan_shop_bot.orders.errors import OrderError
from nyan_shop_bot.orders.fakes import FakePurchaseOutcome
from nyan_shop_bot.orders.mock_checkout import create_mock_order_service
from nyan_shop_bot.orders.models import MinorMoney, OrderRequest, OrderSnapshot
from nyan_shop_bot.orders.ports import OrderRepository

_CALLBACK = re.compile(r"^mc:([0-9]):([0-9]):([sfu])$")
_OUTCOMES = {
    "s": FakePurchaseOutcome.SUCCESS,
    "f": FakePurchaseOutcome.OUT_OF_STOCK,
    "u": FakePurchaseOutcome.ACCEPTED,
}


def _status(snapshot: OrderSnapshot) -> str:
    total = snapshot.unit_price.amount_minor * snapshot.quantity
    result = (
        f"Đơn MOCK {snapshot.intent_id[:8]} · {snapshot.purchase_state.value} · "
        f"{total:,} {snapshot.unit_price.currency} (minor)"
    )
    if snapshot.failure_code is not None:
        result += f" · {snapshot.failure_code.value}"
    if snapshot.purchase_state.value in {"UNKNOWN", "RECONCILING"}:
        result += " · chưa có kết quả cuối; không tạo đơn thứ hai"
    return result


def build_mock_checkout_dispatcher(
    *, settings: Settings, repository: OrderRepository, allowed_user_id: int
) -> Dispatcher:
    """Build transport-free handlers; caller controls whether to start Telegram."""
    if (
        settings.app_env not in {"local", "test"}
        or not is_loopback_host(settings.app_host)
        or settings.supplier_mode != "mock"
        or settings.payment_mode != "disabled"
        or settings.allow_real_purchases
        or allowed_user_id <= 0
    ):
        raise ValueError("mock bot requires a local safe profile and an allowlisted user")

    router = Router(name="mock-checkout")

    @router.message(Command("catalog"))
    async def catalog(message: Message) -> None:
        if message.from_user is None or message.from_user.id != allowed_user_id:
            await message.answer("Demo MOCK: không có quyền truy cập.")
            return
        response = await FakeCatalogReader().read_catalog()
        lines = ["CATALOG MOCK — sản phẩm tổng hợp; không liên quan nguồn hàng thật."]
        rows: list[list[InlineKeyboardButton]] = []
        for product_index, product in enumerate(response.items):
            for variant_index, variant in enumerate(product.variants):
                if variant.available_quantity <= 0:
                    continue
                lines.append(
                    f"{product.name} / {variant.name}: "
                    f"{variant.price.amount_minor:,} {variant.price.currency} (minor)"
                )
                for code, label in (("s", "thành công"), ("f", "lỗi an toàn"), ("u", "UNKNOWN")):
                    rows.append(
                        [
                            InlineKeyboardButton(
                                text=f"{product.name}: {label}",
                                callback_data=f"mc:{product_index}:{variant_index}:{code}",
                            )
                        ]
                    )
        await message.answer(
            "\n".join(lines), reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
        )

    @router.message(Command("orders"))
    async def orders(message: Message) -> None:
        if message.from_user is None or message.from_user.id != allowed_user_id:
            await message.answer("Demo MOCK: không có quyền truy cập.")
            return
        snapshots = await create_mock_order_service(settings, repository).list_recent(
            customer_reference=f"telegram:{allowed_user_id}", limit=10
        )
        await message.answer(
            "\n".join(["LỊCH SỬ ĐƠN MOCK", *(_status(item) for item in snapshots)])
            if snapshots
            else "Chưa có đơn MOCK."
        )

    @router.callback_query()
    async def checkout(callback: CallbackQuery) -> None:
        await callback.answer()
        message = callback.message
        if callback.from_user.id != allowed_user_id or not isinstance(message, Message):
            return
        match = _CALLBACK.fullmatch(callback.data or "")
        if match is None:
            await message.answer("Nút demo không hợp lệ. Dùng /catalog để tải lại.")
            return
        product_index, variant_index, code = match.groups()
        response = await FakeCatalogReader().read_catalog()
        try:
            product = response.items[int(product_index)]
            variant = product.variants[int(variant_index)]
        except IndexError:
            await message.answer("Sản phẩm demo không còn hợp lệ. Dùng /catalog.")
            return
        key_source = (
            f"telegram:{allowed_user_id}:{message.chat.id}:{message.message_id}:"
            f"{product.id}:{variant.id}"
        )
        key = hashlib.sha256(key_source.encode("ascii")).hexdigest()
        try:
            snapshot = await create_mock_order_service(
                settings, repository, purchase=_OUTCOMES[code]
            ).place_order(
                customer_reference=f"telegram:{allowed_user_id}",
                request=OrderRequest(
                    product_id=product.id,
                    variant_id=variant.id,
                    quantity=1,
                    idempotency_key=key,
                    max_unit_price=MinorMoney.from_catalog(variant.price),
                ),
            )
        except OrderError:
            await message.answer("Không thể tạo đơn MOCK an toàn. Dùng /orders để kiểm tra.")
            return
        await message.answer(_status(snapshot))

    dispatcher = Dispatcher()
    dispatcher.include_router(router)
    return dispatcher
