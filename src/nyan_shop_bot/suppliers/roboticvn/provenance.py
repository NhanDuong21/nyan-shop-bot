"""Sanitized, machine-testable provenance facts for the Roboticvn v2 adapter."""

from typing import Final

PRODUCTION_ORIGIN: Final = "https://api.roboticvn.com"
API_PREFIX: Final = "/api/v2"
GLOBAL_AUTH_HEADER: Final = "x-api-key"

PASTED_SWAGGER_SHA256: Final = "09be6d7dd099c57115ecd611d67bc0a28b0dcb12634b7435051d98e20db0cc9f"
PUBLIC_OPENAPI_URL: Final = f"{PRODUCTION_ORIGIN}{API_PREFIX}/docs/openapi.json"
PUBLIC_OPENAPI_SHA256: Final = "22de68f114b6c30e68cc88ded579bf4b77632f43bc67fe9c74bbe60f8cdb1930"
PUBLIC_FETCHED_AT: Final = "2026-09-21T03:05:06Z"
PUBLIC_FETCH_HTTP_STATUS: Final = 200
PUBLIC_FETCH_CONTENT_TYPE: Final = "application/json"
PUBLIC_FETCH_RAW_BYTES: Final = 19_482
PUBLIC_OPENAPI_SPEC_VERSION: Final = "3.0.3"
PUBLIC_API_TITLE: Final = "Roboticvn Customer API"
PUBLIC_API_VERSION: Final = "2.2.0"

AUTHORIZED_READ_PATHS: Final = (
    "/api/v2/products",
    "/api/v2/products/{id}",
    "/api/v2/wallet/balance",
    "/api/v2/wallet/transactions",
)
