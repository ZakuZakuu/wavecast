# WaveCast Preliminary Product Target

**Status:** Product freeze for the preliminary-round build  
**Audience:** Every ChatGPT/Codex/engineering session working on WaveCast  
**Read before:** planning, architecture changes, playback changes, narration changes, or UI work

---

## 0. 产品定位与差异化（2026-10-07 收敛）

**核心价值：从你想听的一个问题出发，把音乐与它背后的故事编成一档专属电台节目。**

- 当用户想探索某种风格、游戏配乐或喜欢的艺人时，相关内容可能散落在视频、文章和歌单里，现成节目也未必恰好契合。WaveCast 把这些兴趣组织成可连续收听的节目，减少用户自行搜索、理解和拼接内容的成本；不假设别处完全没有相关内容。
- 长尾、个人化兴趣是展示差异化的好入口，例如“为什么某款游戏的音乐这么特别”。它不是产品门槛：从“下班听点爵士”到深入探索，都在服务范围内。既支持日常陪伴，也帮助发现和理解音乐。
- 个性化是手段：围绕用户的口味与问题编排，收听兴趣再延伸到下一次发现。首页可保留容易进入的主题，加入少量具体、有吸引力且试听通过的选题，不为了“小众”全部替换。

**质量标准要具体。** 讲解有依据、选曲扣题、听感自然、节目路线完整且有真实收尾。不以无法衡量的“真人节目几成”作为标准，也不宣称超越真人主播；按真实试听与验证结果判断质量。

**真实音乐，合成主持。** 当前产品播放已有歌曲，AI 负责研究、选曲、写稿和合成配音，不生成音乐；主持声音不得表述为真人。对外重点讲清楚听众获得的节目价值，无需反复解释“不取代谁”。

**对外表述守则（简介、海报、视频）**

- 强调：一个具体兴趣如何变成音乐与故事组成的节目，兼顾探索与陪伴；展示经过验证的特色选题。
- 避免：断言用户一定会离开其他应用、断言真人不愿做某类节目；夸耀 AI 或承诺超越真人；把示意内容说成真实生成结果；未核实的功能（见下）。
- 专业选题可作为待验证方向；未经证据核实，不断言某首歌使用了特定乐器或乐理手法，也不把该题目的生成质量视为已通过。

**与愿景的差距（尚未核实，不可当作已实现来宣传）**

- 游客首页固定选题目前偏大众；是否加入少量更有吸引力的具体主题，需要实际试听和用户选择。
- 基于收听的创意化推荐依赖 AI 推荐规划器；线上开关和实际效果待核实。已有推荐入口不等于已验证创意推荐能力，也不能未经核对就声称生产关闭。
- 游戏配乐、乐理/乐器类专业题目的研究质量和曲库覆盖尚未系统验证。

下一步先核实推荐状态，再小幅调整简介和设计海报；本定位不改变下面 P0 的听感目标，也不启动新一轮广泛功能重做。

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
