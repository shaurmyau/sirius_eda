import os
from locust import HttpUser, task, between

WAIT_MIN = float(os.getenv("WAIT_MIN", "0.05"))
WAIT_MAX = float(os.getenv("WAIT_MAX", "0.15"))

class MenuUser(HttpUser):
    wait_time = between(WAIT_MIN, WAIT_MAX)

    @task(3)
    def get_all_menu(self):
        self.client.get("/menu/items")

    @task(1)
    def get_category(self):
        self.client.get("/menu/categories/food")
