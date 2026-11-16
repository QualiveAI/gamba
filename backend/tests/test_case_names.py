"""Имена кейсов: БД хранит уже переведённые PT-BR названия, а не пути обложек."""

from app.catalog_localization import case_name


def test_translated_name_passes_through():
    assert case_name("Caixa do Lixo", "assets/demo/cover-trash.webp") == "Caixa do Lixo"
    assert case_name("Brainrot", "assets/demo/cover-brainrot.webp") == "Brainrot"


def test_legacy_key_still_translates():
    assert case_name("trash", "fallback") == "Caixa do Lixo"
    assert case_name("mm2", "fallback") == "Murder Mystery 2"


def test_cover_path_is_never_returned_as_name():
    # Раньше промах по словарям возвращал fallback = путь обложки.
    for name, cover in (
        ("Caixa do Lixo", "assets/demo/cover-trash.webp"),
        ("Caixa Diária", "assets/demo/cover-daily.webp"),
        ("Pet Simulator 99", "assets/demo/cover-pets.webp"),
    ):
        resolved = case_name(name, cover)
        assert not resolved.startswith("assets/"), resolved
        assert resolved == name


def test_unknown_case_falls_back_to_given_name():
    # API передаёт fallback = имя из БД (не путь обложки) — см. app/api/cases.py.
    assert case_name("Algo Novo", "Algo Novo") == "Algo Novo"
    assert case_name("Algo Novo", "Algo Novo") != "assets/demo/cover-x.webp"
