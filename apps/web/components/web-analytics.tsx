"use client";

import { Analytics } from "@vercel/analytics/next";

import { beforeSendAnalytics } from "../lib/analytics-filter";

/**
 * Vercel Web Analytics (free tier), mounted once in the root layout. A client
 * component only because `beforeSend` is a function; it renders nothing.
 */
export function WebAnalytics() {
  return <Analytics beforeSend={beforeSendAnalytics} />;
}
