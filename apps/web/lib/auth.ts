import { Pool } from "pg";
import { PostgresDialect } from "kysely";
import { betterAuth } from "better-auth";
import { jwt } from "better-auth/plugins";
import { emailOTP } from "better-auth/plugins/email-otp";
import { APIError } from "better-auth/api";
import { resolveAuthDatabaseUrl } from "./auth-database-url";
import { isEmailOtpConfigured, markEmailDeliveryFailed, sendLoginOtp } from "./email-otp";

export class AuthNotConfiguredError extends Error {
  constructor() {
    super("Authentication is not configured");
  }
}

export function isAuthConfigured(): boolean {
  return Boolean(
    resolveAuthDatabaseUrl() &&
      process.env.BETTER_AUTH_SECRET &&
      process.env.BETTER_AUTH_URL,
  );
}

let authInstance: ReturnType<typeof createAuth> | undefined;
let databasePool: Pool | undefined;

export function createAuth() {
  const databaseUrl = resolveAuthDatabaseUrl();
  const secret = process.env.BETTER_AUTH_SECRET;
  const baseURL = process.env.BETTER_AUTH_URL;
  if (!databaseUrl || !secret || !baseURL) throw new AuthNotConfiguredError();

  databasePool = new Pool({ connectionString: databaseUrl, max: 3 });
  const socialProviders = {
    ...(process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET
      ? {
          google: {
            clientId: process.env.GOOGLE_CLIENT_ID,
            clientSecret: process.env.GOOGLE_CLIENT_SECRET,
          },
        }
      : {}),
    ...(process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET
      ? {
          github: {
            clientId: process.env.GITHUB_CLIENT_ID,
            clientSecret: process.env.GITHUB_CLIENT_SECRET,
          },
        }
      : {}),
  };

  return betterAuth({
    appName: "WaveCast",
    baseURL,
    secret,
    database: {
      dialect: new PostgresDialect({ pool: databasePool }),
      type: "postgres",
      schemaName: process.env.BETTER_AUTH_SCHEMA ?? "auth",
    },
    socialProviders,
    // Shared counters survive serverless instance changes. Apply auth:migrate
    // with mail credentials configured before enabling email login in production.
    ...(isEmailOtpConfigured() ? {
      rateLimit: {
        enabled: true,
        storage: "database" as const,
        customRules: {
          "/email-otp/send-verification-otp": { window: 60, max: 3 },
        },
      },
    } : {}),
    plugins: [
      ...(isEmailOtpConfigured() ? [emailOTP({
        otpLength: 6,
        expiresIn: 300,
        allowedAttempts: 3,
        storeOTP: "hashed",
        async sendVerificationOTP({ email, otp, type }) {
          if (type !== "sign-in") {
            throw new APIError("BAD_REQUEST", { message: "Unsupported email operation" });
          }
          try {
            await sendLoginOtp({ email, otp });
          } catch {
            markEmailDeliveryFailed();
            throw new APIError("SERVICE_UNAVAILABLE", { message: "Email delivery unavailable" });
          }
        },
      })] : []),
      jwt({
        jwt: {
          issuer: baseURL,
          audience: baseURL,
          definePayload: ({ user }) => ({ id: user.id }),
        },
      }),
    ],
  });
}

export function getAuth() {
  if (!authInstance) authInstance = createAuth();
  return authInstance;
}

export function configuredSocialProviders(): string[] {
  const configured: string[] = [];
  if (process.env.GOOGLE_CLIENT_ID && process.env.GOOGLE_CLIENT_SECRET) {
    configured.push("google");
  }
  if (process.env.GITHUB_CLIENT_ID && process.env.GITHUB_CLIENT_SECRET) {
    configured.push("github");
  }
  return configured;
}
