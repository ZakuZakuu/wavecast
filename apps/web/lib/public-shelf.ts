import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "./api";
import type { PublicShelfItem } from "./types";

export type PublicShelfState = {
  /** What the rail shows now (empty while loading, and when the section is left out). */
  items: PublicShelfItem[];
  /** Asked for the first time and not answered yet. */
  loading: boolean;
  /** A 换一批 is on its way: the rail shows placeholders. */
  refreshing: boolean;
  /** Too few public programmes (or none could be reached): the whole section is left out. */
  hidden: boolean;
  /** Nothing more can be offered: 换一批 gives way to 已经看完了. */
  atEnd: boolean;
  refresh: () => void;
};

/**
 * 「大家都在听」: a batch of public programmes, and the next batch each time 换一批 is pressed. The
 * ones already shown are sent along so they are not offered again; nothing is generated, so there is
 * no daily limit. Asked again when `identity` changes (what is offered depends on who is asking).
 */
export function usePublicShelf(identity: string | null, enabled: boolean): PublicShelfState {
  const [items, setItems] = useState<PublicShelfItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [hidden, setHidden] = useState(false);
  const [atEnd, setAtEnd] = useState(false);
  const shown = useRef<string[]>([]);
  const generation = useRef(0);

  useEffect(() => {
    if (!enabled) return;
    const mine = ++generation.current;
    shown.current = [];
    setLoading(true);
    setRefreshing(false);
    setHidden(false);
    setAtEnd(false);
    api.publicShelf()
      .then((page) => {
        if (generation.current !== mine) return;
        shown.current = page.items.map((item) => item.id);
        setItems(page.items);
        setHidden(page.items.length === 0);
        setAtEnd(!page.has_more);
      })
      .catch(() => {
        if (generation.current !== mine) return;
        // A shelf that cannot be reached is not worth an error on the home page.
        setItems([]);
        setHidden(true);
      })
      .finally(() => {
        if (generation.current === mine) setLoading(false);
      });
  }, [enabled, identity]);

  const refresh = useCallback(() => {
    if (refreshing || loading || atEnd || !items.length) return;
    const mine = generation.current;
    setRefreshing(true);
    api.publicShelf(shown.current)
      .then((page) => {
        if (generation.current !== mine) return;
        if (page.items.length) {
          shown.current = [...shown.current, ...page.items.map((item) => item.id)];
          setItems(page.items);
        }
        setAtEnd(!page.has_more || page.items.length === 0);
      })
      .catch(() => undefined)
      .finally(() => {
        if (generation.current === mine) setRefreshing(false);
      });
  }, [atEnd, items.length, loading, refreshing]);

  return { items, loading, refreshing, hidden, atEnd, refresh };
}
