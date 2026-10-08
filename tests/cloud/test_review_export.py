import runpy
from pathlib import Path

review_payload = runpy.run_path(str(Path('scripts/cloud/export-review.py')))['review_payload']


def test_review_keeps_product_copy_but_excludes_private_and_provider_fields():
    result = review_payload({
        'id': 'episode-01', 'listener_id': 'private', 'owner_user_id': 'private',
        'progressive_session': {'raw_response': 'private'},
        'segments': [{'id': 'n1', 'kind': 'NARRATION', 'narration_text': '这一首从这里开始。',
                      'tts_text': '这一首从这里开始。', 'audio_source_url': 'signed-secret',
                      'unexpected_secret': 'private'}],
    })
    assert result['segments'][0]['narration_text'] == '这一首从这里开始。'
    assert result['segments'][0]['tts_text'] == '这一首从这里开始。'
    assert set(result['episode']) == {'id'}
    assert 'audio_source_url' not in result['segments'][0]
    assert 'unexpected_secret' not in result['segments'][0]


def test_export_does_not_claim_planned_segments_are_ready_or_sum_mix_duration():
    result = review_payload({'segments': [
        {'state': 'PLANNED', 'planned_duration_seconds': 180},
        {'state': 'AUDIO_READY', 'actual_duration_seconds': 10},
    ]})
    assert result['segments'][0]['state'] == 'PLANNED'
    assert 'mix_duration_seconds' not in result
    assert result['limitations']
