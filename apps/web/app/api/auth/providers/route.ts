import { configuredSocialProviders, isAuthConfigured } from "../../../../lib/auth";

export function GET(): Response {
  const enabled = isAuthConfigured();
  return Response.json({
    enabled,
    providers: enabled ? configuredSocialProviders() : [],
  });
}
