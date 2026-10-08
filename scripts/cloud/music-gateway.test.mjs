import test from 'node:test';
import assert from 'node:assert/strict';
import { makeGateway } from './music-gateway.ts';
const token = 'offline-test-key-only-'.repeat(3);
const env = { MUSIC_GATEWAY_TOKEN: token, MUSIC_SIDECAR_URL: 'http://music-sidecar.railway.internal:8000' };
const req = (path, auth = token, method = 'GET') => new Request('https://gateway.invalid' + path, {
  method, headers: auth ? { Authorization: 'Bearer ' + auth } : {},
});

test('health is local; missing configuration and unauthorized requests never reach sidecar', async () => {
  let calls = 0;
  const fetcher = async () => { calls++; return Response.json({ tracks: [] }); };
  const gateway = makeGateway(env, { fetcher });
  assert.equal((await gateway(req('/health', '')).then(r => r.json())).status, 'ok');
  for (const key of ['', 'wrong', token + 'x']) assert.equal((await gateway(req('/search?query=a', key))).status, 401);
  for (const config of [{}, { ...env, MUSIC_GATEWAY_TOKEN: '' }, { ...env, MUSIC_SIDECAR_URL: 'https://evil.invalid' }])
    assert.equal((await makeGateway(config, { fetcher })(req('/search?query=a'))).status, 503);
  assert.equal(calls, 0);
});

test('only bounded GET catalogue routes; bearer is never sent to sidecar', async () => {
  const calls = [];
  const gateway = makeGateway(env, { fetcher: async (url, options) => {
    calls.push({ url: String(url), options }); return Response.json({ tracks: [] });
  } });
  for (const path of ['/search?query=Bonobo&limit=3', '/tracks/123', '/tracks/123/playback', '/tracks/123/timing', '/ready'])
    assert.equal((await gateway(req(path))).status, 200);
  assert.equal(calls.length, 5);
  for (const { url, options } of calls) {
    assert.ok(url.startsWith(env.MUSIC_SIDECAR_URL));
    assert.equal(options.headers.Authorization, undefined);
    assert.equal(options.redirect, 'manual');
  }
  for (const path of ['/api/episodes', '/tracks/abc', '/tracks/123?url=https://evil.invalid', '/search?query=x&limit=51', '/search?query=', '/search?query=a&query=b', '/search?query=x&url=https://evil.invalid'])
    assert.ok([400, 404].includes((await gateway(req(path))).status));
  assert.equal((await gateway(req('/search?query=x', token, 'POST'))).status, 405);
  assert.equal(calls.length, 5);
});

test('redirects, upstream errors and malformed/oversized replies are sanitized', async () => {
  for (const response of [new Response('SECRET', { status: 302, headers: { Location: 'https://evil.invalid' } }),
    new Response('SECRET', { status: 502 }), new Response('SECRET'), Response.json(['SECRET']),
    new Response('x'.repeat(2_000_001))]) {
    const reply = await makeGateway(env, { fetcher: async () => response })(req('/tracks/123'));
    assert.equal(reply.status, 502); assert.ok(!(await reply.text()).includes('SECRET'));
  }
  const reply = await makeGateway(env, { fetcher: async () => { throw new Error('SECRET'); } })(req('/tracks/123'));
  assert.equal(reply.status, 502); assert.ok(!(await reply.text()).includes('SECRET'));
});

test('rate window is bounded and resets; responses cannot be cached', async () => {
  let clock = 0, calls = 0;
  const gateway = makeGateway(env, { now: () => clock, maxRequests: 1, fetcher: async () => { calls++; return Response.json({}); } });
  const first = await gateway(req('/tracks/123'));
  assert.equal(first.status, 200); assert.equal(first.headers.get('cache-control'), 'no-store');
  const busy = await gateway(req('/tracks/123')); assert.equal(busy.status, 429);
  assert.equal(busy.headers.get('retry-after'), '60'); assert.equal(calls, 1);
  clock = 60_000; assert.equal((await gateway(req('/tracks/123'))).status, 200);
});

test('concurrent cap rejects excess without upstream work and releases after completion', async () => {
  let release;
  const waiting = new Promise(resolve => { release = resolve; });
  let calls = 0;
  const gateway = makeGateway(env, { maxConcurrent: 1, fetcher: async () => { calls++; await waiting; return Response.json({}); } });
  const first = gateway(req('/tracks/123'));
  assert.equal((await gateway(req('/tracks/456'))).status, 429); assert.equal(calls, 1);
  release(); assert.equal((await first).status, 200);
  assert.equal((await gateway(req('/tracks/456'))).status, 200);
});
