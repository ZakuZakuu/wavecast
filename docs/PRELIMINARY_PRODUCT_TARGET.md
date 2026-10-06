# WaveCast Preliminary Product Target

**Status:** Product freeze for the preliminary-round build  
**Audience:** Every ChatGPT/Codex/engineering session working on WaveCast  
**Read before:** planning, architecture changes, playback changes, narration changes, or UI work

---

## 0. 产品定位与差异化（2026-10 收敛）

**核心价值：为长尾、个人化的音乐兴趣，做一档本来不存在的节目。**

- 用户不会因为 AI 电台“比现成的更好”而离开音乐软件、播客和真人电台。他们会来，是因为想听的那件事在别处**没有对应的节目**。例如：某款游戏的配乐是怎样配合游戏内容的；哪些歌曲用了某种乐器或乐理手法。这类题目有人想听，但真人电台是小众媒体，不会为少数听众去做。
- 所以 WaveCast 的对手不是“更好的电台”，而是“没有”。小众意味着大量需求从未被满足；系统的任务是帮用户发掘更独特的音乐世界，而不仅是大众选题。
- 个性化是手段：节目针对用户的口味与问题来做；收听记录用于进一步推荐，并做有创意的选题，让用户进入首页就觉得“这个题目有意思，我要听一下”。

**期望值要诚实。** AI 没有真人主播/DJ 那样的阅历，不追求超越真人节目；内部判断是达到真人节目的六成已经有价值。这是内部校准，不对外写成数据或承诺。

**音乐是真的，AI 不生成音乐。** 歌曲来自真实曲库中的真实作品；AI 负责研究、选曲、写稿和（合成）配音。这对排斥 AIGC 的受众是天然缓冲：AI 没有替代歌手或主持人，而是在没有真人愿意做节目的地方补上一档。主持声音是 AI 合成的，不得对外表述为真人主持，也无需回避。

**对外表述守则（简介、海报、视频）**

- 强调：选题的独特与个性化、真实的歌、补缺口而非取代。
- 避免：夸耀 AI 的强大或编排水平；“取代/超越电台和主持人”；把示意内容说成真实生成结果；未核实的功能（见下）。
- 小众选题示例只能写成题目，不得由我们断言某首歌具体用了什么手法等事实。

**与愿景的差距（尚未完成，不可当作已实现来宣传）**

- 游客首页固定的“先听这几档”偏大众，缺少“这个有意思”的惊喜感。
- 基于收听的创意化推荐依赖 AI 推荐规划器；其开关此前记录为生产默认关闭、走确定性兜底，线上实际状态待核实。
- 游戏配乐、乐理/乐器类专业题目的研究质量和曲库覆盖尚未系统验证。

以上只决定首页选题、推荐和对外材料的优先级，不改变下面 P0 的听感目标。

---

## 1. What we are shipping in this stage

The preliminary-round goal is **not** to prove every possible WaveCast mode or to perfect the underlying runtime architecture.

The goal is to ship **one convincing, end-to-end AI radio listening experience** that a judge can start, listen to, and immediately understand.

The default experience for this stage is a **light-hosted driving-radio style programme**:

- music remains the main content;
- a host appears occasionally with short, useful comments;
- narration may happen **inside a track**, over a safe instrumental / non-vocal region, or around a transition;
- some transitions may contain no narration at all and should simply mix cleanly;
- the programme should feel continuously produced, not like a playlist with TTS blocks inserted between songs.

A listener should perceive one coherent radio programme, not the internal generation stages.

---

## 2. Core listening experience

The canonical mental model is:

> **WaveCast generates an editorial audio timeline, not a playlist plus inter-track comments.**

Music, host speech, ducking, fades, transitions, and silence are all parts of one programme arrangement.

### Opening

When a user starts a newly generated programme:

1. music should begin quickly;
2. the first tens of seconds provide natural latency cover for background generation;
3. the first host copy should already be known, or nearly ready, from the proposal/opening preparation stage;
4. when a safe instrumental or non-vocal window appears, the music may duck and the host can briefly introduce:
   - what is playing;
   - one useful piece of context;
   - why this is a good place to begin the programme;
5. the host leaves before an important vocal passage and the music returns naturally.

The product **must not require the first song to finish before the first host speech**.

The exact timestamp is not a fixed contract. A host should use an appropriate musical window rather than speak at a mechanically chosen second.

### During the programme

Narration is flexible. It may occur:

- over an instrumental intro;
- in an instrumental break or other low-vocal section;
- over an outgoing instrumental outro;
- during a cross-track transition;
- as a short standalone spoken beat when the story genuinely needs it.

Narration is **not required between every pair of tracks**.

A direct music-to-music mix is valid when talking would make the experience worse.

The host should usually answer questions such as:

- What are we hearing?
- Why is this track here?
- What should the listener notice?
- How does this connect to the programme topic or the surrounding music?

Avoid turning every host appearance into a Wikipedia-style biography dump.

### Ending

An Outro belongs only at the genuine end of the programme.

The system must not infer that a temporary shortage of resolved future music means the programme is editorially complete.

The programme length and track count are **content-dependent**. There is no product requirement such as “at least 3 tracks” or “exactly 5 tracks.” For a typical 15–25 minute music-led programme, several tracks will often be natural, but this is a product outcome, not a hard runtime invariant.

