import hashlib
import hmac


class ProvablyFairRNG:
    def __init__(self, server_seed: str, client_seed: str, nonce: int):
        self.server_seed = server_seed
        self.client_seed = client_seed
        self.nonce = nonce

    def roll(self) -> float:
        msg = f"{self.client_seed}:{self.nonce}".encode()
        h = hmac.new(self.server_seed.encode(), msg, hashlib.sha256).hexdigest()
        val = int(h[:13], 16)
        return val / (2**52)

    @staticmethod
    def server_seed_hash(server_seed: str) -> str:
        return hashlib.sha256(server_seed.encode()).hexdigest()

    @staticmethod
    def verify(server_seed: str, client_seed: str, nonce: int, roll: float) -> bool:
        try:
            return ProvablyFairRNG(server_seed, client_seed, nonce).roll() == roll
        except Exception:
            return False
