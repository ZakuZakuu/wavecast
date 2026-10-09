import pytest
from wavecast.narration_quality import (
    check_block,
    estimate_seconds,
    opener_of,
    summarize,
)
from wavecast.spoken_form import KnownTrack


def issues(text: str, **kwargs) -> list[str]:
    return check_block(text, **kwargs).issues


def test_plain_factual_copy_has_no_ai_flavour() -> None:
    check = check_block("Sparkle 是 1982 年《FOR YOU》的第一首。接下来是 Jody，节奏慢一点。")

    assert check.issues == []
    assert check.figurative_hits == []
    assert not check.ai_flavoured


@pytest.mark.parametrize(
    "text",
    [
        "吉他一层层叠上来，旋律慢慢铺开。",
        "他把那股劲收了起来，换成夜色里的光泽。",
        "低音弦沉下去，音符之间留着呼吸。",
    ],
)
def test_stock_figurative_phrases_are_found(text: str) -> None:
    check = check_block(text)

    assert check.figurative_hits
    assert check.ai_flavoured


@pytest.mark.parametrize(
    ("text", "issue"),
    [
        ("这不是风格的断裂，而是同一支乐队换了手法。", "contrast_frame"),
        ("与其说是怀旧，不如说是重新发现。", "contrast_frame"),
        ("这也提醒我们，同一首歌有很多面。", "moralising"),
        ("鼓、贝斯、吉他一起往前推。", "parallel_list"),
        ("好了，下期再见。", "podcast_talk"),
        ("资料显示这首歌录于东京。", "evidence_talk"),
        ("我小时候第一次听到这首歌。", "personal_experience"),
    ],
)
def test_pattern_issues(text: str, issue: str) -> None:
    assert issue in issues(text)


def test_a_block_much_longer_than_its_window_is_flagged() -> None:
    long_text = "这首歌" + "的故事很长" * 40

    assert any(i.startswith("too_long") for i in issues(long_text, window_seconds=10))
    assert not any(i.startswith("too_long") for i in issues("很短的一句。", window_seconds=10))


def test_estimated_seconds_ignore_punctuation() -> None:
    assert estimate_seconds("你好，世界。", 4) == 1.0


def test_english_words_cost_extra_time() -> None:
    plain = estimate_seconds("接下来是歌曲")
    mixed = estimate_seconds("接下来是 Take Me Somewhere Nice 歌曲")

    assert mixed == pytest.approx(plain + 4 * 0.6)


def test_an_unreadable_name_is_reported_unless_the_track_is_known() -> None:
    text = "接下来是《もののけ姫》。"

    assert "unspeakable_script" in issues(text)
    assert "unspeakable_script" not in issues(
        text, tracks=[KnownTrack(artist="久石譲", title="もののけ姫")]
    )


def test_a_final_block_must_not_point_forward() -> None:
    assert "final_block_points_forward" in issues("下一首我们听点别的。", is_final=True)
    assert "final_block_points_forward" not in issues("下一首我们听点别的。", is_final=False)


def test_stock_openers_share_one_fingerprint() -> None:
    assert opener_of("刚才这首很安静。") == opener_of("刚才那段更热闹。") == "刚才"
    assert opener_of("Sparkle 放完了。") != opener_of("Jody 来了。")


def test_summary_measures_repetition_and_flavour() -> None:
    same = [check_block("刚才这首很好。"), check_block("刚才那首也好。"), check_block("接下来是下一首。")]
    varied = [check_block("Sparkle 放完了。"), check_block("1982 年的专辑。"), check_block("这位乐手也弹贝斯。")]

    assert summarize(same).most_common_opener == "刚才"
    assert summarize(same).most_common_opener_share == pytest.approx(2 / 3)
    assert summarize(varied).opener_diversity == 1.0
    assert summarize([check_block("一层层叠起来。")]).ai_flavour_rate == 1.0
    assert summarize([]).blocks == 0


def test_years_are_read_in_digits_and_in_chinese() -> None:
    from wavecast.narration_quality import years_in

    assert years_in("1982 年，一九九八年和 2005年") == {"1982", "1998", "2005"}
    assert years_in("第 1234 首") == set()  # not a year
    assert years_in("播放了 19800 次") == set()


