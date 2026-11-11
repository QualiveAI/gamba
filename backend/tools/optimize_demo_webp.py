"""Локальная оптимизация уже подготовленных demo WebP.

Скрипт не читает .env, не подключается к БД и не обращается к сети.
По умолчанию пишет во внешний staging-каталог; --in-place требует явного флага.
Альфа-канал сохраняется, RGB/RGBA изображения кодируются WebP quality=82.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

from PIL import Image


def encode(source: Path, quality: int) -> tuple[bytes, dict]:
    with Image.open(source) as image:
        image.load()
        source_mode = image.mode
        source_size = image.size
        source_alpha = image.getchannel("A").getextrema() if "A" in image.getbands() else None
        target = image.convert("RGBA" if source_alpha is not None else "RGB")
        output = io.BytesIO()
        target.save(output, format="WEBP", quality=quality, method=6)
    payload = output.getvalue()
    with Image.open(io.BytesIO(payload)) as check:
        check.load()
        if check.size != source_size:
            raise ValueError(f"Размер изменился: {source}")
        if source_alpha is not None and (
            "A" not in check.getbands() or check.getchannel("A").getextrema() != source_alpha
        ):
            raise ValueError(f"Альфа-канал изменился: {source}")
    return payload, {
        "mode": source_mode,
        "size": source_size,
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("frontend/assets/demo"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quality", type=int, default=82, choices=range(60, 96))
    parser.add_argument("--in-place", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve()
    output = args.output.resolve()
    if not source.is_dir() or output == source and not args.in_place:
        raise SystemExit("Нужен каталог source и отдельный output; --in-place требует явного флага")
    if output == source and not args.in_place:
        raise SystemExit("Output не может совпадать с source без --in-place")
    output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for item in sorted(source.glob("*.webp")):
        payload, meta = encode(item, args.quality)
        target = output / item.name
        target.write_bytes(payload)
        manifest.append(
            {
                "source": item.name,
                "target": target.name,
                "source_bytes": item.stat().st_size,
                "target_bytes": len(payload),
                **meta,
            }
        )
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    summary = {
        "files": len(manifest),
        "source_bytes": sum(x["source_bytes"] for x in manifest),
        "target_bytes": sum(x["target_bytes"] for x in manifest),
        "quality": args.quality,
        "output": str(output),
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
