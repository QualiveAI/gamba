import json
import re
from pathlib import Path

from PIL import Image

from app.catalog_localization import CASE_NAMES_PT_BR, case_name, item_name
from tools.seed_demo import CATALOG, fix_missing_images, translate


def test_demo_catalog_labels_are_pt_br():
    data = json.loads(CATALOG.read_text(encoding="utf-8"))
    labels = [item_name(item["name"]) for case in data["cases"] for item in case["items"]]
    assert len(labels) == 210
    assert all(label and re.search(r"[\u0400-\u04ff]", label) is None for label in labels)
    assert all(case_name(case["id"]) == CASE_NAMES_PT_BR[case["id"]] for case in data["cases"])
    assert translate("Фрукт (Kitsune)") == "Fruta (Kitsune)"
    assert translate("100k Монет") == "100 mil moedas"
    assert item_name("Cracked Egg") == "Ovo rachado"
    assert item_name("Uncommon Knife") == "Faca incomum"


def test_demo_catalog_has_decodable_cover_and_item_assets():
    root = Path(__file__).resolve().parents[2]
    data = json.loads(
        (root / "backend" / "tools" / "demo_catalog.json").read_text(encoding="utf-8")
    )
    image_root = root / "frontend" / "assets" / "demo"
    null_before = [
        item["asset"] for case in data["cases"] for item in case["items"] if not item.get("image")
    ]
    fix_missing_images(data)
    null_after = [
        item["asset"] for case in data["cases"] for item in case["items"] if not item.get("image")
    ]
    assert len(null_before) == 21
    assert null_after == []
    assert {"dti8", "garden9", "nights11", "pets7", "trash15"}.issubset(null_before)
    assert {"daily11", "daily13", "daily15"}.issubset(null_before)
    assert {"weekly6", "weekly7", "weekly8", "weekly10", "weekly11", "weekly15"}.issubset(
        null_before
    )
    assert {
        "monthly6",
        "monthly7",
        "monthly8",
        "monthly11",
        "monthly13",
        "monthly14",
        "monthly15",
    }.issubset(null_before)
    freebet_ids = {"trash", "daily", "weekly", "monthly"}
    case_counts = {}
    for case in data["cases"]:
        cover = root / "frontend" / case["cover"]
        assert cover.is_file(), (case["id"], str(cover))
        with Image.open(cover) as image:
            image.verify()
        resolved = []
        for item in case["items"]:
            asset = item["asset"]
            candidates = []
            if item.get("image"):
                candidates.append(root / "frontend" / item["image"])
            candidates.append(image_root / f"{asset}.webp")
            source_matches = sorted((root / "frontend" / "assets").glob(f"{asset}.*"))
            candidates.extend(source_matches)
            match = next((path for path in candidates if path.is_file()), None)
            assert match is not None, (case["id"], asset)
            with Image.open(match) as image:
                image.verify()
            resolved.append(asset)
        case_counts[case["id"]] = len(resolved)
    assert len(case_counts) == 14
    assert all(count == 15 for count in case_counts.values())
    assert all(case_counts[key] == 15 for key in freebet_ids)
