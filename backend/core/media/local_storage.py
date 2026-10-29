import hashlib
import io
import os

from PIL import Image

from core.media.storage import MediaRef


def validate_image(data: bytes) -> tuple[int, int, str]:
    if len(data) > 512 * 1024:
        raise ValueError("too large")  # noqa: B904
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
    except Exception:
        raise ValueError("not an image")  # noqa: B904
    # resize/convert
    img = img.convert("RGB")
    img.thumbnail((512, 512))
    buf = io.BytesIO()
    img.save(buf, format="WEBP")
    return img.width, img.height, "image/webp"


class LocalStorage:
    def __init__(self, base_dir: str = "./media"):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def put(self, data: bytes, content_type: str, owner: str) -> MediaRef:
        # validate
        w, h, ct = validate_image(data)
        # dedup by sha256
        sha = hashlib.sha256(data).hexdigest()
        # check DB? We'll handle dedup in API layer; storage just stores
        storage_key = sha + ".webp"
        path = os.path.join(self.base_dir, storage_key)
        if not os.path.exists(path):
            # convert and save webp
            img = Image.open(io.BytesIO(data))
            img = img.convert("RGB")
            img.thumbnail((512, 512))
            img.save(path, format="WEBP")
        # media_id assigned by DB; storage returns key in MediaRef with id 0 placeholder
        return MediaRef(0, storage_key, ct)

    def get(self, media_id: int):
        # not used directly; API resolves storage_key from DB
        return b"", "image/webp"

    def delete(self, media_id: int):
        pass
