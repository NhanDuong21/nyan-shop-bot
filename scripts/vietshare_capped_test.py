"""Local, product-28-only VietShare capped test control; defaults OFF.

This script is deliberately outside the FastAPI, admin, and Telegram runtimes.
Do not invoke arm or dispatch without the owner's separate final approval.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import time
from pathlib import Path
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nyan_shop_bot.config import is_loopback_host  # noqa: E402
from nyan_shop_bot.suppliers.vietshare.adapter import VietShareReadAdapter  # noqa: E402
from nyan_shop_bot.suppliers.vietshare.capped_runtime import (  # noqa: E402
    CappedTestPlan,
    LocalOsOperatorIdentity,
    VietShareCappedTestRuntime,
)
from nyan_shop_bot.suppliers.vietshare.capped_transport import (  # noqa: E402
    VietShareCappedOrderTransport,
)
from nyan_shop_bot.suppliers.vietshare.http_transport import (  # noqa: E402
    VietShareHttpTransport,
)
from nyan_shop_bot.suppliers.vietshare.models import VietShareCredentials  # noqa: E402
from nyan_shop_bot.suppliers.vietshare.pg_gate import VietSharePgGate  # noqa: E402
from nyan_shop_bot.suppliers.vietshare.secret_delivery import (  # noqa: E402
    VietShareSecretDeliveryStore,
)


class CappedSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore", hide_input_in_errors=True)

    app_env: Literal["local"] = "local"
    app_host: str = "127.0.0.1"
    supplier_mode: Literal["mock"] = "mock"
    payment_mode: Literal["disabled"] = "disabled"
    allow_real_purchases: Literal[False] = False
    database_url: str
    vietshare_api_id: SecretStr | None = None
    vietshare_api_secret: SecretStr | None = None
    vietshare_delivery_key: SecretStr | None = None
    vietshare_capped_test_enabled: bool = False

    @model_validator(mode="after")
    def require_local_database(self) -> Self:
        url = make_url(self.database_url)
        if (
            not is_loopback_host(self.app_host)
            or url.drivername != "postgresql+asyncpg"
            or not is_loopback_host(url.host or "")
            or url.database != "nyan_shop_bot"
        ):
            raise ValueError("Capped test requires the named local PostgreSQL database")
        return self


def load_plan(path: Path) -> CappedTestPlan:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        required = {
            "test_id",
            "product_id",
            "quantity",
            "max_unit_price_vnd",
            "absolute_spend_cap_vnd",
            "wallet_id",
            "operator_id",
        }
        if type(document) is not dict or set(document) != required:
            raise ValueError
        return CappedTestPlan(**document)
    except (OSError, ValueError, TypeError):
        raise SystemExit("Invalid local capped test plan") from None


async def run(args: argparse.Namespace) -> None:
    if args.command == "identity":
        print(LocalOsOperatorIdentity().current_id())
        return
    env_file = await asyncio.to_thread(Path(args.env_file).resolve)
    if not await asyncio.to_thread(env_file.is_file) or env_file.name == ".env.example":
        raise SystemExit("An ignored local environment file is required")
    settings = CappedSettings(_env_file=env_file)
    engine = create_async_engine(settings.database_url, hide_parameters=True, pool_pre_ping=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    gate = VietSharePgGate(sessions)
    try:
        if args.command == "disarm":
            await gate.disarm()
            print("DISARMED")
            return
        if args.command == "status":
            record = await gate.get(args.test_id)
            print("ABSENT" if record is None else record.state.value)
            return
        if args.command == "mark-reconciling":
            await gate.mark_reconciling(
                args.test_id,
                operator_id=LocalOsOperatorIdentity().current_id(),
                evidence_ref=args.evidence_ref,
            )
            print("RECONCILING")
            return
        if args.command == "mark-dispatch-lost":
            await gate.mark_dispatch_lost(
                args.test_id,
                operator_id=LocalOsOperatorIdentity().current_id(),
                evidence_ref=args.evidence_ref,
            )
            print("UNKNOWN")
            return
        if args.command == "purge-expired-deliveries":
            count = await VietShareSecretDeliveryStore.purge_expired_rows(sessions)
            print(f"PURGED {count}")
            return
        api_id = settings.vietshare_api_id
        api_secret = settings.vietshare_api_secret
        delivery_key = settings.vietshare_delivery_key
        if (
            api_id is None
            or not api_id.get_secret_value()
            or api_secret is None
            or not api_secret.get_secret_value()
            or delivery_key is None
            or not delivery_key.get_secret_value()
        ):
            raise SystemExit("Local VietShare credentials and delivery key are required")
        credentials = VietShareCredentials(api_id.get_secret_value(), api_secret.get_secret_value())
        try:
            key_bytes = delivery_key.get_secret_value().encode("ascii")
        except UnicodeError:
            raise SystemExit("Invalid local delivery encryption key") from None
        store = VietShareSecretDeliveryStore(sessions, key=key_bytes)
        read_transport = VietShareHttpTransport()
        write_transport = VietShareCappedOrderTransport()
        try:
            reader = VietShareReadAdapter(
                credentials=credentials,
                transport=read_transport,
                clock=time.time,
                nonce_source=lambda: secrets.token_hex(16),
                retry_sleeper=asyncio.sleep,
                max_retries=0,
            )
            runtime = VietShareCappedTestRuntime(
                gate=gate,
                delivery_store=store,
                credentials=credentials,
                transport=write_transport,
                product_reader=reader,
                operator=LocalOsOperatorIdentity(),
                kill_switch_enabled=settings.vietshare_capped_test_enabled,
            )
            if args.command == "prepare":
                await runtime.prepare(load_plan(Path(args.plan)))
                print("PREPARED")
            elif args.command == "arm":
                await runtime.arm(
                    load_plan(Path(args.plan)),
                    approved_by="NhanDuong21",
                    approval_ref=args.approval_ref,
                )
                print("ARMED")
            elif args.command == "dispatch":
                result = await runtime.dispatch(args.test_id)
                print(result.state.value)
        finally:
            await write_transport.aclose()
            await read_transport.aclose()
    finally:
        await engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", help="Ignored local capped-test environment file")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("identity")
    for name in ("prepare", "arm"):
        sub = commands.add_parser(name)
        sub.add_argument("--plan", required=True)
        if name == "arm":
            sub.add_argument("--approval-ref", required=True)
    for name in ("status", "dispatch", "mark-reconciling", "mark-dispatch-lost"):
        sub = commands.add_parser(name)
        sub.add_argument("--test-id", required=True)
        if name in {"mark-reconciling", "mark-dispatch-lost"}:
            sub.add_argument("--evidence-ref", required=True)
    commands.add_parser("disarm")
    commands.add_parser("purge-expired-deliveries")
    args = parser.parse_args()
    if args.command != "identity" and not args.env_file:
        parser.error("--env-file is required")
    try:
        asyncio.run(run(args))
    except (ValueError, OSError) as exc:
        # All domain errors are redacted; never render an exception chain.
        raise SystemExit(type(exc).__name__) from None
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
