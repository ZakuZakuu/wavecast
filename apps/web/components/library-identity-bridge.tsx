"use client";

import { createElement, useEffect, useState, type ReactNode } from "react";

import { authClient, clearApiAuthToken } from "../lib/auth-client";
import { syncAuthenticatedLibrary, useGuestLibraryIdentity } from "../lib/user-library";

export function LibraryIdentityBridge({ children }: { children: ReactNode }) {
  const { data: session, isPending } = authClient.useSession();
  const identity = isPending ? null : session?.user?.id ?? "guest";
  const [readyIdentity, setReadyIdentity] = useState<string | null>(null);

  useEffect(() => {
    if (isPending) {
      setReadyIdentity(null);
      return;
    }

    let active = true;
    const nextIdentity = session?.user?.id ?? "guest";
    clearApiAuthToken();
    useGuestLibraryIdentity();
    const initialization = session?.user
      ? syncAuthenticatedLibrary()
      : Promise.resolve();
    void initialization
      .catch(() => undefined)
      .finally(() => {
        if (active) setReadyIdentity(nextIdentity);
      });

    return () => {
      active = false;
    };
  }, [isPending, session?.user?.id]);

  if (isPending || readyIdentity !== identity) {
    return createElement("div", {
      className: "library-identity-loading",
      "aria-busy": "true",
      "aria-label": "正在读取节目库身份",
    });
  }
  return children;
}
