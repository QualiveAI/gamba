from locust import HttpUser, between, task


class GameUser(HttpUser):
    wait_time = between(1, 3)

    @task(3)
    def open_case(self):
        self.client.post("/games/cases/session", headers={"X-Tenant": "default"})

    @task(1)
    def deposit(self):
        self.client.post("/deposits", json={"rail": "pix", "amount_minor": 100, "currency": "BRL"})

    @task(1)
    def withdraw(self):
        self.client.post(
            "/withdrawals", json={"amount_minor": 10, "currency": "units", "channel": "giftcard"}
        )
