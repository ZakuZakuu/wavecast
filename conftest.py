import pytest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-live",
        action="store_true",
        default=False,
        help="run explicitly opted-in tests that make paid provider API calls",
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    if config.getoption("--run-live"):
        return
    skip_live = pytest.mark.skip(reason="live provider tests require explicit --run-live opt-in")
    for item in items:
        if item.get_closest_marker("live"):
            item.add_marker(skip_live)
