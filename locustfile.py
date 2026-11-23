"""Locust workload for the public menu and authenticated order path.

Read-only traffic works without a token. Set LOCUST_TOKEN to include order
creation in the workload (the token owner needs a funded balance).
"""
import os

from locust import HttpUser, between, task

WAIT_MIN = float(os.getenv("WAIT_MIN", "0.05"))
WAIT_MAX = float(os.getenv("WAIT_MAX", "0.15"))
ITEM_ID = int(os.getenv("LOCUST_ITEM_ID", "1"))
TOKEN = os.getenv("LOCUST_TOKEN", "").strip()


class SiriusFoodUser(HttpUser):
    wait_time = between(WAIT_MIN, WAIT_MAX)

    @task(7)
    def get_menu(self):
        self.client.get("/menu/items", name="GET /menu/items")

    @task(2)
    def get_menu_category(self):
        self.client.get("/menu/categories/food", name="GET /menu/categories/{category}")

    @task(1)
    def get_menu_item(self):
        self.client.get(f"/menu/items/{ITEM_ID}", name="GET /menu/items/{item_id}")

    @task(1)
    def create_order(self):
        if not TOKEN:
            return
        self.client.post(
            "/orders/create",
            name="POST /orders/create",
            headers={"Authorization": f"Bearer {TOKEN}"},
            json={"item_id": ITEM_ID, "quantity": 1},
        )
