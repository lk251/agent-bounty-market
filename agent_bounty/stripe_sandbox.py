from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from importlib import metadata
from typing import Any, Protocol

from .util import require_currency, require_positive_amount, sha256_text, stable_json


PINNED_STRIPE_PACKAGE = "15.2.0"
STRIPE_INTEGRATION_ENV = "AGENT_BOUNTY_STRIPE_SANDBOX"
STRIPE_REAL_RUN_ENV = "AGENT_BOUNTY_RUN_STRIPE_INTEGRATION"


class StripeSandboxError(RuntimeError):
    pass


class StripeClient(Protocol):
    def create_checkout_session(self, *, idempotency_key: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def retrieve_charge(self, charge_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def create_payment_intent(self, *, idempotency_key: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def retrieve_account(self, account_id: str | None = None) -> dict[str, Any]:
        raise NotImplementedError

    def create_transfer(self, *, idempotency_key: str, params: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def retrieve_transfer(self, transfer_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def construct_event(self, payload: bytes, signature_header: str, endpoint_secret: str) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class StripeSandboxConfig:
    enabled: bool
    secret_key: str | None
    webhook_secret: str | None
    connected_account_id: str | None
    platform_account_id: str | None
    public_base_url: str

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "StripeSandboxConfig":
        values = os.environ if env is None else env
        return cls(
            enabled=values.get(STRIPE_INTEGRATION_ENV) == "1",
            secret_key=values.get("STRIPE_TEST_SECRET_KEY") or None,
            webhook_secret=values.get("STRIPE_TEST_WEBHOOK_SECRET") or None,
            connected_account_id=values.get("STRIPE_TEST_CONNECTED_ACCOUNT_ID") or None,
            platform_account_id=values.get("STRIPE_TEST_PLATFORM_ACCOUNT_ID") or None,
            public_base_url=values.get("AGENT_BOUNTY_PUBLIC_BASE_URL", "http://127.0.0.1:4242").rstrip("/"),
        )

    def require_enabled(self) -> None:
        if not self.enabled:
            raise StripeSandboxError(f"set {STRIPE_INTEGRATION_ENV}=1 to enable Stripe sandbox integration")
        if not self.secret_key:
            raise StripeSandboxError("set STRIPE_TEST_SECRET_KEY to a sk_test_ or rk_test_ key")
        if not (self.secret_key.startswith("sk_test_") or self.secret_key.startswith("rk_test_")):
            raise StripeSandboxError("Stripe sandbox integration refuses live or non-test API keys")

    def require_webhook_secret(self) -> str:
        self.require_enabled()
        if not self.webhook_secret or not self.webhook_secret.startswith("whsec_"):
            raise StripeSandboxError("set STRIPE_TEST_WEBHOOK_SECRET to the whsec_ value from stripe listen")
        return self.webhook_secret


def request_digest(params: dict[str, Any]) -> str:
    return sha256_text(stable_json(params))


def safe_error_message(exc: BaseException) -> str:
    text = str(exc).replace("\n", " ").strip()
    for prefix in ("sk_test_", "rk_test_", "sk_live_", "rk_live_", "whsec_"):
        if prefix in text:
            text = text.split(prefix, 1)[0] + prefix + "..."
    return text[:400]


def stripe_package_version() -> str | None:
    try:
        return metadata.version("stripe")
    except metadata.PackageNotFoundError:
        return None


def stripe_cli_version() -> str | None:
    executable = shutil.which("stripe")
    if not executable:
        return None
    try:
        completed = subprocess.run([executable, "--version"], check=False, capture_output=True, text=True, timeout=5)
    except Exception:
        return "unavailable"
    output = (completed.stdout or completed.stderr).strip()
    return output or "available"


def ensure_test_object(obj: dict[str, Any], *, object_name: str) -> None:
    if obj.get("livemode") is not False:
        raise StripeSandboxError(f"{object_name} must be a test-mode Stripe object")


def require_id(obj: dict[str, Any], *, prefix: str, object_name: str) -> str:
    value = obj.get("id")
    if not isinstance(value, str) or not value.startswith(prefix):
        raise StripeSandboxError(f"{object_name} missing {prefix} id")
    ensure_test_object(obj, object_name=object_name)
    return value


def checkout_params(
    *,
    funding_request_id: str,
    project_id: str,
    source_kind: str,
    amount: int,
    currency: str,
    success_url: str,
    cancel_url: str,
) -> dict[str, Any]:
    require_positive_amount(amount)
    currency = require_currency(currency).lower()
    metadata = {
        "agent_bounty_kind": "project_funding",
        "funding_request_id": funding_request_id,
        "project_id": project_id,
        "source_kind": source_kind,
        "amount": str(amount),
        "currency": currency,
    }
    return {
        "mode": "payment",
        "payment_method_types": ["card"],
        "line_items": [
            {
                "price_data": {
                    "currency": currency,
                    "unit_amount": amount,
                    "product_data": {"name": f"Motoko project funding: {project_id}"},
                },
                "quantity": 1,
            }
        ],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "metadata": metadata,
        "payment_intent_data": {"metadata": dict(metadata)},
    }


def automated_payment_intent_params(
    *,
    funding_request_id: str,
    project_id: str,
    source_kind: str,
    amount: int,
    currency: str,
    payment_method: str,
) -> dict[str, Any]:
    require_positive_amount(amount)
    currency = require_currency(currency).lower()
    metadata = {
        "agent_bounty_kind": "project_funding",
        "funding_request_id": funding_request_id,
        "project_id": project_id,
        "source_kind": source_kind,
        "amount": str(amount),
        "currency": currency,
    }
    return {
        "amount": amount,
        "currency": currency,
        "payment_method": payment_method,
        "confirm": True,
        "error_on_requires_action": True,
        "metadata": metadata,
    }


def transfer_params(
    *,
    project_id: str,
    bounty_id: str,
    solver_id: str,
    payout_id: str,
    amount: int,
    currency: str,
    destination_account_id: str,
    accepted_receipt_id: str,
    candidate_sha: str,
    verifier_digest: str,
    backend_digest: str,
    policy_digest: str,
) -> dict[str, Any]:
    require_positive_amount(amount)
    currency = require_currency(currency).lower()
    transfer_group = f"bounty:{bounty_id}"
    metadata = {
        "agent_bounty_kind": "solver_transfer",
        "project_id": project_id,
        "bounty_id": bounty_id,
        "solver_id": solver_id,
        "payout_id": payout_id,
        "receipt_id": accepted_receipt_id,
        "candidate_sha": candidate_sha,
        "verifier_digest": verifier_digest[:120],
        "backend_digest": backend_digest[:120],
        "policy_digest": policy_digest[:120],
    }
    return {
        "amount": amount,
        "currency": currency,
        "destination": destination_account_id,
        "transfer_group": transfer_group,
        "metadata": metadata,
    }


class OfficialStripeClient:
    def __init__(self, config: StripeSandboxConfig):
        config.require_enabled()
        self.config = config
        try:
            import stripe  # type: ignore[import-not-found]
        except ImportError as exc:
            raise StripeSandboxError(
                f"install optional Stripe dependency: stripe=={PINNED_STRIPE_PACKAGE}"
            ) from exc
        self.stripe = stripe
        self.stripe.api_key = config.secret_key

    def create_checkout_session(self, *, idempotency_key: str, params: dict[str, Any]) -> dict[str, Any]:
        return _stripe_object_to_dict(
            self.stripe.checkout.Session.create(
                **params,
                idempotency_key=idempotency_key,
            )
        )

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        return _stripe_object_to_dict(
            self.stripe.checkout.Session.retrieve(
                session_id,
                expand=["payment_intent", "payment_intent.latest_charge"],
            )
        )

    def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        return _stripe_object_to_dict(
            self.stripe.PaymentIntent.retrieve(payment_intent_id, expand=["latest_charge"])
        )

    def retrieve_charge(self, charge_id: str) -> dict[str, Any]:
        return _stripe_object_to_dict(self.stripe.Charge.retrieve(charge_id))

    def create_payment_intent(self, *, idempotency_key: str, params: dict[str, Any]) -> dict[str, Any]:
        return _stripe_object_to_dict(
            self.stripe.PaymentIntent.create(
                **params,
                expand=["latest_charge"],
                idempotency_key=idempotency_key,
            )
        )

    def retrieve_account(self, account_id: str | None = None) -> dict[str, Any]:
        if account_id:
            return _stripe_object_to_dict(self.stripe.Account.retrieve(account_id))
        return _stripe_object_to_dict(self.stripe.Account.retrieve())

    def create_transfer(self, *, idempotency_key: str, params: dict[str, Any]) -> dict[str, Any]:
        return _stripe_object_to_dict(
            self.stripe.Transfer.create(
                **params,
                idempotency_key=idempotency_key,
            )
        )

    def retrieve_transfer(self, transfer_id: str) -> dict[str, Any]:
        return _stripe_object_to_dict(self.stripe.Transfer.retrieve(transfer_id))

    def construct_event(self, payload: bytes, signature_header: str, endpoint_secret: str) -> dict[str, Any]:
        event = self.stripe.Webhook.construct_event(payload, signature_header, endpoint_secret)
        return _stripe_object_to_dict(event)


class FakeStripeClient:
    def __init__(self):
        self.checkout_sessions: dict[str, dict[str, Any]] = {}
        self.payment_intents: dict[str, dict[str, Any]] = {}
        self.accounts: dict[str, dict[str, Any]] = {}
        self.transfers: dict[str, dict[str, Any]] = {}
        self.created_checkout_params: list[dict[str, Any]] = []
        self.created_payment_intent_params: list[dict[str, Any]] = []
        self.created_transfer_params: list[dict[str, Any]] = []
        self.fail_next_transfer: str | None = None
        self.platform_account = {"id": "acct_platform_test", "object": "account", "livemode": False, "country": "US"}

    @staticmethod
    def _fake_id(prefix: str, key: str) -> str:
        return f"{prefix}_{sha256_text(key).split(':', 1)[1][:24]}"

    def create_checkout_session(self, *, idempotency_key: str, params: dict[str, Any]) -> dict[str, Any]:
        self.created_checkout_params.append({"idempotency_key": idempotency_key, "params": params})
        session_id = self._fake_id("cs_test", idempotency_key)
        existing = self.checkout_sessions.get(session_id)
        if existing:
            return dict(existing)
        amount = int(params["line_items"][0]["price_data"]["unit_amount"])
        currency = str(params["line_items"][0]["price_data"]["currency"])
        metadata = dict(params["metadata"])
        payment_intent_id = self._fake_id("pi_test", idempotency_key)
        charge_id = self._fake_id("ch_test", idempotency_key)
        payment_intent = {
            "id": payment_intent_id,
            "object": "payment_intent",
            "livemode": False,
            "amount": amount,
            "amount_received": amount,
            "currency": currency,
            "status": "succeeded",
            "metadata": metadata,
            "latest_charge": {"id": charge_id, "object": "charge", "livemode": False},
        }
        session = {
            "id": session_id,
            "object": "checkout.session",
            "livemode": False,
            "payment_status": "unpaid",
            "amount_total": amount,
            "currency": currency,
            "metadata": metadata,
            "payment_intent": payment_intent_id,
            "url": f"https://checkout.stripe.test/{session_id}",
        }
        self.payment_intents[payment_intent_id] = payment_intent
        self.checkout_sessions[session_id] = session
        return dict(session)

    def retrieve_checkout_session(self, session_id: str) -> dict[str, Any]:
        session = dict(self.checkout_sessions[session_id])
        pi_id = session.get("payment_intent")
        if isinstance(pi_id, str) and pi_id in self.payment_intents:
            session["payment_intent"] = dict(self.payment_intents[pi_id])
            session["payment_status"] = "paid"
        return session

    def retrieve_payment_intent(self, payment_intent_id: str) -> dict[str, Any]:
        return dict(self.payment_intents[payment_intent_id])

    def retrieve_charge(self, charge_id: str) -> dict[str, Any]:
        for payment_intent in self.payment_intents.values():
            latest_charge = payment_intent.get("latest_charge")
            if isinstance(latest_charge, dict) and latest_charge.get("id") == charge_id:
                return {
                    "id": charge_id,
                    "object": "charge",
                    "livemode": False,
                    "amount": payment_intent["amount"],
                    "currency": payment_intent["currency"],
                    "payment_intent": payment_intent["id"],
                }
        return {"id": charge_id, "object": "charge", "livemode": False}

    def create_payment_intent(self, *, idempotency_key: str, params: dict[str, Any]) -> dict[str, Any]:
        self.created_payment_intent_params.append({"idempotency_key": idempotency_key, "params": params})
        payment_intent_id = self._fake_id("pi_test", idempotency_key)
        existing = self.payment_intents.get(payment_intent_id)
        if existing:
            return dict(existing)
        charge_id = self._fake_id("ch_test", idempotency_key)
        payment_intent = {
            "id": payment_intent_id,
            "object": "payment_intent",
            "livemode": False,
            "amount": int(params["amount"]),
            "amount_received": int(params["amount"]),
            "currency": params["currency"],
            "status": "succeeded",
            "metadata": dict(params["metadata"]),
            "latest_charge": {"id": charge_id, "object": "charge", "livemode": False},
        }
        self.payment_intents[payment_intent_id] = payment_intent
        return dict(payment_intent)

    def retrieve_account(self, account_id: str | None = None) -> dict[str, Any]:
        if not account_id:
            return dict(self.platform_account)
        return dict(self.accounts.get(account_id, {"id": account_id, "object": "account", "livemode": False, "country": "US", "charges_enabled": True, "payouts_enabled": True}))

    def create_transfer(self, *, idempotency_key: str, params: dict[str, Any]) -> dict[str, Any]:
        self.created_transfer_params.append({"idempotency_key": idempotency_key, "params": params})
        if self.fail_next_transfer:
            message = self.fail_next_transfer
            self.fail_next_transfer = None
            raise StripeSandboxError(message)
        transfer_id = self._fake_id("tr_test", idempotency_key)
        existing = self.transfers.get(transfer_id)
        if existing:
            return dict(existing)
        transfer = {
            "id": transfer_id,
            "object": "transfer",
            "livemode": False,
            "amount": int(params["amount"]),
            "currency": params["currency"],
            "destination": params["destination"],
            "transfer_group": params["transfer_group"],
            "metadata": dict(params["metadata"]),
        }
        self.transfers[transfer_id] = transfer
        return dict(transfer)

    def retrieve_transfer(self, transfer_id: str) -> dict[str, Any]:
        return dict(self.transfers[transfer_id])

    def construct_event(self, payload: bytes, signature_header: str, endpoint_secret: str) -> dict[str, Any]:
        from .stripe_webhooks import verify_stripe_signature

        verify_stripe_signature(payload=payload, signature_header=signature_header, endpoint_secret=endpoint_secret)
        parsed = json.loads(payload.decode("utf-8"))
        if not isinstance(parsed, dict):
            raise StripeSandboxError("fake Stripe event payload must be an object")
        return parsed


def _stripe_object_to_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "to_dict_recursive"):
        return value.to_dict_recursive()
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        return value.to_dict()
    try:
        return json.loads(json.dumps(value))
    except TypeError as exc:
        raise StripeSandboxError("Stripe SDK returned an unsupported object") from exc
