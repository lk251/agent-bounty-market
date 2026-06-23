from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol

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


class StripeTransport(Protocol):
    def request(self, method: str, path: str, *, headers: dict[str, str], data: dict[str, str] | None = None) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class StripeTestConfig:
    secret_key: str
    solver_accounts: dict[str, str]
    payment_method: str = "pm_card_visa"
    api_base: str = "https://api.stripe.com"
    api_version: str | None = None

    def __post_init__(self) -> None:
        if not self.secret_key.startswith("sk_test_"):
            raise PaymentGatewayError("Stripe test gateway requires an sk_test_ secret key")
        if not self.solver_accounts:
            raise PaymentGatewayError("Stripe test gateway requires explicit solver account mapping")
        for solver_id, account_id in self.solver_accounts.items():
            if not solver_id.strip():
                raise PaymentGatewayError("Stripe solver account mapping contains an empty solver id")
            if not account_id.startswith("acct_"):
                raise PaymentGatewayError(f"Stripe account for solver {solver_id} must start with acct_")


class UrllibStripeTransport:
    def __init__(self, *, api_base: str = "https://api.stripe.com", timeout_seconds: float = 20.0):
        self.api_base = api_base.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, *, headers: dict[str, str], data: dict[str, str] | None = None) -> dict[str, Any]:
        body = None
        request_headers = dict(headers)
        if data is not None:
            body = urllib.parse.urlencode(data).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        request = urllib.request.Request(
            f"{self.api_base}{path}",
            data=body,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise PaymentGatewayError(f"Stripe API returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise PaymentGatewayError(f"Stripe API request failed: {exc}") from exc
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise PaymentGatewayError("Stripe API returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise PaymentGatewayError("Stripe API returned a non-object response")
        return parsed


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
    """Explicit Stripe test-mode gateway.

    It is intentionally unavailable unless constructed with a StripeTestConfig
    and explicitly_configured=True. The gateway uses only Stripe test keys and
    maps local funding to PaymentIntents and solver settlement to Transfers.
    """

    def __init__(
        self,
        *,
        config: StripeTestConfig | None = None,
        explicitly_configured: bool = False,
        transport: StripeTransport | None = None,
    ):
        if not explicitly_configured or config is None:
            raise PaymentGatewayError("StripePaymentGateway requires explicit test-mode configuration")
        self.config = config
        self.transport = transport or UrllibStripeTransport(api_base=config.api_base)
        self._credits: dict[str, GatewayCredit] = {}
        self._beneficiaries: dict[str, GatewayBeneficiary] = {}
        self._payouts: dict[str, GatewayPayout] = {}

    @classmethod
    def from_env(cls, *, env: dict[str, str], explicitly_configured: bool = False) -> "StripePaymentGateway":
        if env.get("AGENT_BOUNTY_STRIPE_TEST_MODE") != "1":
            raise PaymentGatewayError("set AGENT_BOUNTY_STRIPE_TEST_MODE=1 to enable Stripe test gateway")
        secret_key = env.get("STRIPE_SECRET_KEY", "")
        accounts_raw = env.get("AGENT_BOUNTY_STRIPE_SOLVER_ACCOUNTS_JSON", "")
        try:
            accounts = json.loads(accounts_raw)
        except json.JSONDecodeError as exc:
            raise PaymentGatewayError("AGENT_BOUNTY_STRIPE_SOLVER_ACCOUNTS_JSON must be JSON") from exc
        if not isinstance(accounts, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in accounts.items()):
            raise PaymentGatewayError("AGENT_BOUNTY_STRIPE_SOLVER_ACCOUNTS_JSON must be an object of solver id to acct_ id")
        config = StripeTestConfig(
            secret_key=secret_key,
            solver_accounts=accounts,
            payment_method=env.get("AGENT_BOUNTY_STRIPE_PAYMENT_METHOD", "pm_card_visa"),
            api_base=env.get("STRIPE_API_BASE", "https://api.stripe.com"),
        )
        return cls(config=config, explicitly_configured=explicitly_configured)

    def credit_project_treasury(self, *, project_id: str, amount: int, currency: str, idempotency_key: str) -> GatewayCredit:
        require_positive_amount(amount)
        currency = require_currency(currency)
        if idempotency_key in self._credits:
            old = self._credits[idempotency_key]
            return GatewayCredit(old.external_id, old.amount, old.currency, True)
        response = self._post(
            "/v1/payment_intents",
            idempotency_key=idempotency_key,
            data={
                "amount": str(amount),
                "currency": currency.lower(),
                "confirm": "true",
                "payment_method": self.config.payment_method,
                "metadata[agent_bounty_kind]": "project_funding",
                "metadata[project_id]": project_id,
                "metadata[idempotency_key]": idempotency_key,
            },
        )
        external_id = self._require_id(response, prefix="pi_")
        self._assert_amount_currency(response, amount=amount, currency=currency)
        credit = GatewayCredit(external_id, amount, currency, False)
        self._credits[idempotency_key] = credit
        return credit

    def ensure_solver_beneficiary(self, *, solver_id: str, idempotency_key: str) -> GatewayBeneficiary:
        if idempotency_key in self._beneficiaries:
            return GatewayBeneficiary(self._beneficiaries[idempotency_key].external_id, True)
        account_id = self.config.solver_accounts.get(solver_id)
        if account_id is None:
            raise PaymentGatewayError(f"no Stripe test connected account configured for solver {solver_id}")
        beneficiary = GatewayBeneficiary(account_id, False)
        self._beneficiaries[idempotency_key] = beneficiary
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
        if idempotency_key in self._payouts:
            old = self._payouts[idempotency_key]
            return GatewayPayout(old.external_id, old.status, old.amount, old.currency, True)
        destination = self.config.solver_accounts.get(solver_id)
        if destination is None:
            raise PaymentGatewayError(f"no Stripe test connected account configured for solver {solver_id}")
        response = self._post(
            "/v1/transfers",
            idempotency_key=idempotency_key,
            data={
                "amount": str(amount),
                "currency": currency.lower(),
                "destination": destination,
                "transfer_group": payout_id,
                "metadata[agent_bounty_kind]": "solver_payout",
                "metadata[payout_id]": payout_id,
                "metadata[solver_id]": solver_id,
                "metadata[idempotency_key]": idempotency_key,
            },
        )
        external_id = self._require_id(response, prefix="tr_")
        self._assert_amount_currency(response, amount=amount, currency=currency)
        payout = GatewayPayout(external_id, "paid", amount, currency, False)
        self._payouts[idempotency_key] = payout
        return payout

    def retrieve_payout_status(self, *, external_id: str) -> str:
        if not external_id.startswith("tr_"):
            raise PaymentGatewayError("Stripe transfer id must start with tr_")
        response = self._get(f"/v1/transfers/{urllib.parse.quote(external_id)}")
        self._require_id(response, prefix="tr_")
        return "paid"

    def _headers(self, *, idempotency_key: str | None = None) -> dict[str, str]:
        token = base64.b64encode(f"{self.config.secret_key}:".encode("utf-8")).decode("ascii")
        headers = {"Authorization": f"Basic {token}"}
        if self.config.api_version:
            headers["Stripe-Version"] = self.config.api_version
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _post(self, path: str, *, idempotency_key: str, data: dict[str, str]) -> dict[str, Any]:
        return self.transport.request("POST", path, headers=self._headers(idempotency_key=idempotency_key), data=data)

    def _get(self, path: str) -> dict[str, Any]:
        return self.transport.request("GET", path, headers=self._headers())

    @staticmethod
    def _require_id(response: dict[str, Any], *, prefix: str) -> str:
        external_id = response.get("id")
        if not isinstance(external_id, str) or not external_id.startswith(prefix):
            raise PaymentGatewayError(f"Stripe response missing {prefix} id")
        livemode = response.get("livemode")
        if livemode is not False:
            raise PaymentGatewayError("Stripe test gateway rejected a live-mode or unknown-mode response")
        return external_id

    @staticmethod
    def _assert_amount_currency(response: dict[str, Any], *, amount: int, currency: str) -> None:
        response_amount = response.get("amount")
        response_currency = response.get("currency")
        try:
            parsed_amount = int(response_amount)
        except (TypeError, ValueError) as exc:
            raise PaymentGatewayError("Stripe response amount was missing or invalid") from exc
        if parsed_amount != amount or str(response_currency).upper() != currency:
            raise PaymentGatewayError("Stripe response amount/currency did not match request")
