"""Wallet and Transaction document shapes (ADR-0006).

Interim policy (ADR-0007, deferred 2026-08-04): these are schema + cost-logging helpers only.
No balance-deduction, free-tier gating, or insufficient-balance enforcement belongs here until
ADR-0007 is resolved — building it now would be speculative work against an open ADR.
"""

import uuid
from datetime import UTC, datetime
from typing import Literal

TransactionType = Literal["credit", "debit"]
TransactionOperation = Literal[
    "generation",
    "humanization",
    "citation_verify",
    "plagiarism_check",
    "free_tier_grant",
    "purchase",
]


def new_wallet_document(user_id: str) -> dict:
    """Build a zeroed Wallet document for a newly registered user.

    Output matches ADR-0006's Wallet schema: `token_balance` and `free_pages_used_today` start
    at 0; `free_pages_reset_at` starts at now (UTC).
    """
    return {
        "id": str(uuid.uuid4()),
        "user_id": user_id,
        "token_balance": 0,
        "free_pages_used_today": 0,
        "free_pages_reset_at": datetime.now(UTC),
    }


def new_transaction_document(
    wallet_id: str,
    type_: TransactionType,
    amount_tokens: int,
    operation: TransactionOperation,
    reference_id: str | None = None,
    deepseek_cost_usd: float | None = None,
) -> dict:
    """Build a Transaction document logging one billing-relevant operation.

    Cost-logging only, per ADR-0007's interim policy: callers must not use this to gate or
    deduct anything — it exists so `deepseek_cost_usd` data accumulates for ADR #7 later.
    """
    return {
        "id": str(uuid.uuid4()),
        "wallet_id": wallet_id,
        "type": type_,
        "amount_tokens": amount_tokens,
        "operation": operation,
        "reference_id": reference_id,
        "deepseek_cost_usd": deepseek_cost_usd,
        "created_at": datetime.now(UTC),
    }
