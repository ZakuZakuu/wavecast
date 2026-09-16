from wavecast.evals import RETRIEVAL_BENCHMARK_CASES, SYNTHETIC_RETRIEVAL_FIXTURES
from wavecast.providers.retrieval import VersionKind


def test_retrieval_benchmark_covers_long_tail_queries() -> None:
    queries = {case.query for case in RETRIEVAL_BENCHMARK_CASES}

    assert "3rd Coast - Jealousy" in queries
    assert "3rd Coast - Luv is True" in queries
    assert "Clazziquai Project" in queries
    assert "Persona 4 - Specialist" in queries


def test_synthetic_retrieval_fixtures_preserve_version_alternatives() -> None:
    assert len(SYNTHETIC_RETRIEVAL_FIXTURES) == 4
    assert sum(
        fixture.version_kind is VersionKind.UNKNOWN for fixture in SYNTHETIC_RETRIEVAL_FIXTURES
    ) == 2
    assert any(fixture.version_kind is VersionKind.LIVE for fixture in SYNTHETIC_RETRIEVAL_FIXTURES)
    assert any(fixture.version_kind is VersionKind.REMIX for fixture in SYNTHETIC_RETRIEVAL_FIXTURES)