---

## 3. Default host style for the preliminary round

The preliminary demo should optimize for one middle-ground style rather than fully polishing several modes.

Think:

> **a good radio station you would leave on while driving**

The host is present, but does not dominate.

Typical behavior:

- short introduction during an early safe musical window;
- occasional 1–3 sentence contextual comments;
- some transitions with narration;
- some transitions with only mixing;
- no requirement to explain every song;
- no long lecture unless the chosen programme topic genuinely calls for it.

Existing NONE / LIGHT / FULL concepts may remain in code, but **only the default light-radio experience is P0 for this stage**.

Do not spend preliminary-round time making all modes equally sophisticated.

---

## 4. Opening package

The proposal / programme-start path should conceptually prepare an **Opening Package** before the listener reaches the player.

The package should be sufficient to start a credible programme while the expensive pipeline continues in the background.

Conceptually it contains:

- the opening track;
- the opening editorial intent;
- the first short host copy or enough structured context to produce it immediately;
- a safe preferred placement intent/window when available;
- enough next-step intent to let background generation continue coherently.

This does **not** mean pre-generating the whole show.

It means the first listening minute should not depend on the slowest Research/Curator path.

TTS may still be generated just after playback starts, provided it is ready before the intended host window. Music starts first; the host should arrive naturally, not after an arbitrary full-song wait.

---

## 5. Timing and vocal awareness

The lyric/timing work exists to improve **placement**, not to make the LLM analyze lyric text.

For this stage:

- timestamp-only vocal / lyric intervals are useful;
- avoid talking over important lead vocals when possible;
- prefer instrumental intros, gaps, breaks, and outros;
- duck music under speech rather than treating narration as a totally separate player;
- if timing metadata is unavailable, use a conservative fallback;
- never block music playback merely because narration placement is imperfect.

The listener should not be aware of internal placeholders, narration states, generation jobs, or timing metadata.

---

## 6. Continuity rule

The strongest runtime product rule remains:

> **Music continuity wins over optional narration.**

If Writer or TTS is late:

- keep the programme playing;
- omit or defer that host beat;
- do not show a loading wall;
- do not strand the programme behind an internal narration placeholder.

However, “music continuity wins” does **not** mean narration is only allowed between songs. Narration should be arranged into the continuous programme whenever it is ready and musically appropriate.

---

## 7. P0 acceptance target before UI P0

Do not keep expanding the playback architecture once this experience is achieved.

The listening P0 is good enough when a fresh generated programme can demonstrate all of the following:

1. Playback starts quickly with real music.
2. A short host introduction can appear during an appropriate early musical window; it does not require waiting for the first song to end.
3. At least one later host appearance is placed naturally in the programme, which may be in-track or around a transition.
4. At least one transition may be music-only and still sound intentional.
5. The host does not routinely talk over obvious lead vocals.
6. The programme has a coherent editorial arc and a genuine ending; temporary generation shortages are not presented as the final Outro.
7. Writer/TTS/provider degradation does not stop music.
8. The listener can play through the programme without seeing internal states such as `Pending host bridge`, `SCRIPT_READY`, or other implementation terminology.
9. Basic seek/pause/resume behavior remains good enough for a demo; already-filed long-tail player issues do not need to block preliminary submission unless they break the core flow.

After these are credible in one default radio style, **stop playback expansion and move to UI P0**.

---

## 8. Explicit non-goals for the preliminary round

Unless a concrete blocker proves otherwise, do **not** spend this stage on:

- another broad player/runtime rewrite;
- perfect support for NONE/LIGHT/FULL as three equally complete products;
- hard-coded minimum or maximum track-count policy beyond existing safety bounds;
- beat/downbeat-aware DJ automation;
- semantic lyric analysis;
- sophisticated TTS emotion/prosody control;
- adaptive RL/recommendation research;
- exhaustive edge-case recovery;
- polishing already-filed non-P0 playback issues;
- architecture work whose main benefit is future cleanliness rather than the preliminary demo.

Prefer a small, product-correct fix over a more general architecture when both can safely deliver the target experience.

---

## 9. Engineering priority order

When trade-offs appear, use this order:

1. **Can a listener enjoy and understand the programme?**
2. **Does the core listening flow continue without interruption?**
3. **Does the narration/music arrangement feel like radio rather than stitched blocks?**
4. **Is the result coherent enough to demonstrate the WaveCast idea?**
5. **Is the implementation safe and testable enough to submit?**
6. Only then optimize architecture purity, generality, or future extensibility.

A technically elegant change that delays the demo without materially improving the above experience is the wrong change for this milestone.

---

## 10. Handoff rule for future sessions

A new session must not infer the active product goal only from historical ADRs, old PRs, or runtime architecture notes.

Before changing code, it must read:

1. `AGENTS.md`
2. **this document**
3. `docs/PROJECT_STATE.md`
4. only then the relevant handoff/ADR/implementation files

If older documentation describes a technically stricter behavior that conflicts with this preliminary-round product target, **do not silently follow the old behavior**. Reconcile the conflict against the current product goal and update the state/handoff documentation.

The immediate roadmap is intentionally short:

> **Listening P0 → UI P0 → preliminary-round submission**

Do not reopen broader platform work until those two P0s are complete.
