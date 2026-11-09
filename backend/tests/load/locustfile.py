from locust import HttpUser, between, task


class GameUser(HttpUser):
    """Нагрузочный прогон по публичным чтениям (auth-зависимые записи требуют JWT)."""

    wait_time = between(1, 3)

    @task(3)
    def meta_games(self):
        self.client.get("/meta/games", headers={"X-Tenant": "default"})

    @task(2)
    def meta_geos(self):
        self.client.get("/meta/geos", headers={"X-Tenant": "default"})

    @task(2)
    def cases(self):
        self.client.get("/meta/cases", headers={"X-Tenant": "default"})
