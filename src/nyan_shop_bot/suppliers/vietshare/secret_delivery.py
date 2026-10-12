"""Restricted, encrypted local delivery store for one capped VietShare test.

The encryption key belongs in an ignored local environment file. Neither the
journal nor this module's exceptions or representations expose account material.
"""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nyan_shop_bot.suppliers.vietshare.write_orders import DeliveredAccounts


class SecretDeliveryError(ValueError):
    """A redacted delivery-store failure."""


@dataclass(frozen=True, repr=False)
class SecretDelivery:
    reference: str
    accounts: DeliveredAccounts = field(repr=False)

    def __repr__(self) -> str:
        return "SecretDelivery(<redacted>)"


class VietShareSecretDeliveryStore:
    """Encrypt account material in a separate PostgreSQL table for at most 24 h."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession], *, key: bytes) -> None:
        try:
            self._cipher = Fernet(key)
        except (TypeError, ValueError):
            raise SecretDeliveryError("Invalid local delivery encryption key") from None
        self._sessions = sessions

    def __repr__(self) -> str:
        return "VietShareSecretDeliveryStore(<redacted>)"

    async def put(self, *, test_id: str, order_code: str, accounts: DeliveredAccounts) -> str:
        if not isinstance(accounts, DeliveredAccounts) or not accounts.values:
            raise SecretDeliveryError("Invalid supplier delivery")
        try:
            plaintext = json.dumps(
                list(accounts.values), ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, UnicodeError):
            raise SecretDeliveryError("Invalid supplier delivery") from None
        if len(plaintext) > 16_000:
            raise SecretDeliveryError("Supplier delivery exceeds local size limit")
        async with self._sessions() as session, session.begin():
            existing = (
                (
                    await session.execute(
                        text("""
                            SELECT delivery_ref, supplier_order_code, ciphertext,
                                expires_at > clock_timestamp() AS active
                            FROM vietshare_secret_deliveries
                            WHERE test_id=:id FOR UPDATE
                        """),
                        {"id": test_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
            if existing is not None:
                try:
                    identical = self._cipher.decrypt(bytes(existing["ciphertext"])) == plaintext
                except InvalidToken:
                    identical = False
                if (
                    not existing["active"]
                    or existing["supplier_order_code"] != order_code
                    or not identical
                ):
                    raise SecretDeliveryError("Existing delivery conflicts with supplier result")
                return str(existing["delivery_ref"])
            reference = secrets.token_hex(16)
            ciphertext = self._cipher.encrypt(plaintext)
            await session.execute(
                text("""
                    INSERT INTO vietshare_secret_deliveries
                        (delivery_ref, test_id, supplier_order_code, ciphertext,
                         expires_at)
                    VALUES (:ref, :id, :code, :ciphertext,
                            clock_timestamp() + INTERVAL '24 hours')
                """),
                {
                    "ref": reference,
                    "id": test_id,
                    "code": order_code,
                    "ciphertext": ciphertext,
                },
            )
            return reference

    async def read(self, *, reference: str, operator_id: str) -> SecretDelivery:
        """Return material only to the journal's authenticated local operator."""
        async with self._sessions() as session:
            row = (
                (
                    await session.execute(
                        text("""
                            SELECT d.ciphertext FROM vietshare_secret_deliveries AS d
                            JOIN vietshare_write_journal AS j ON j.test_id=d.test_id
                            WHERE d.delivery_ref=:ref AND j.secret_delivery_ref=:ref
                                AND j.operator_id=:operator
                                AND j.state IN ('SUCCEEDED','RECONCILING')
                                AND d.expires_at > clock_timestamp()
                        """),
                        {"ref": reference, "operator": operator_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise SecretDeliveryError("Delivery is unavailable to this operator")
        try:
            values = json.loads(self._cipher.decrypt(bytes(row["ciphertext"])))
            if (
                type(values) is not list
                or not values
                or any(type(value) is not str or not value for value in values)
            ):
                raise ValueError
        except (InvalidToken, ValueError, TypeError, UnicodeError):
            raise SecretDeliveryError("Stored delivery cannot be opened") from None
        return SecretDelivery(reference, DeliveredAccounts(tuple(values)))

    async def acknowledge(self, *, reference: str, operator_id: str) -> None:
        """Erase ciphertext after the operator confirms secure handoff."""
        async with self._sessions() as session, session.begin():
            deleted = await session.execute(
                text("""
                    DELETE FROM vietshare_secret_deliveries AS d
                    USING vietshare_write_journal AS j
                    WHERE d.test_id=j.test_id AND d.delivery_ref=:ref
                        AND j.secret_delivery_ref=:ref AND j.operator_id=:operator
                        AND j.state IN ('SUCCEEDED','RECONCILING')
                    RETURNING d.delivery_ref
                """),
                {"ref": reference, "operator": operator_id},
            )
            if deleted.scalar_one_or_none() is None:
                raise SecretDeliveryError("Delivery is unavailable to this operator")

    async def purge_expired(self) -> int:
        return await self.purge_expired_rows(self._sessions)

    @staticmethod
    async def purge_expired_rows(sessions: async_sessionmaker[AsyncSession]) -> int:
        """Remove expired ciphertext without needing the encryption key."""
        async with sessions() as session, session.begin():
            result = await session.execute(
                text("""
                    DELETE FROM vietshare_secret_deliveries
                    WHERE expires_at <= clock_timestamp()
                    RETURNING delivery_ref
                """)
            )
            return len(result.all())
