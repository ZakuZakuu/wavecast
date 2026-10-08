import { configuredSocialProviders, isAuthConfigured } from "../../../../lib/auth";
import { isEmailOtpConfigured } from "../../../../lib/email-otp";

export function GET(): Response {
  const enabled = isAuthConfigured();
  return Response.json({
    enabled,
    providers: enabled ? configuredSocialProviders() : [],
    emailOtp: enabled && isEmailOtpConfigured(),
  });
}
