"""Deterministic synthetic catalog; no partner data or credentials."""

from nyan_shop_bot.catalog.models import CatalogItem, Money, SupplierCapabilities


class MockCatalogReader:
    """Small in-memory catalog used by local development and tests."""

    capabilities = SupplierCapabilities()

    _items = (
        CatalogItem(
            id="mock-learning-pass-30d",
            name="Gói học tập mẫu 30 ngày",
            description="Sản phẩm tổng hợp chỉ dùng để kiểm thử giao diện.",
            price=Money(amount_minor=49_000, currency="VND"),
            available_quantity=12,
        ),
        CatalogItem(
            id="mock-design-seat-7d",
            name="Chỗ ngồi thiết kế mẫu 7 ngày",
            description="Không đại diện cho hàng hóa hay tồn kho của nhà cung cấp thật.",
            price=Money(amount_minor=25_000, currency="VND"),
            available_quantity=5,
        ),
        CatalogItem(
            id="mock-toolkit-1m",
            name="Bộ công cụ mẫu 1 tháng",
            description="Fixture giả, không thể đặt mua hoặc thanh toán.",
            price=Money(amount_minor=79_000, currency="VND"),
            available_quantity=0,
        ),
    )

    async def list_products(self) -> list[CatalogItem]:
        return list(self._items)

    async def get_product(self, product_id: str) -> CatalogItem | None:
        return next((item for item in self._items if item.id == product_id), None)
