import pytest
from wavecast.publishing import (
    GENERATION_RESERVE_BYTES,
    MAX_CONCURRENT_MIXES,
    MAX_PUBLISHED_PER_OWNER,
    MIX_SCRATCH_BYTES,
    PublishRefusal,
    check_publish_admission,
    estimated_audio_bytes,
    is_publication_id,
    new_publication_id,
    published_budget_bytes,
    short_code,
)

GB = 1024**3


def admit(**changes):
    values = dict(
        duration_seconds=38 * 60, owner_live_count=0, mixing_count=0,
        pinned_bytes=0, budget_bytes=GB, free_bytes=GB,
    )
    values.update(changes)
    check_publish_admission(**values)


def refusal(**changes) -> str:
    with pytest.raises(PublishRefusal) as error:
        admit(**changes)
    return error.value.code


def test_ids_and_short_codes_tell_published_programmes_from_proposals() -> None:
    identifier = new_publication_id()
    assert is_publication_id(identifier)
    assert not is_publication_id("proposal-" + "a" * 32)
    assert identifier.removeprefix("pub-").startswith(short_code(identifier))
    assert len(short_code(identifier)) == 10


def test_a_programme_that_fits_is_admitted() -> None:
    admit()


def test_an_owner_cannot_keep_more_than_the_limit_published() -> None:
    admit(owner_live_count=MAX_PUBLISHED_PER_OWNER - 1)
    assert refusal(owner_live_count=MAX_PUBLISHED_PER_OWNER) == "limit"


def test_only_a_few_mixes_run_at_once() -> None:
    admit(mixing_count=MAX_CONCURRENT_MIXES - 1)
    assert refusal(mixing_count=MAX_CONCURRENT_MIXES) == "busy"


def test_bringing_back_kept_audio_needs_no_room_only_the_owners_limit() -> None:
    # A revoked programme shared again mixes and stores nothing: a full budget or disk cannot stop it.
    admit(reuses_audio=True, budget_bytes=0, pinned_bytes=GB, free_bytes=0, mixing_count=MAX_CONCURRENT_MIXES)
    assert refusal(reuses_audio=True, owner_live_count=MAX_PUBLISHED_PER_OWNER) == "limit"


def test_published_audio_has_a_budget() -> None:
    output = estimated_audio_bytes(38 * 60)
    admit(budget_bytes=output, pinned_bytes=0)
    assert refusal(budget_bytes=output + 10, pinned_bytes=11) == "space"


def test_generation_always_keeps_its_reserve() -> None:
    output = estimated_audio_bytes(38 * 60)
    needed = output + MIX_SCRATCH_BYTES + GENERATION_RESERVE_BYTES
    admit(free_bytes=needed)
    assert refusal(free_bytes=needed - 1) == "space"
    # Not knowing the free space does not block anyone.
    admit(free_bytes=None)


def test_the_budget_is_a_share_of_the_volume_unless_it_is_set() -> None:
    assert published_budget_bytes(500 * 1024 * 1024, None) == 250 * 1024 * 1024
    assert published_budget_bytes(500 * 1024 * 1024, 100) == 100
    assert published_budget_bytes(0, None) == 0
