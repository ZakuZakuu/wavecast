"""Read an existing cloud-local episode without generating or sending provider requests."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


def review_payload(episode: dict) -> dict:
    fields = ('id', 'seed_id', 'title', 'topic', 'state', 'generation_mode',
              'program_estimated_duration_seconds', 'program_rendered_frontier_seconds')
    segment_fields = ('id', 'chapter_id', 'order', 'kind', 'state', 'title', 'artist',
                      'planned_duration_seconds', 'actual_duration_seconds',
                      'narration_text', 'tts_text', 'tts_cues', 'narration_role')
    return {
        'episode': {key: episode[key] for key in fields if key in episode},
        'segments': [{key: segment[key] for key in segment_fields if key in segment}
                     for segment in episode.get('segments', [])],
        'limitations': ['Evidence is source domain and title only (no URLs, queries or prompts).',
                        'Segment durations do not equal mix duration when speech overlaps music.',
                        'Future planned segments may not yet have audio.'],
    }


def fetch_usage(episode_id: str, listener_id: str) -> dict | None:
    """Best-effort provider usage summary for this episode (counts and timings only)."""
    return fetch_local(episode_id, listener_id, 'usage')


def fetch_evidence(episode_id: str, listener_id: str) -> dict | None:
    """Best-effort evidence behind each chapter (claims, source domain and title)."""
    return fetch_local(episode_id, listener_id, 'evidence')


def fetch_local(episode_id: str, listener_id: str, resource: str) -> dict | None:
    request = Request('http://127.0.0.1:8000/api/episodes/' + quote(episode_id) + '/' + resource,
                      headers={'X-Wavecast-Listener': listener_id})
    try:
        with urlopen(request, timeout=20) as response:
            if not response.geturl().startswith('http://127.0.0.1:8000/'):
                return None
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, ValueError, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('episode_id')
    parser.add_argument('--listener-id', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', args.episode_id):
        parser.error('Invalid episode ID')
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,128}', args.listener_id):
        parser.error('Invalid listener ID')
    # Hard-coded loopback URL; cannot read production or follow external redirects.
    request = Request('http://127.0.0.1:8000/api/episodes/' + quote(args.episode_id),
                      headers={'X-Wavecast-Listener': args.listener_id})
    try:
        with urlopen(request, timeout=20) as response:
            if not response.geturl().startswith('http://127.0.0.1:8000/'):
                raise ValueError('Unexpected redirect')
            episode = json.load(response)
        payload = review_payload(episode)
        payload['usage'] = fetch_usage(args.episode_id, args.listener_id)
        payload['evidence'] = fetch_evidence(args.episode_id, args.listener_id)
        output = Path('.wavecast-data/cloud/reviews') / (args.episode_id + '.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                          encoding='utf-8')
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as error:
        print(json.dumps({'status': 'failed', 'error_type': type(error).__name__}))
        return 1
    print(json.dumps({'status': 'ok', 'review_file': str(output)}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
