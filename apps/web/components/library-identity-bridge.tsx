"use client";

import { createElement, useEffect, useState, type ReactNode } from "react";

import { authClient, clearApiAuthToken } from "../lib/auth-client";
import {
  activateGuestLibraryIdentity,
  beginLibraryIdentityTransition,
  cancelLibraryIdentityTransition,
  syncAuthenticatedLibrary,
} from "../lib/user-library";

export function LibraryIdentityBridge({ children }: { children: ReactNode }) {
  const { data: session, isPending } = authClient.useSession();
  const identity = isPending ? null : session?.user?.id ?? "guest";
  const [readyIdentity, setReadyIdentity] = useState<string | null>(null);
  const [failedIdentity, setFailedIdentity] = useState<string | null>(null);
  const [retryGeneration, setRetryGeneration] = useState(0);

  useEffect(() => {
    if (isPending) {
      setReadyIdentity(null);
      setFailedIdentity(null);
      return;
    }

    let active = true;
    const userId = session?.user?.id;
    const nextIdentity = userId ?? "guest";
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
  }, [isPending, session?.user?.id, retryGeneration]);

  if (isPending || readyIdentity !== identity) {
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