def test_a_year_missing_from_the_evidence_is_flagged_only_when_the_set_is_given() -> None:
    assert "unsupported_year:1979" in issues("1979 年的歌", supported_years={"1980"})
    assert not any(i.startswith("unsupported_year") for i in issues("1980 年的歌", supported_years={"1980"}))
    assert not any(i.startswith("unsupported_year") for i in issues("1979 年的歌"))


def test_an_artist_that_is_planned_but_not_played_is_flagged_in_any_script_or_case() -> None:
    found = issues("下一首之前，先说说 Explosions In The Sky。", unplayed_names=["explosions in the sky"])

    assert "mentions_unplayed:explosions in the sky" in found
    assert "mentions_unplayed:久石譲" in issues("久石让写的。", unplayed_names=["久石譲"])  # script variant
    assert not any(i.startswith("mentions_unplayed") for i in issues("别的乐队。", unplayed_names=["Mogwai"]))
    assert not any(i.startswith("mentions_unplayed") for i in issues("很短。", unplayed_names=["a"]))


# --- phrases and repetition seen in live programmes (2026-10-09) ---------------------------


@pytest.mark.parametrize(
    "text",
    [
        "这首歌能一下子把后摇的张力立住。",
        "吉他和电子各站一边，中间留出空间。",
        "安静里慢慢有东西长出来。",
        "我想用这首歌来开始我们今天的后摇安静之旅。",
        "把步调放慢一点，给这段留点空白。",
        "几条线连上了。",
        "安静堆到临界，自己就散了。",
    ],
)
def test_abstract_stock_phrases_from_live_programmes_are_figurative_hits(text: str) -> None:
    from wavecast.narration_quality import check_block, rewrite_reasons

    assert rewrite_reasons(check_block(text))


def test_plain_factual_sentences_are_not_flagged_by_the_new_phrases() -> None:
    from wavecast.narration_quality import check_block, rewrite_reasons

    for text in (
        "Mogwai 是格拉斯哥的乐队。",
        "这首歌出自二〇〇一年的专辑。",
        "还是 Hammock，换成 Breathturn。",
    ):
        assert not rewrite_reasons(check_block(text))


ROUTE = ["Breathturn", "Take Me Somewhere Nice", "Your Hand in Mine", "Tape"]


def test_a_closing_block_that_lists_the_route_is_flagged() -> None:
    text = "从 Breathturn 到 Take Me Somewhere Nice，再到 Your Hand in Mine，今晚就到这儿。"

    assert "recap_list" in issues(text, is_final=True, route_titles=ROUTE)
    assert "recap_list" not in issues(
        "最后一首是 Your Hand in Mine，到这儿。", is_final=True, route_titles=ROUTE
    )
    assert "recap_list" not in issues(
        "从 Breathturn 到 Take Me Somewhere Nice，再到 Tape。", route_titles=ROUTE
    )  # only the closing block is held to this
    assert "recap_list" not in issues(text, is_final=True)


def test_a_sentence_that_repeats_an_earlier_one_is_flagged_even_if_reworded() -> None:
    earlier = "他们受访时说，早年开始做纯器乐，就是因为受了 Mogwai 很大的影响。"

    assert "repeats_earlier" in issues(
        "他们说过，早年做纯器乐是受了 Mogwai 的影响。", earlier=earlier
    )
    assert "repeats_earlier" in issues(earlier, earlier=earlier)
    assert "repeats_earlier" not in issues("他们来自德州，只用吉他和鼓。", earlier=earlier)
    assert "repeats_earlier" not in issues("早年做纯器乐是受了 Mogwai 的影响。")  # nothing earlier


def test_short_sentences_are_never_counted_as_repeats() -> None:
    assert "repeats_earlier" not in issues("今晚到这儿。", earlier="今晚到这儿。好的。")


def test_the_new_findings_are_worth_a_rewrite() -> None:
    from wavecast.narration_quality import check_block, rewrite_reasons

    recap = check_block(
        "Breathturn、Take Me Somewhere Nice 和 Your Hand in Mine。", is_final=True, route_titles=ROUTE
    )
    repeat = check_block("早年做纯器乐是受了 Mogwai 的影响。", earlier="早年做纯器乐是受了 Mogwai 的影响。")

    assert any("one by one" in reason for reason in rewrite_reasons(recap))
    assert any("already said" in reason for reason in rewrite_reasons(repeat))
