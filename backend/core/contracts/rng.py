from typing import Protocol, runtime_checkable


@runtime_checkable
class RngProvider(Protocol):
    def roll(self, server_seed: str, client_seed: str, nonce: int) -> float: ...
