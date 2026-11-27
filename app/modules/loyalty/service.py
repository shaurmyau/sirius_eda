"""Сервис чтения баланса и уровня лояльности."""
from decimal import Decimal

from app.modules.loyalty.repository import LoyaltyRepository

TIER_PERCENTAGES = {"Bronze": Decimal("3"), "Silver": Decimal("5"), "Gold": Decimal("7")}


class LoyaltyService:
    def __init__(self, repository: LoyaltyRepository):
        self.repository = repository

    def get_summary(self, user_id: int) -> dict:
        account = self.repository.get_or_create(user_id)
        return {
            "balance": str(account.balance),
            "total_earned": str(account.total_earned),
            "tier": account.tier,
            "earn_percent": str(TIER_PERCENTAGES.get(account.tier, Decimal("3"))),
        }
