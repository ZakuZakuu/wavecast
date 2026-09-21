"""Credential-free Guided Discovery benchmark inputs.

Cases intentionally describe failure modes rather than prescribing exact tracks.  Evaluation
should reward musical reasoning, evidence discipline, and a coherent arc instead of memorization.
"""

from wavecast.intelligence.models import (
    NarrationSlotContext,
    NarrationSlotPlacement,
    RadioScriptBlockKind,
    ResolvedTrack,
)

from .quality import GuidedDiscoveryCase, RadioWritingCriterion, RadioWritingFixture
from .radio_writing import RadioWritingEvidenceMode, RadioWritingReviewExample

PHASE53C_RADIO_WRITING_REVIEW_EXAMPLES: tuple[RadioWritingReviewExample, ...] = (
    RadioWritingReviewExample(
        example_id="opening-empty-evidence",
        slot_context=NarrationSlotContext(
            slot_id="opening-after-track",
            chapter_index=0,
            placement=NarrationSlotPlacement.AFTER_TRACK,
            allowed_block_kinds=[RadioScriptBlockKind.INTRO],
            chapter_track=ResolvedTrack(
                track_ref="fixture:anchor",
                canonical_artist="Anchor Artist",
                canonical_title="Anchor Song",
            ),
            just_played_track=ResolvedTrack(
                track_ref="fixture:anchor",
                canonical_artist="Anchor Artist",
                canonical_title="Anchor Song",
            ),
            upcoming_track=ResolvedTrack(
                track_ref="fixture:bridge",
                canonical_artist="Bridge Artist",
                canonical_title="Bridge Song",
            ),
            is_opening=True,
        ),
        block_kind=RadioScriptBlockKind.INTRO,
        weak_text="这首歌来自一个重要时期，复杂的节奏和深刻的情感马上会带你进入今天的主题。",
        stronger_text="先从这首歌本身开始听。背景资料还不够时，我们先不替它下结论，等听见更多线索再往下走。",
        criteria=[
            RadioWritingCriterion.GROUNDED_INTERPRETATION,
            RadioWritingCriterion.ONE_SPOKEN_BEAT,
        ],
        evidence_mode=RadioWritingEvidenceMode.EMPTY,
        reviewer_note="无 evidence 时，stronger fixture 保持克制，不用具体音乐或事实断言填空。",
    ),
    RadioWritingReviewExample(
        example_id="opening-supported",
        slot_context=NarrationSlotContext(
            slot_id="opening-supported-after-track",
            chapter_index=0,
            placement=NarrationSlotPlacement.AFTER_TRACK,
            allowed_block_kinds=[RadioScriptBlockKind.INTRO],
            chapter_track=ResolvedTrack(
                track_ref="fixture:anchor",
                canonical_artist="Anchor Artist",
                canonical_title="Anchor Song",
            ),
            just_played_track=ResolvedTrack(
                track_ref="fixture:anchor",
                canonical_artist="Anchor Artist",
                canonical_title="Anchor Song",
            ),
            upcoming_track=ResolvedTrack(
                track_ref="fixture:bridge",
                canonical_artist="Bridge Artist",
                canonical_title="Bridge Song",
            ),
            is_opening=True,
        ),
        block_kind=RadioScriptBlockKind.INTRO,
        weak_text="我们先从一首很有氛围的歌开始，等下会聊到它为什么特别。",
        stronger_text="先听开头留下的那一小块空间：人声还没进来，鼓和 bass 已经把方向定住了。后面我们再看这种松紧怎样延伸。",
        criteria=[
            RadioWritingCriterion.CONCRETE_BEFORE_ABSTRACT,
            RadioWritingCriterion.LISTEN_FOR_CUE,
            RadioWritingCriterion.ONE_SPOKEN_BEAT,
        ],
        evidence_mode=RadioWritingEvidenceMode.SUPPORTED,
        reviewer_note="有 supporting evidence 时，opening 可以给一个短而可验证的 listen-for cue。",
    ),
    RadioWritingReviewExample(
        example_id="direct-track-intro",
        slot_context=NarrationSlotContext(
            slot_id="track-intro-a-to-b",
            chapter_index=1,
            placement=NarrationSlotPlacement.BEFORE_TRACK,
            allowed_block_kinds=[RadioScriptBlockKind.TRACK_INTRO],
            chapter_track=ResolvedTrack(
                track_ref="fixture:bridge",
                canonical_artist="Bridge Artist",
                canonical_title="Bridge Song",
            ),
            just_played_track=ResolvedTrack(
                track_ref="fixture:anchor",
                canonical_artist="Anchor Artist",
                canonical_title="Anchor Song",
            ),
            upcoming_track=ResolvedTrack(
                track_ref="fixture:bridge",
                canonical_artist="Bridge Artist",
                canonical_title="Bridge Song",
            ),
        ),
        block_kind=RadioScriptBlockKind.TRACK_INTRO,
        weak_text="接下来是 Bridge Song，希望你会喜欢。",
        stronger_text="刚才 Anchor Song 把人声放在拍子后面，下一首 Bridge Song 把这种松弛感交给更轻的鼓组；听听它怎样换一种方式稳住律动。",
        criteria=[
            RadioWritingCriterion.FACT_SOUND_CONNECTION,
            RadioWritingCriterion.CONTEXTUAL_DEIXIS,
            RadioWritingCriterion.LISTEN_FOR_CUE,
        ],
        evidence_mode=RadioWritingEvidenceMode.SUPPORTED,
        reviewer_note="direct A→B 的 stronger fixture 必须说明下一首为什么值得听，而不只是报歌名。",
    ),
    RadioWritingReviewExample(
        example_id="narrative-only-transition",
        slot_context=NarrationSlotContext(
            slot_id="narrative-only-middle",
            chapter_index=2,
            placement=NarrationSlotPlacement.AFTER_TRACK,
            allowed_block_kinds=[RadioScriptBlockKind.TRANSITION],
            just_played_track=ResolvedTrack(
                track_ref="fixture:bridge",
                canonical_artist="Bridge Artist",
                canonical_title="Bridge Song",
            ),
            upcoming_track=ResolvedTrack(
                track_ref="fixture:discovery",
                canonical_artist="Discovery Artist",
                canonical_title="Discovery Song",
            ),
        ),
        block_kind=RadioScriptBlockKind.TRANSITION,
        weak_text="刚才这首很有意思，下一首也会继续我们的音乐探索。",
        stronger_text="刚才 Bridge Song 用留白把律动放松下来，下一首 Discovery Song 会把同样的空间感推向更密的和声；你可以留意两首歌的鼓和人声谁先改变。",
        criteria=[
            RadioWritingCriterion.CONTEXTUAL_DEIXIS,
            RadioWritingCriterion.FACT_SOUND_CONNECTION,
            RadioWritingCriterion.ONE_SPOKEN_BEAT,
        ],
        evidence_mode=RadioWritingEvidenceMode.SUPPORTED,
        reviewer_note="这是 narrative-only middle transition：没有 chapter_track，只有真实的前后邻接。",
    ),
    RadioWritingReviewExample(
        example_id="final-outro",
        slot_context=NarrationSlotContext(
            slot_id="final-outro",
            chapter_index=3,
            placement=NarrationSlotPlacement.AFTER_FINAL_TRACK,
            allowed_block_kinds=[RadioScriptBlockKind.OUTRO],
            just_played_track=ResolvedTrack(
                track_ref="fixture:discovery",
                canonical_artist="Discovery Artist",
                canonical_title="Discovery Song",
            ),
            is_final=True,
        ),
        block_kind=RadioScriptBlockKind.OUTRO,
        weak_text="今天我们从熟悉的歌听到更广的音乐，希望你喜欢这期节目。",
        stronger_text="下次再听到人声稍微往后靠，不妨先别把它当成松散；也许正是鼓和 bass 在替它稳住方向。",
        criteria=[
            RadioWritingCriterion.OUTRO_CALLBACK,
            RadioWritingCriterion.NO_FORCED_CLEVERNESS,
        ],
        evidence_mode=RadioWritingEvidenceMode.SUPPORTED,
        reviewer_note="Outro 回扣前面真实听到的节奏细节，并留下一个可以带走的听法。",
    ),
)


