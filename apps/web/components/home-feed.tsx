"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { api } from "../lib/api";
import { authClient } from "../lib/auth-client";
import type { ProgramIdea, Seed } from "../lib/types";
import { AppShell } from "./app-shell";
import { ProgramArtwork } from "./program-artwork";
import { ProgramCard } from "./program-card";
import { WaveIcon } from "./wave-icon";

const ideaPalettes: [string, string][] = [
  ["#173b57", "#ef6757"],
  ["#2c2148", "#b677ff"],
  ["#123c36", "#8fd3b6"],
];

function ideaArtwork(idea: ProgramIdea, index: number) {
  return {
    family: ["editorial", "waveform", "geometry"][index % 3],
    seed: [...idea.id].reduce((sum, char) => sum + char.charCodeAt(0), 0) % 1000,
    palette: ideaPalettes[index % ideaPalettes.length],
  };
}

export function HomeFeed() {
  const router = useRouter();
  const { data: session, isPending: sessionPending } = authClient.useSession();
  const [seeds, setSeeds] = useState<Seed[]>([]);
  const [ideas, setIdeas] = useState<ProgramIdea[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [recommendationError, setRecommendationError] = useState<string | null>(null);
  const [recommendationsLoading, setRecommendationsLoading] = useState(false);
  const [materializingId, setMaterializingId] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => {
    api.seeds()
      .then(setSeeds)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "节目暂时无法载入"));
  }, []);

  useEffect(() => {
    if (sessionPending) return;
    if (!session?.user) {
      setIdeas([]);
      setRecommendationError(null);
      return;
    }

    let active = true;
    setRecommendationsLoading(true);
    setRecommendationError(null);
    api.recommendations(session.user.id)
      .then((value) => {
        if (active) setIdeas(value);
      })
      .catch((reason: unknown) => {
        if (active) {
          setRecommendationError(reason instanceof Error ? reason.message : "个性化节目暂时无法载入");
        }
      })
      .finally(() => {
        if (active) setRecommendationsLoading(false);
      });

    return () => {
      active = false;
    };
  }, [session?.user?.id, sessionPending]);

  const searchResults = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase();
    if (!needle) return seeds;
    return seeds.filter((seed) =>
      [
        seed.title,
        seed.topic,
        seed.short_description,
        seed.opening_track_title,
        seed.opening_track_artist,
      ].some((value) => value.toLocaleLowerCase().includes(needle)),
    );
  }, [query, seeds]);

  const openRecommendation = async (idea: ProgramIdea) => {
    if (materializingId) return;
    setMaterializingId(idea.id);
    setRecommendationError(null);
    try {
      if (!session?.user) throw new Error("请先登录后再生成个性化节目");
      const batch = await api.materializeRecommendation(idea.id, session.user.id);
      const proposal = batch.proposals[0];
      if (!proposal) throw new Error("节目暂时无法生成");
      setIdeas((current) => current.filter((candidate) => candidate.id !== idea.id));
      router.push(`/program/${proposal.id}`);
    } catch (reason) {
      setRecommendationError(reason instanceof Error ? reason.message : "节目暂时无法生成");
    } finally {
      setMaterializingId(null);
    }
  };

  return (
    <AppShell>
      <div className="page-header home-header">
        <div>
          <p className="program-kicker">WAVECAST</p>
          <h1>为你推荐 <WaveIcon name="chevron" size={24} /></h1>
        </div>
        <button
          type="button"
          className={searchOpen ? "icon-button soft-button active" : "icon-button soft-button"}
          aria-label={searchOpen ? "关闭搜索" : "搜索"}
          aria-expanded={searchOpen}
          onClick={() => {
            setSearchOpen((value) => !value);
            if (searchOpen) setQuery("");
          }}
        >
          <WaveIcon name={searchOpen ? "close" : "search"} />
        </button>
        <Link href="/account" className="profile-link" aria-label="账户">
          <span className="profile-dot" aria-hidden="true">
            {session?.user.name?.slice(0, 1) ?? "访"}
          </span>
        </Link>
      </div>

      {searchOpen ? (
        <section className="home-search-panel page-enter" aria-label="搜索节目">
          <div className="home-search-field">
            <WaveIcon name="search" size={18} />
            <input
              autoFocus
              type="search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="搜索节目、风格、艺人或歌曲"
              aria-label="搜索节目、风格、艺人或歌曲"
            />
            {query ? (
              <button type="button" aria-label="清除搜索" onClick={() => setQuery("")}>
                <WaveIcon name="close" size={15} />
              </button>
            ) : null}
          </div>
          <div className="home-search-summary">
            <span>{query ? "搜索结果" : "全部节目"}</span>
            <small>{searchResults.length} 个</small>
          </div>
          {searchResults.length ? (
            <div className="home-search-results">
              {searchResults.map((seed) => <ProgramCard seed={seed} compact key={"search-" + seed.id} />)}
            </div>
          ) : (
            <div className="home-search-empty">
              <p>没有找到匹配的节目。</p>
              <Link href="/tune">试试自己调一档</Link>
            </div>
          )}
        </section>
      ) : null}

      {error ? <p className="inline-error">{error}</p> : null}
      {recommendationError ? <p className="inline-error">{recommendationError}</p> : null}

      {session?.user ? (
        <section className="feed-section">
          <div className="section-title-row">
            <h2>根据你的口味</h2>
            <span>AI 为你准备</span>
          </div>
          <div className="program-shelf" aria-label="个性化推荐节目">
            {ideas.map((idea, index) => {
              const artwork = ideaArtwork(idea, index);
              const busy = materializingId === idea.id;
              return (
                <button
                  type="button"
                  className="program-card recommendation-card"
                  key={idea.id}
                  disabled={Boolean(materializingId)}
                  onClick={() => void openRecommendation(idea)}
                >
                  <ProgramArtwork
                    title={idea.title}
                    subtitle={idea.tags.slice(0, 2).join(" · ") || "For You"}
                    palette={artwork.palette}
                    seed={artwork.seed}
                    family={artwork.family}
                  />
                  <div className="program-card-copy">
                    <strong>{idea.title}</strong>
                    <span>{busy ? "正在准备节目…" : idea.reason}</span>
                  </div>
                </button>
              );
            })}
            {recommendationsLoading && !ideas.length
              ? Array.from({ length: 3 }).map((_, index) => <div className="program-skeleton" key={index} />)
              : null}
          </div>
          {!recommendationsLoading && !ideas.length && !recommendationError ? (
            <div className="recommendation-empty">
              <p>听几档节目、收藏喜欢的内容后，这里会继续长出新的节目。</p>
              <Link href="/tune">先调一档</Link>
            </div>
          ) : null}
        </section>
      ) : (
        <section className="feed-section">
          <div className="section-title-row">
            <h2>先听起来</h2>
            <Link href="/account">登录后开启个性化</Link>
          </div>
          <div className="program-shelf" aria-label="推荐节目">
            {seeds.map((seed) => <ProgramCard seed={seed} key={seed.id} />)}
            {!seeds.length && !error
              ? Array.from({ length: 4 }).map((_, index) => <div className="program-skeleton" key={index} />)
              : null}
          </div>
        </section>
      )}

      <section className="feed-section">
        <div className="section-title-row"><h2>值得一听</h2><span>编辑精选</span></div>
        <div className="compact-program-list">
          {seeds.map((seed) => <ProgramCard seed={seed} compact key={"compact-" + seed.id} />)}
        </div>
      </section>

      <section className="editorial-banner">
        <div>
          <p className="program-kicker">GUIDED LISTENING</p>
          <h2>不是歌单，是一档为你排好的节目。</h2>
          <p>音乐先开始，故事只在你前方一点点长出来。</p>
        </div>
        <Link href="/tune" className="banner-action"><WaveIcon name="sparkle" />去调一档</Link>
      </section>
    </AppShell>
  );
}
