from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select

from bot.database.models import User, Operations
from bot.database.models.main import PromoCodes, PromoCodeUsages
from bot.database import Database
from bot.database.methods.read import invalidate_user_cache, invalidate_stats_cache, promo_rule_error
from bot.database.methods.cache_utils import safe_create_task
from bot.database.methods.audit import log_audit

# Canonical promo error code (from promo_rule_error) -> user-facing key.
_REDEEM_PROMO_ERRORS = {
    "not_found": "promo.not_found",
    "inactive": "promo.inactive",
    "wrong_type": "promo.not_balance_type",
    "expired": "promo.expired",
    "max_uses": "promo.max_uses_reached",
    "already_used": "promo.already_used",
}


class _Abort(Exception):
    """Abort the current transaction with a user-facing failure code."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


async def admin_balance_change(telegram_id: int, amount: Decimal) -> tuple[bool, str]:
    """
    Atomic admin balance change (top-up or deduction) with operation record.
    amount > 0 for top-up, amount < 0 for deduction.
    Returns (success, message).
    """
    try:
        async with Database().session() as s:
            user = (await s.execute(
                select(User).where(User.telegram_id == telegram_id).with_for_update()
            )).scalars().one_or_none()

            if not user:
                raise _Abort("user_not_found")

            if amount < 0 and user.balance < abs(amount):
                raise _Abort("insufficient_funds")

            user.balance += amount

            operation = Operations(
                user_id=telegram_id,
                operation_value=amount,
                operation_time=datetime.now(timezone.utc)
            )
            s.add(operation)

    except _Abort as e:
        return False, e.code

    except Exception as e:
        await log_audit(
            "admin_balance_change_failed",
            level="WARNING",
            user_id=telegram_id,
            resource_type="User",
            details=f"amount={amount}, error={e}",
        )
        return False, "balance_change_error"

    safe_create_task(invalidate_user_cache(telegram_id))
    safe_create_task(invalidate_stats_cache())

    return True, "success"


async def redeem_balance_promo(code: str, user_id: int) -> tuple[bool, str, Decimal | None]:
    """
    Redeem a balance-type promo code: add discount_value to user balance.
    Returns (success, error_key_or_empty, amount_added).
    """
    try:
        async with Database().session() as s:
            user = (await s.execute(
                select(User).where(User.telegram_id == user_id).with_for_update()
            )).scalars().one_or_none()
            if not user:
                raise _Abort("promo.not_found")

            promo = (await s.execute(
                select(PromoCodes).where(PromoCodes.code == code.upper()).with_for_update()
            )).scalars().first()

            err = await promo_rule_error(s, promo, user_id, require_balance=True)
            if err:
                raise _Abort(_REDEEM_PROMO_ERRORS[err])

            amount = Decimal(str(promo.discount_value))
            user.balance += amount
            promo.current_uses += 1
            s.add(PromoCodeUsages(promo_id=promo.id, user_id=user_id))
            s.add(Operations(
                user_id=user_id,
                operation_value=amount,
                operation_time=datetime.now(timezone.utc),
            ))

    except _Abort as e:
        return False, e.code, None

    except Exception as e:
        await log_audit(
            "promo_redeem_failed",
            level="WARNING",
            user_id=user_id,
            resource_type="PromoCode",
            resource_id=code,
            details=str(e),
        )
        return False, "errors.something_wrong", None

    safe_create_task(invalidate_user_cache(user_id))
    safe_create_task(invalidate_stats_cache())
    return True, "", amount