PHASE53_RADIO_WRITING_FIXTURES: tuple[RadioWritingFixture, ...] = (
    RadioWritingFixture(
        fixture_id="cultural-precision",
        criterion=RadioWritingCriterion.CULTURAL_PRECISION,
        weak_text="这首歌让中文歌词承载了某族群音乐复杂而深厚的律动传统。",
        stronger_text="刚才副歌里，人声没有一直贴着正拍走；它稍微往后靠，bass 和鼓把这点松紧托住了。",
        rationale="把宽泛的族群化判断改成具体、可听的节奏观察。",
    ),
    RadioWritingFixture(
        fixture_id="listen-for-cue",
        criterion=RadioWritingCriterion.LISTEN_FOR_CUE,
        weak_text="这首歌的音乐性很丰富，情绪也很有层次。",
        stronger_text="留意第二遍副歌前鼓组怎么收窄；人声进来以后，空间反而被留得更开。",
        rationale="给听众一个可以在播放中验证的聆听线索。",
    ),
    RadioWritingFixture(
        fixture_id="one-spoken-beat",
        criterion=RadioWritingCriterion.ONE_SPOKEN_BEAT,
        weak_text="这首歌来自一个重要时期，它的编曲、歌词和演唱都体现了作者的成长，也影响了后来很多音乐人。",
        stronger_text="先听编曲怎么把空间留给人声。至于它为什么重要，我们下一段再接着说。",
        rationale="把多个解释动作拆成一个可说、可继续推进的旁白 beat。",
    ),
    RadioWritingFixture(
        fixture_id="outro-callback",
        criterion=RadioWritingCriterion.OUTRO_CALLBACK,
        weak_text="今天我们从熟悉的歌听到更广的音乐，希望你喜欢这期节目。",
        stronger_text="下次再听到那种稍微往后的唱腔，可以先别急着把它当成松散；也许正是鼓和 bass 在替它稳住方向。",
        rationale="Outro 回扣本期实际听到的细节，并留下可带走的听法。",
    ),
)


