import pytest
from wavecast.text_identity import canonical_name, same_catalog_name


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("久石让", "久石譲"),  # Simplified vs Japanese shinjitai
        ("久石让", "久石讓"),  # Simplified vs Traditional
        ("久石讓", "久石譲"),  # Traditional vs Japanese shinjitai
        ("东京事变", "東京事変"),
        ("现实を嗤う", "現実を嗤う"),
        ("Joe Hisaishi", "  joe   hisaishi "),
        ("３ｒｄ Coast", "3rd Coast"),  # full-width forms
    ],
)
def test_script_variants_and_spacing_are_the_same_name(left: str, right: str) -> None:
    assert same_catalog_name(left, right)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ("久石譲", "宇多田ヒカル"),
        ("Jealousy", "Jealousy (Live)"),
        ("罪と罰", "罪と罰 (Remix)"),
        ("椎名林檎", "東京事変"),
        ("Bill Evans", "Bill Evans Trio"),
    ],
)
def test_different_names_and_version_labels_stay_distinct(left: str, right: str) -> None:
    assert not same_catalog_name(left, right)


def test_canonical_name_is_only_a_comparison_key() -> None:
    original = "久石譲"
    canonical_name(original)
    assert original == "久石譲"
    assert canonical_name(original) == canonical_name("久石让")
