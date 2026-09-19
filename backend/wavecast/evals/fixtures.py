"""Credential-free Guided Discovery benchmark inputs.

Cases intentionally describe failure modes rather than prescribing exact tracks.  Evaluation
should reward musical reasoning, evidence discipline, and a coherent arc instead of memorization.
"""

from .quality import GuidedDiscoveryCase

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