GUIDED_DISCOVERY_CASES: tuple[GuidedDiscoveryCase, ...] = (
    GuidedDiscoveryCase(
        case_id="third-coast-same-artist-trap",
        title="3rd Coast beyond the immediate cluster",
        topic="guided discovery around smooth urban lounge music",
        anchor_tracks=["3rd Coast - Jealousy", "3rd Coast - Luv is True"],
        failure_mode="same-artist and game-franchise repetition",
        expected_dimensions=["groove", "harmony", "production texture", "vocal interplay"],
    ),
    GuidedDiscoveryCase(
        case_id="persona-style-explanation",
        title="Game-music style without an OST-only list",
        topic="Persona P3/P4/P5 inspired guided discovery",
        anchor_tracks=["Persona 4 - Reach Out To The Truth"],
        failure_mode="confusing soundtrack context with musical traits",
        expected_dimensions=["jazz harmony", "funk rhythm", "club production", "instrumentation"],
    ),
    GuidedDiscoveryCase(
        case_id="artist-to-scene-bridge",
        title="Artist to scene and era",
        topic="guided discovery from trip-hop into adjacent late-1990s production language",
        anchor_tracks=["Portishead - Glory Box"],
        failure_mode="shallow same-artist similarity",
        expected_dimensions=["harmonic language", "sampling", "vocal treatment", "era"],
    ),
    GuidedDiscoveryCase(
        case_id="late-night-city-drive",
        title="Relaxed but rhythmic night drive",
        topic="relaxed late-night city driving, rhythmic but not aggressive",
        anchor_artists=["Sade"],
        failure_mode="incoherent mood-playlist dumping",
        expected_dimensions=["tempo feel", "bass texture", "vocal intimacy", "emotional energy"],
    ),
)


