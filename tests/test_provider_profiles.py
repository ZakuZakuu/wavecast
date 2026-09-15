from wavecast.providers.profiles import InferenceProfile, StructuredTransport, policy_for


def test_fast_profile_is_responses_json_schema_without_thinking() -> None:
    policy = policy_for(
        InferenceProfile.FAST,
        default_timeout_seconds=20,
        default_max_output_tokens=4096,
        default_max_attempts=2,
    )

    assert policy.transport is StructuredTransport.RESPONSES_JSON_SCHEMA
    assert policy.timeout_seconds == 15
    assert policy.max_output_tokens == 2048
    assert policy.max_attempts == 1
    assert policy.reasoning_effort == "none"


def test_balanced_and_deep_profiles_keep_background_retry_and_reasoning_separate() -> None:
    balanced = policy_for(
        InferenceProfile.BALANCED,
        default_timeout_seconds=20,
        default_max_output_tokens=4096,
        default_max_attempts=2,
    )
    deep = policy_for(
        InferenceProfile.DEEP,
        default_timeout_seconds=20,
        deep_timeout_seconds=45,
        default_max_output_tokens=4096,
        default_max_attempts=2,
    )

    assert balanced.reasoning_effort == "low"
    assert balanced.max_output_tokens == 4096
    assert balanced.max_attempts == 2
    assert deep.reasoning_effort == "high"
    assert deep.max_output_tokens == 8192
    assert deep.max_attempts == 2
    assert deep.timeout_seconds == 45
