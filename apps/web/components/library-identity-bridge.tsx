"use client";

import { createElement, useEffect, useRef, useState, type ReactNode } from "react";

import { authClient, clearApiAuthToken } from "../lib/auth-client";
import {
  activateGuestLibraryIdentity,
  beginLibraryIdentityTransition,
  cancelLibraryIdentityTransition,
  syncAuthenticatedLibrary,
} from "../lib/user-library";

export function LibraryIdentityBridge({ children }: { children: ReactNode }) {
  const { data: session, isPending } = authClient.useSession();
  // Only the first session lookup may hold the app back. Better Auth sets
  // isPending again on every refetch while signed out (data is null), which
  // fires each time the page returns to the foreground; treating that as a new
  // identity would unmount the whole app, player included.
  const settled = useRef(false);
  if (!isPending) settled.current = true;
  const identity = settled.current ? session?.user?.id ?? "guest" : null;
  const [readyIdentity, setReadyIdentity] = useState<string | null>(null);
  const [failedIdentity, setFailedIdentity] = useState<string | null>(null);
  const [retryGeneration, setRetryGeneration] = useState(0);

  useEffect(() => {
    if (identity === null) {
      setReadyIdentity(null);
      setFailedIdentity(null);
      return;
    }

    let active = true;
    const userId = identity === "guest" ? undefined : identity;
    const nextIdentity = identity;
    const generation = beginLibraryIdentityTransition();
    setReadyIdentity(null);
    setFailedIdentity(null);
    clearApiAuthToken();
    const initialization = userId
      ? syncAuthenticatedLibrary(userId, generation)
      : Promise.resolve(activateGuestLibraryIdentity(generation));
    void initialization.then(() => {
      if (active) setReadyIdentity(nextIdentity);
    }).catch(() => {
      if (active) setFailedIdentity(nextIdentity);
    });

    return () => {
      active = false;
      cancelLibraryIdentityTransition(generation);
    };
  }, [identity, retryGeneration]);

  if (identity === null || readyIdentity !== identity) {
    if (identity !== null && failedIdentity === identity) {
      return createElement("div", {
        className: "library-identity-loading",
        role: "alert",
      },
      createElement("p", null, "暂时无法同步你的节目库，请检查网络后重试。"),
      createElement("button", {
        type: "button",
        onClick: () => setRetryGeneration((value) => value + 1),
      }, "重试"));
    }
    return createElement("div", {
      className: "library-identity-loading",
      "aria-busy": "true",
      "aria-label": "正在读取节目库身份",
    });
  }
  return children;
}
