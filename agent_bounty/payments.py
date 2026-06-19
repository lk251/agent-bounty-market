from __future__ import annotations

from dataclasses import dataclass

from .util import require_currency, require_positive_amount, sha256_text


class PaymentGatewayError(RuntimeError):
    pass


@dataclass(frozen=True)
class GatewayCredit:
    external_id: str
    amount: int
    currency: str
    replayed: bool


@dataclass(frozen=True)
class GatewayBeneficiary:
    external_id: str
    replayed: bool


@dataclass(frozen=True)
class GatewayPayout:
    external_id: str
    status: str
    amount: int
    currency: str
    replayed: bool


class PaymentGateway:
    def credit_project_treasury(self, *, project_id: str, amount: int, currency: str, idempotency_key: str) -> GatewayCredit:
        raise NotImplementedError

    def ensure_solver_beneficiary(self, *, solver_id: str, idempotency_key: str) -> GatewayBeneficiary:
        raise NotImplementedError

    def release_payout(
        self,
        *,
        payout_id: str,
        solver_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
    ) -> GatewayPayout:
        raise NotImplementedError

    def retrieve_payout_status(self, *, external_id: str) -> str:
        raise NotImplementedError


class FakePaymentGateway(PaymentGateway):
    """Deterministic idempotent gateway for local tests and demos."""

    def __init__(self, *, fail_payout_keys: set[str] | None = None):
        self.credits: dict[str, GatewayCredit] = {}
        self.beneficiaries: dict[str, GatewayBeneficiary] = {}
        self.payouts: dict[str, GatewayPayout] = {}
        self.fail_payout_keys = set(fail_payout_keys or set())

    @staticmethod
    def _id(prefix: str, key: str) -> str:
        return f"{prefix}_{sha256_text(key).split(':', 1)[1][:24]}"

    def credit_project_treasury(self, *, project_id: str, amount: int, currency: str, idempotency_key: str) -> GatewayCredit:
        require_positive_amount(amount)
        currency = require_currency(currency)
        if idempotency_key in self.credits:
            old = self.credits[idempotency_key]
            return GatewayCredit(old.external_id, old.amount, old.currency, True)
        credit = GatewayCredit(self._id("fake_credit", idempotency_key), amount, currency, False)
        self.credits[idempotency_key] = credit
        return credit

    def ensure_solver_beneficiary(self, *, solver_id: str, idempotency_key: str) -> GatewayBeneficiary:
        if idempotency_key in self.beneficiaries:
            return GatewayBeneficiary(self.beneficiaries[idempotency_key].external_id, True)
        beneficiary = GatewayBeneficiary(self._id("fake_beneficiary", idempotency_key), False)
        self.beneficiaries[idempotency_key] = beneficiary
        return beneficiary

    def release_payout(
        self,
        *,
        payout_id: str,
        solver_id: str,
        amount: int,
        currency: str,
        idempotency_key: str,
    ) -> GatewayPayout:
        require_positive_amount(amount)
        currency = require_currency(currency)
        if idempotency_key in self.payouts:
            old = self.payouts[idempotency_key]
            return GatewayPayout(old.external_id, old.status, old.amount, old.currency, True)
        if idempotency_key in self.fail_payout_keys:
            raise PaymentGatewayError(f"fake payout failure for {idempotency_key}")
        payout = GatewayPayout(self._id("fake_payout", idempotency_key), "paid", amount, currency, False)
        self.payouts[idempotency_key] = payout
        return payout

    def retrieve_payout_status(self, *, external_id: str) -> str:
        for payout in self.payouts.values():
            if payout.external_id == external_id:
                return payout.status
        raise PaymentGatewayError(f"unknown fake payout {external_id}")


class StripePaymentGateway(PaymentGateway):
    """Documented boundary for future Stripe test-mode integration.

    This class intentionally cannot be used accidentally. The hackathon core
    gets its exactly-once state machine right against FakePaymentGateway before
    introducing real Stripe credentials, webhooks, or Connect onboarding.
    """

    def __init__(self, *, explicitly_configured: bool = False):
        if not explicitly_configured:
            raise PaymentGatewayError("StripePaymentGateway requires explicit test-mode configuration")