PHASE51_EDITORIAL_CASES: tuple[GuidedDiscoveryCase, ...] = (
    GuidedDiscoveryCase(
        case_id="phase51-fang-datong-biography",
        title="\u65b9\u5927\u540c\uff1a\u4e00\u751f\u4e0e\u97f3\u4e50",
        topic="\u65b9\u5927\u540c\u7684\u4e00\u751f\u4e0e\u97f3\u4e50\uff1a\u4ece\u6210\u957f\u3001\u521b\u4f5c\u9053\u8def\u5230\u4e0d\u540c\u9636\u6bb5\u7684\u91cd\u8981\u4f5c\u54c1",
        anchor_artists=["\u65b9\u5927\u540c"],
        failure_mode="\u767e\u79d1\u5f0f\u751f\u6daf\u6d41\u6c34\u8d26\u6216\u53ea\u6309\u5e74\u4efd\u6392\u5217\u70ed\u95e8\u6b4c\u66f2",
        expected_dimensions=["biographical arc", "career stage", "musical development"],
        benchmark_kind="artist_biography",
    ),
    GuidedDiscoveryCase(
        case_id="phase51-fang-to-musiq-discovery",
        title="\u65b9\u5927\u540c to Musiq Soulchild: Soul / Neo-Soul / R&B discovery",
        topic="\u4ece\u65b9\u5927\u540c\u51fa\u53d1\uff0c\u89e3\u91ca\u4e3a\u4f55\u53ef\u4ee5\u8d70\u5230 Musiq Soulchild\uff0c\u518d\u63a2\u7d22\u66f4\u5e7f\u6cdb\u7684 Soul\u3001Neo-Soul \u4e0e R&B",
        anchor_artists=["\u65b9\u5927\u540c"],
        failure_mode="\u505c\u7559\u5728\u65b9\u5927\u540c\u672c\u5730\u5019\u9009\u6216\u7528\u65e0\u4f9d\u636e\u7684\u76f8\u4f3c\u6027\u786c\u8df3",
        expected_dimensions=["vocal phrasing", "rhythmic pocket", "neo-soul vocabulary", "R&B lineage"],
        benchmark_kind="deep_discovery",
        required_route_artists=["Musiq Soulchild"],
        minimum_distinct_artists=3,
    ),
    GuidedDiscoveryCase(
        case_id="phase51-uk-garage",
        title="UK Garage: \u4ece\u573a\u666f\u5230\u58f0\u97f3",
        topic="\u8bb2\u6e05\u695a UK Garage \u4ece\u54ea\u91cc\u6765\u3001\u662f\u4ec0\u4e48\u58f0\u97f3\u3001\u5173\u952e\u4eba\u7269\u548c\u4f5c\u54c1\u3001\u5982\u4f55\u53d1\u5c55\u4ee5\u53ca\u540e\u6765\u5f71\u54cd\u4e86\u4ec0\u4e48",
        failure_mode="\u6d41\u6d3e\u5b9a\u4e49\u52a0\u827a\u4eba\u540d\u5355\uff0c\u4f46\u542c\u5b8c\u4ecd\u542c\u4e0d\u61c2\u58f0\u97f3\u548c\u573a\u666f",
        expected_dimensions=["scene origin", "groove and rhythm", "club context", "substyles"],
        benchmark_kind="genre_scene",
    ),
    GuidedDiscoveryCase(
        case_id="phase51-chinese-rock-history",
        title="\u4e2d\u56fd\u6447\u6eda\uff1a\u4ece\u65e9\u671f\u5230\u73b0\u5728",
        topic="\u4e2d\u56fd\u6447\u6eda\u4ece\u65e9\u671f\u53d1\u5c55\u5230\u4eca\u5929\uff1a\u91cd\u8981\u9636\u6bb5\u3001\u4ee3\u8868\u4f5c\u54c1\u3001\u58f0\u97f3\u53d8\u5316\u548c\u65f6\u4ee3\u80cc\u666f",
        failure_mode="\u51e0\u5341\u5e74\u5927\u4e8b\u8bb0\u52a0\u64ad\u653e\u5217\u8868\uff0c\u7f3a\u5c11\u65f6\u4ee3\u4e4b\u95f4\u7684\u8fde\u7eed\u4e0e\u65ad\u88c2",
        expected_dimensions=["era segmentation", "scene context", "sound change", "industry context"],
        benchmark_kind="longitudinal_history",
    ),
)
