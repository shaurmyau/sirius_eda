"""Сервис администрирования промокодов."""
from app.modules.promotions.repository import PromoCodeRepository
from app.modules.promotions.policy import utc_naive


class PromoCodeService:
    def __init__(self, repository: PromoCodeRepository):
        self.repository = repository

    def create(self, data: dict):
        values = dict(data)
        values["code"] = values["code"].strip().upper()
        if not values["code"]:
            raise ValueError("Код промокода не может быть пустым")
        values["valid_from"] = utc_naive(values["valid_from"])
        values["valid_until"] = utc_naive(values["valid_until"])
        if values["valid_until"] <= values["valid_from"]:
            raise ValueError("valid_until должен быть позже valid_from")
        if values["discount_type"] not in ("percent", "fixed"):
            raise ValueError("discount_type должен быть percent или fixed")
        if values["discount_type"] == "percent" and values["discount_value"] > 100:
            raise ValueError("Процент скидки не может превышать 100")
        if self.repository.get_by_code(values["code"]):
            raise ValueError("Промокод с таким кодом уже существует")
        return self.repository.create(**values)

    def list_all(self):
        return self.repository.list_all()
