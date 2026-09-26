# ADR 0016: Separate cheap Program Proposals from Episode materialization

## Context

WaveCast already has a durable progressive episode runtime. That runtime expects an
`EpisodeSeed` with a resolved opening track and starts expensive research, writing,
TTS, and progressive chapter generation only after the listener commits to listening.

The product UI now also needs two cheaper entry points:

- Tune: turn one listener intent into a program card.
- For You: eventually create a small batch of recommendation cards.

Generating full episodes for those cards would destroy the cost and latency model.

## Decision

Introduce a provider-neutral `ProgramProposal` boundary before `EpisodeSeed`.

A proposal contains only enough information to promise a listening experience:

- title, topic, short description;
- approximate duration;
- resolved opening-track identity;
- deterministic cover parameters;
- compact genre/mood tags;
- a short editorial route preview.

`ProgramProposalGenerator` is asynchronous and provider-neutral. Mock mode uses a
credential-free deterministic implementation. Live mode uses a bounded structured
LLM call only to draft editorial metadata and ranked artist/title hypotheses. The
LLM never supplies an authoritative catalog ID or playback reference. Application
code resolves each opening-track hypothesis through the existing
`MusicProviderRegistry` / exact catalog-resolution boundary before constructing a
`ProgramProposal`; if no candidate resolves, generation fails closed.

The API stores generated proposals in a proposal repository and exposes a generic
program-detail read. A listener does not create an episode by viewing a proposal.
Only the existing start-listening boundary converts the proposal into an
`EpisodeSeed` and enters the Phase 7 progressive runtime.

## Consequences

- Tune and future Home recommendation can share one proposal generator contract.
- Program cards stay cheap; live proposal creation may use one structured LLM call
  plus bounded catalog metadata lookups, but Exa/Tavily research, Writer, and TTS do
  not run before listening starts.
- The Phase 7 runtime remains unchanged.
- The first repository is intentionally in-memory. Durable proposal storage is a
  later production requirement before generated proposal links are expected to
  survive API restarts.
- The deterministic mock generator validates lifecycle and UI integration only; it
  is not a claim about recommendation quality.
