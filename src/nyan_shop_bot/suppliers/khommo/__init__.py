"""Offline-testable, read-only KhoMMO integration."""

from nyan_shop_bot.suppliers.khommo.adapter import (
    KHOMMO_CAPABILITIES,
    PRODUCTION_BASE_URL,
    KhoMmoReadAdapter,
    KhoMmoTransport,
    Sleeper,
)
from nyan_shop_bot.suppliers.khommo.catalog_reader import (
    KhoMmoCatalogReader,
    KhoMmoCatalogSourceUnavailable,
)
from nyan_shop_bot.suppliers.khommo.http_transport import (
    KhoMmoHttpTransport,
    KhoMmoTransportSafetyError,
)
from nyan_shop_bot.suppliers.khommo.models import (
    Account,
    CreditUnits,
    KhoMmoConfigurationError,
    KhoMmoRequest,
    KhoMmoResponse,
    KhoMmoToken,
    OutcomeCode,
    PaymentMode,
    Product,
    ReadFailure,
    ReadOutcome,
    ReadSuccess,
    SensitiveHeaders,
    UnsupportedSchemaError,
    VndUnits,
    Wallet,
    parse_account,
    parse_product,
    parse_products,
)

__all__ = [
    "KHOMMO_CAPABILITIES",
    "PRODUCTION_BASE_URL",
    "Account",
    "CreditUnits",
    "KhoMmoConfigurationError",
    "KhoMmoCatalogReader",
    "KhoMmoCatalogSourceUnavailable",
    "KhoMmoHttpTransport",
    "KhoMmoReadAdapter",
    "KhoMmoRequest",
    "KhoMmoResponse",
    "KhoMmoToken",
    "KhoMmoTransport",
    "KhoMmoTransportSafetyError",
    "OutcomeCode",
    "PaymentMode",
    "Product",
    "ReadFailure",
    "ReadOutcome",
    "ReadSuccess",
    "SensitiveHeaders",
    "Sleeper",
    "UnsupportedSchemaError",
    "VndUnits",
    "Wallet",
    "parse_account",
    "parse_product",
    "parse_products",
]
