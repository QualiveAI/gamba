from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class MediaRef:
    media_id: int
    storage_key: str
    content_type: str


@runtime_checkable
class MediaStorage(Protocol):
    def put(self, data: bytes, content_type: str, owner: str) -> MediaRef: ...
    def get(self, media_id: int) -> tuple[bytes, str]: ...
    def delete(self, media_id: int) -> None: ...
