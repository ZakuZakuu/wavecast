import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "live_curation_eval.py"
_SPEC = importlib.util.spec_from_file_location("live_curation_eval", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
live_curation_eval = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(live_curation_eval)


@pytest.mark.parametrize(
    "arguments",
    [
        ["--case", "phase51-fang-to-musiq-discovery"],
        ["--suite", "phase51", "--case", "guided-discovery-3rd-coast"],
    ],
)
def test_parse_args_rejects_suite_case_mismatch(
    monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    monkeypatch.setattr(sys, "argv", ["live_curation_eval.py", *arguments])
    with pytest.raises(SystemExit) as exc_info:
        live_curation_eval.parse_args()
    assert exc_info.value.code == 2
