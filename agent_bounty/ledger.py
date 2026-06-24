from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from typing import Iterable

from .util import require_currency, require_positive_amount, utc_now


class LedgerError(RuntimeError):
    pass


@dataclass(frozen=True)
class TransferResult:
    entry_id: str
    replayed: bool


class Ledger:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def balance(self, account: str, currency: str = "USD") -> int:
        currency = require_currency(currency)
        row = self.conn.execute(
            "SELECT balance FROM account_balances WHERE account = ? AND currency = ?",
            (account, currency),
        ).fetchone()
        return int(row["balance"]) if row else 0

    def balances(self, accounts: Iterable[str], currency: str = "USD") -> dict[str, int]:
        return {account: self.balance(account, currency) for account in accounts}

    def transfer(
        self,
        *,
        event_type: str,
        idempotency_key: str,
        from_account: str,
        to_account: str,
        amount: int,
        currency: str = "USD",
        project_id: str | None = None,
        bounty_id: str | None = None,
        solver_id: str | None = None,
        payout_id: str | None = None,
        external_id: str | None = None,
        prevent_negative_accounts: set[str] | None = None,
    ) -> TransferResult:
        require_positive_amount(amount)
        currency = require_currency(currency)
        existing = self.conn.execute(
            "SELECT id FROM ledger_entries WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing:
            return TransferResult(entry_id=existing["id"], replayed=True)
        if prevent_negative_accounts and from_account in prevent_negative_accounts:
            available = self.balance(from_account, currency)
            if available < amount:
                raise LedgerError(
                    f"insufficient funds in {from_account}: available {available} {currency}, need {amount}"
                )
        entry_id = "le_" + uuid.uuid4().hex
        try:
            self._ensure_account(from_account, currency)
            self._ensure_account(to_account, currency)
            self.conn.execute(
                "UPDATE account_balances SET balance = balance - ? WHERE account = ? AND currency = ?",
                (amount, from_account, currency),
            )
            self.conn.execute(
                "UPDATE account_balances SET balance = balance + ? WHERE account = ? AND currency = ?",
                (amount, to_account, currency),
            )
            self.conn.execute(
                """
                INSERT INTO ledger_entries(
                    id, event_type, idempotency_key, from_account, to_account, amount,
                    currency, project_id, bounty_id, solver_id, payout_id, external_id, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    event_type,
                    idempotency_key,
                    from_account,
                    to_account,
                    amount,
                    currency,
                    project_id,
                    bounty_id,
                    solver_id,
                    payout_id,
                    external_id,
                    utc_now(),
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise LedgerError(f"ledger transfer would violate balance constraints: {exc}") from exc
        return TransferResult(entry_id=entry_id, replayed=False)

    def _ensure_account(self, account: str, currency: str) -> None:
        allow_negative = 1 if account.startswith("external:") else 0
        self.conn.execute(
            """
            INSERT OR IGNORE INTO account_balances(account, currency, balance, allow_negative)
            VALUES (?, ?, 0, ?)
            """,
            (account, currency, allow_negative),
        )


def project_available_account(project_id: str) -> str:
    return f"project:{project_id}:available"


def project_reserved_account(project_id: str) -> str:
    return f"project:{project_id}:reserved"


def project_released_account(project_id: str) -> str:
    return f"project:{project_id}:released"


def project_refunded_account(project_id: str) -> str:
    return f"project:{project_id}:refunded"


def solver_earned_account(solver_id: str) -> str:
    return f"solver:{solver_id}:earned"


def solver_payout_transit_account(solver_id: str) -> str:
    return f"solver:{solver_id}:payout_transit"


def solver_paid_account(solver_id: str) -> str:
    return f"solver:{solver_id}:paid"


def solver_operating_available_account(solver_id: str) -> str:
    return f"solver:{solver_id}:operating_available"


def solver_operating_reserved_account(solver_id: str) -> str:
    return f"solver:{solver_id}:operating_reserved"


def solver_operating_spent_account(solver_id: str) -> str:
    return f"solver:{solver_id}:operating_spent"


def external_account(name: str) -> str:
    return f"external:{name}"


def platform_fee_account() -> str:
    return "platform:fees"
