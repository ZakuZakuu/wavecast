import { Pool } from "pg";
import { PostgresDialect } from "kysely";
import { betterAuth } from "better-auth";
import { jwt } from "better-auth/plugins";

export class AuthNotConfiguredError extends Error {
  constructor() {
    super("Authentication is not configured");
  }
}

export function isAuthConfigured(): boolean {
  return Boolean(
    process.env.WAVECAST_DATABASE_URL &&
      process.env.BETTER_AUTH_SECRET &&
      process.env.BETTER_AUTH_URL,
  );
}

let authInstance: ReturnType<typeof createAuth> | undefined;
let databasePool: Pool | undefined;

export function createAuth() {
  const databaseUrl = process.env.WAVECAST_DATABASE_URL;
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
    plugins: [
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
