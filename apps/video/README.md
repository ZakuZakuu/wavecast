# WaveCast concept film (`@wavecast/video`)

Remotion project for the ~2:08 concept film. The single source of truth for
the creative is [`docs/design/film/FILM_BRIEF.md`](../../docs/design/film/FILM_BRIEF.md).
This package is a separate pnpm workspace package; `apps/web` does not depend on it.

Remotion is source-available under its own license (free for individuals,
for-profit companies with up to 3 employees and non-profits); see
`node_modules/remotion/LICENSE.md`.

## Where things are

| What | File |
|---|---|
| All on-screen text (station calls, side lines, titles, songs, host lines, route, recommendations, cover-wall titles) | `src/content.ts` |
| Every timing (storyboard, camera, gestures, sound events) | `src/timeline.ts` |
| Light per moment (crossfade weights) | `src/scene.ts` |
| Backgrounds: morning beams/dust, afternoon dapple + station tint, night rain/bokeh/drops | `src/scenes/Backdrop.tsx` |
| Cold open (dial, needle, lock, brand) | `src/scenes/ColdOpen.tsx`, `src/scenes/coldCurve.ts` |
| Phone rig, camera and screen choreography | `src/scenes/Phone.tsx` |
| Phone UI (home, player, tuner, tuning-in, route, mini bar, tab bar, finger) | `src/components/PhoneScreens.tsx` |
| Covers: the product generator `apps/web/lib/cover/build-cover.ts` | `src/components/Cover.tsx` |
| Chapter cards, station calls, side lines, subtitles | `src/scenes/Text.tsx` |
| Breakdown cards, mixer, cover wall and end card | `src/scenes/Breakdown.tsx`, `src/scenes/NightOverlay.tsx`, `src/scenes/Wall.tsx` |
| Grain, vignette, disclaimer, final fade | `src/scenes/Overlays.tsx` |
| Sound: effects, score (D major pentatonic, one 4-bar motif) and mix, synthesised offline with fixed seeds | `scripts/build-audio.ts`, `scripts/audio/` |
| Music cue sheet (`music-cues.md`) | `scripts/build-cues.ts` |

Every frame is a pure function of the frame number. There is no `Math.random`;
all randomness uses fixed seeds (`src/lib/math.ts`, `rng`).

## Preview locally

```sh
pnpm install
pnpm --dir apps/video studio        # Remotion Studio, composition "WaveCast"
pnpm --dir apps/video still 12 47.5 # PNG stills at those seconds -> apps/video/out/stills
```

Fonts (Noto Sans SC / Noto Serif SC) load from Google Fonts through
`@remotion/google-fonts`, so preview and render need network access.
`scripts/build-charset.ts` (run automatically by `studio`, `still` and `render`)
collects the characters the film uses so only the matching font slices load.

If your machine already has a Chrome/Chromium headless shell, point Remotion at it
with `REMOTION_BROWSER_EXECUTABLE=/path/to/headless_shell`; otherwise Remotion
downloads one.

## Render

```sh
pnpm --dir apps/video render
```

This writes `apps/video/out/wavecast-film.mp4` (with sound effects),
`apps/video/out/wavecast-film-silent.mp4` and `apps/video/out/music-cues.md`
(H.264, 1920×1080, 30 fps). `out/` is git-ignored; do not commit MP4s.

On GitHub: **Actions → Concept film → Run workflow** renders the same files and
uploads them as the `wavecast-film-<sha>` artifact.
