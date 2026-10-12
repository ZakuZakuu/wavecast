// Archived completed one-off Railway probe, retained for rollback; not auto-run.
const baseURL = 'http://music-sidecar.railway.internal:3101';

async function getJson(path) {
  const response = await fetch(`${baseURL}${path}`);
  if (!response.ok) {
    throw new Error(`${path} -> ${response.status} ${response.statusText}`);
  }
  return await response.json();
}

async function probe() {
  console.log('=== Music Sidecar Narration P0 Probe ===');

  const ready = await fetch(`${baseURL}/ready`);
  if (!ready.ok) throw new Error(`/ready -> ${ready.status}`);
  console.log(`ready=${ready.status}`);

  const search = await getJson('/search?query=%E6%96%B9%E5%A4%A7%E5%90%8C&limit=1');
  const tracks = Array.isArray(search.tracks) ? search.tracks : [];
  if (!tracks.length || !tracks[0].id) throw new Error('search returned no track id');
  const trackId = String(tracks[0].id);
  console.log(`track_id=${trackId}`);

  const timing = await getJson(`/tracks/${encodeURIComponent(trackId)}/timing`);
  const allowedTopLevel = new Set([
    'source_duration_seconds',
    'lyric_timestamps_available',
    'lyric_lines',
    'vocal_intervals',
  ]);
  for (const key of Object.keys(timing)) {
    if (!allowedTopLevel.has(key)) throw new Error(`unexpected timing key: ${key}`);
  }
  for (const key of ['lyric_lines', 'vocal_intervals']) {
    const intervals = timing[key];
    if (!Array.isArray(intervals)) throw new Error(`${key} is not an array`);
    for (const interval of intervals) {
      const keys = Object.keys(interval).sort().join(',');
      if (keys !== 'end_seconds,start_seconds') {
        throw new Error(`${key} contains non-timing data`);
      }
    }
  }

  console.log(`duration=${timing.source_duration_seconds}`);
  console.log(`timestamps=${timing.lyric_timestamps_available}`);
  console.log(`lyric_intervals=${timing.lyric_lines.length}`);
  console.log(`vocal_intervals=${timing.vocal_intervals.length}`);
  console.log('probe=PASS');
}

probe().catch((error) => {
  console.error(`probe=FAIL ${error.message}`);
  process.exit(1);
});

