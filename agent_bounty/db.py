from __future__ import annotations

import sqlite3
from pathlib import Path


SCHEMA_VERSION = 3


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    init_db(conn)
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '3');

        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS treasuries (
            project_id TEXT PRIMARY KEY REFERENCES projects(id),
            currency TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS budget_policies (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            max_bounty_amount INTEGER NOT NULL CHECK(max_bounty_amount >= 0),
            monthly_budget INTEGER NOT NULL CHECK(monthly_budget >= 0),
            human_approval_threshold INTEGER NOT NULL CHECK(human_approval_threshold >= 0),
            allowed_issue_classes_json TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS funding_events (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            amount INTEGER NOT NULL CHECK(amount > 0),
            currency TEXT NOT NULL,
            gateway_event_id TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bounties (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL REFERENCES projects(id),
            title TEXT NOT NULL,
            reward_amount INTEGER NOT NULL CHECK(reward_amount > 0),
            currency TEXT NOT NULL,
            state TEXT NOT NULL,
            base_commit TEXT NOT NULL,
            issue_ref TEXT NOT NULL,
            verifier_id TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            reserve_idempotency_key TEXT UNIQUE,
            accepted_receipt_id TEXT
        );

        CREATE TABLE IF NOT EXISTS state_events (
            id TEXT PRIMARY KEY,
            bounty_id TEXT NOT NULL REFERENCES bounties(id),
            from_state TEXT,
            to_state TEXT NOT NULL,
            reason TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(bounty_id, idempotency_key, to_state)
        );

        CREATE TABLE IF NOT EXISTS solver_identities (
            id TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            beneficiary_external_id TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY,
            bounty_id TEXT NOT NULL REFERENCES bounties(id),
            solver_id TEXT NOT NULL REFERENCES solver_identities(id),
            status TEXT NOT NULL,
            lease_expires_at TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS one_active_claim_per_bounty
            ON claims(bounty_id)
            WHERE status = 'active';

        CREATE TABLE IF NOT EXISTS submissions (
            id TEXT PRIMARY KEY,
            bounty_id TEXT NOT NULL REFERENCES bounties(id),
            claim_id TEXT NOT NULL REFERENCES claims(id),
            solver_id TEXT NOT NULL REFERENCES solver_identities(id),
            candidate_commit TEXT NOT NULL,
            candidate_repo_path TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS verification_runs (
            id TEXT PRIMARY KEY,
            bounty_id TEXT NOT NULL REFERENCES bounties(id),
            submission_id TEXT NOT NULL REFERENCES submissions(id),
            status TEXT NOT NULL,
            verifier_id TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT,
            stdout_sha256 TEXT,
            stderr_sha256 TEXT,
            result_json TEXT,
            backend TEXT,
            backend_digest TEXT,
            policy_digest TEXT,
            lease_expires_at TEXT,
            heartbeat_at TEXT,
            attempt INTEGER NOT NULL DEFAULT 1,
            idempotency_key TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS verification_receipts (
            id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE REFERENCES verification_runs(id),
            bounty_id TEXT NOT NULL REFERENCES bounties(id),
            project_id TEXT,
            issue_ref TEXT,
            submission_id TEXT,
            solver_id TEXT,
            candidate_repo_path TEXT,
            verifier_id TEXT,
            base_commit TEXT NOT NULL,
            candidate_commit TEXT NOT NULL,
            verifier_digest TEXT NOT NULL,
            backend TEXT,
            backend_digest TEXT,
            policy_digest TEXT,
            accepted INTEGER NOT NULL CHECK(accepted IN (0, 1)),
            metrics_json TEXT NOT NULL,
            stdout_sha256 TEXT NOT NULL,
            stderr_sha256 TEXT NOT NULL,
            started_at TEXT NOT NULL,
            finished_at TEXT NOT NULL,
            receipt_json TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS payouts (
            id TEXT PRIMARY KEY,
            bounty_id TEXT NOT NULL UNIQUE REFERENCES bounties(id),
            solver_id TEXT NOT NULL REFERENCES solver_identities(id),
            amount INTEGER NOT NULL CHECK(amount > 0),
            currency TEXT NOT NULL,
            status TEXT NOT NULL,
            gateway_payout_id TEXT,
            accepted_receipt_id TEXT REFERENCES verification_receipts(id),
            verifier_digest TEXT,
            idempotency_key TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS account_balances (
            account TEXT NOT NULL,
            currency TEXT NOT NULL,
            balance INTEGER NOT NULL DEFAULT 0,
            allow_negative INTEGER NOT NULL DEFAULT 0 CHECK(allow_negative IN (0, 1)),
            PRIMARY KEY(account, currency),
            CHECK(allow_negative = 1 OR balance >= 0)
        );

        CREATE TABLE IF NOT EXISTS ledger_entries (
            id TEXT PRIMARY KEY,
            event_type TEXT NOT NULL,
            idempotency_key TEXT NOT NULL UNIQUE,
            from_account TEXT NOT NULL,
            to_account TEXT NOT NULL,
            amount INTEGER NOT NULL CHECK(amount > 0),
            currency TEXT NOT NULL,
            project_id TEXT,
            bounty_id TEXT,
            solver_id TEXT,
            payout_id TEXT,
            external_id TEXT,
            created_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS one_receipt_per_candidate_verifier
            ON verification_receipts(bounty_id, candidate_commit, verifier_digest);
        """
    )
    _ensure_column(conn, "verification_receipts", "project_id", "TEXT")
    _ensure_column(conn, "verification_receipts", "issue_ref", "TEXT")
    _ensure_column(conn, "verification_receipts", "submission_id", "TEXT")
    _ensure_column(conn, "verification_receipts", "solver_id", "TEXT")
    _ensure_column(conn, "verification_receipts", "candidate_repo_path", "TEXT")
    _ensure_column(conn, "verification_receipts", "verifier_id", "TEXT")
    _ensure_column(conn, "verification_receipts", "backend", "TEXT")
    _ensure_column(conn, "verification_receipts", "backend_digest", "TEXT")
    _ensure_column(conn, "verification_receipts", "policy_digest", "TEXT")
    _ensure_column(conn, "verification_runs", "backend", "TEXT")
    _ensure_column(conn, "verification_runs", "backend_digest", "TEXT")
    _ensure_column(conn, "verification_runs", "policy_digest", "TEXT")
    _ensure_column(conn, "verification_runs", "lease_expires_at", "TEXT")
    _ensure_column(conn, "verification_runs", "heartbeat_at", "TEXT")
    _ensure_column(conn, "verification_runs", "attempt", "INTEGER NOT NULL DEFAULT 1")
    _ensure_column(conn, "payouts", "accepted_receipt_id", "TEXT")
    _ensure_column(conn, "payouts", "verifier_digest", "TEXT")
    conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(SCHEMA_VERSION),))
    conn.commit()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
