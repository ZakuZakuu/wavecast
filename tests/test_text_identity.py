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


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("APPLE (feat. 椎名林檎)", "APPLE"),
        ("APPLE [ft. Someone]", "APPLE"),
        ("APPLE（featuring 椎名林檎）", "APPLE"),
        ("APPLE - feat. Someone", "APPLE"),
        ("APPLE (Live)", "APPLE (Live)"),  # a version label is not a feature credit
        ("Feat of Strength", "Feat of Strength"),
        ("(feat. Someone)", "(feat. Someone)"),  # never reduce a title to nothing
    ],
)
def test_without_feature_credit_only_removes_a_trailing_feature_credit(
    title: str, expected: str
) -> None:
    from wavecast.text_identity import without_feature_credit

    assert without_feature_credit(title) == expected


@pytest.mark.parametrize(
    ("left", "right", "same"),
    [
        ("Summer", "Summer (《菊次郎的夏天》钢琴版)", True),
        ("Summer", "Summer (Live) [Remastered]", True),
        ("APPLE (feat. 椎名林檎)", "APPLE", True),
        ("Summer", "Summer Rain", False),
        ("(Live)", "(Live)", True),  # a title that is only a group is kept as it is
        ("(Live)", "Live", False),
    ],
)
def test_base_title_key_ignores_every_trailing_descriptive_group(
    left: str, right: str, same: bool
) -> None:
    from wavecast.text_identity import base_title_key

    assert (base_title_key(left) == base_title_key(right)) is same
