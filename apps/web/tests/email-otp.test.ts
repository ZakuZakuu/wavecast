// @vitest-environment node
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { betterAuth } from "better-auth";
import { memoryAdapter } from "better-auth/adapters/memory";
import { getAuthTables } from "better-auth/db";
// Capture the production configuration without connecting to a real database;
// execute the same plugins against the actual library's in-memory adapter below.
vi.mock("better-auth", async (importOriginal) => {
  const actual = await importOriginal<typeof import("better-auth")>();
  return { ...actual, betterAuth: (options: Parameters<typeof actual.betterAuth>[0]) =>
    typeof options?.database === "object" && "type" in options.database && options.database.type === "postgres"
      ? { options }
      : actual.betterAuth(options) };
});
import { createAuth } from "../lib/auth";
import { isEmailOtpConfigured, markEmailDeliveryFailed, sendLoginOtp, withEmailDeliveryStatus } from "../lib/email-otp";

const mail = vi.fn();
beforeEach(() => {
  vi.stubEnv("BETTER_AUTH_DATABASE_URL", "postgres://localhost/test");
  vi.stubEnv("BETTER_AUTH_SECRET", "a-test-secret-long-enough-for-better-auth-123456");
  vi.stubEnv("BETTER_AUTH_URL", "https://wavecast.example");
  vi.stubEnv("RESEND_API_KEY", "test-key");
  vi.stubEnv("WAVECAST_EMAIL_FROM", "WaveCast <login@auth.example>");
  mail.mockReset().mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", mail);
});
afterEach(() => { vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

function runtime() {
  const configured = createAuth();
  const db: Record<string, Array<Record<string, unknown>>> = { user: [], account: [], session: [], verification: [], jwks: [], rateLimit: [] };
  const auth = betterAuth({
    ...configured.options,
    database: memoryAdapter(db),
    rateLimit: { ...configured.options.rateLimit, storage: "memory" },
  });
  return { auth, db, configured };
}

function sentCode(): string {
  const body = JSON.parse(mail.mock.calls.at(-1)![1].body);
  return body.text.match(/\d{6}/)[0];
}

describe("email delivery", () => {
  it("is gated by both credentials and keeps provider details out of errors", async () => {
    vi.stubEnv("RESEND_API_KEY", "");
    expect(isEmailOtpConfigured()).toBe(false);
    expect(createAuth().options.plugins?.some((plugin) => plugin.id === "email-otp")).toBe(false);
    await expect(sendLoginOtp({ email: "test@example.com", otp: "123456" })).rejects.toThrow("Email delivery unavailable");
    expect(mail).not.toHaveBeenCalled();
    vi.stubEnv("RESEND_API_KEY", "test-key");
    mail.mockRejectedValue(new Error("private provider details"));
    await expect(sendLoginOtp({ email: "test@example.com", otp: "123456" })).rejects.toThrow(/^Email delivery unavailable$/);
  });

  it("does not insert invalid OTP content into the email", async () => {
    await expect(sendLoginOtp({ email: "test@example.com", otp: "<script>" })).rejects.toThrow();
    expect(mail).not.toHaveBeenCalled();
  });

  it("isolates delivery failures between concurrent requests", async () => {
    const [failed, healthy] = await Promise.all([
      withEmailDeliveryStatus(async () => { markEmailDeliveryFailed(); await Promise.resolve(); return Response.json({ success: true }); }),
      withEmailDeliveryStatus(async () => { await Promise.resolve(); return Response.json({ success: true }); }),
    ]);
    expect(failed.status).toBe(503);
    expect(healthy.status).toBe(200);
  });
});

describe("actual Better Auth email login", () => {
  it("reuses an existing verified OAuth user's ID; stores a hash and consumes the code", async () => {
    const { auth, db, configured } = runtime();
    expect(configured.options.rateLimit?.storage).toBe("database");
    expect(getAuthTables(configured.options).rateLimit).toBeDefined();
    const context = await auth.$context;
    const user = await context.internalAdapter.createUser({ email: "listener@example.com", name: "Listener", emailVerified: true }, { method: "oauth" });
    await context.internalAdapter.createAccount({ userId: user.id, providerId: "github", accountId: "github-listener" });
    await auth.api.sendVerificationOTP({ body: { email: user.email, type: "sign-in" } });
    const otp = sentCode();
    expect(JSON.stringify(db.verification)).not.toContain(otp);
    const result = await auth.api.signInEmailOTP({ body: { email: user.email, otp } });
    expect(result.user.id).toBe(user.id);
    expect(db.user).toHaveLength(1);
    await expect(auth.api.signInEmailOTP({ body: { email: user.email, otp } })).rejects.toMatchObject({ body: { code: "INVALID_OTP" } });
  });

  it("registers a new user only after proof of email ownership", async () => {
    const { auth, db } = runtime();
    await auth.api.sendVerificationOTP({ body: { email: "new@example.com", type: "sign-in" } });
    expect(db.user ?? []).toHaveLength(0);
    const result = await auth.api.signInEmailOTP({ body: { email: "new@example.com", otp: sentCode() } });
    expect(result.user.emailVerified).toBe(true);
    expect(db.user).toHaveLength(1);
  });

  it("rejects expired codes and locks out repeated incorrect codes", async () => {
    const { auth, db } = runtime();
    const body = { email: "expired@example.com", type: "sign-in" as const };
    await auth.api.sendVerificationOTP({ body });
    const otp = sentCode();
    db.verification[0].expiresAt = new Date(Date.now() - 1000);
    await expect(auth.api.signInEmailOTP({ body: { email: body.email, otp } })).rejects.toMatchObject({ body: { code: "OTP_EXPIRED" } });
    await auth.api.sendVerificationOTP({ body });
    const goodCode = sentCode();
    const wrongCode = goodCode === "000000" ? "111111" : "000000";
    for (let i = 0; i < 3; i++) await expect(auth.api.signInEmailOTP({ body: { email: body.email, otp: wrongCode } })).rejects.toMatchObject({ body: { code: "INVALID_OTP" } });
    await expect(auth.api.signInEmailOTP({ body: { email: body.email, otp: goodCode } })).rejects.toMatchObject({ body: { code: "TOO_MANY_ATTEMPTS" } });
  });

  it("rate limits sending through the public route and sanitizes mail errors", async () => {
    const { auth } = runtime();
    const request = () => new Request("https://wavecast.example/api/auth/email-otp/send-verification-otp", {
      method: "POST", headers: { "Content-Type": "application/json", Origin: "https://wavecast.example", "x-forwarded-for": "198.51.100.73" },
      body: JSON.stringify({ email: "rate@example.com", type: "sign-in" }),
    });
    expect((await auth.handler(request())).status).toBe(200);
    expect((await auth.handler(request())).status).toBe(200);
    expect((await auth.handler(request())).status).toBe(200);
    expect((await auth.handler(request())).status).toBe(429);
    expect(mail).toHaveBeenCalledTimes(3);
    mail.mockResolvedValue(new Response("private provider details", { status: 403 }));
    const failedRequest = new Request(request(), { headers: { "Content-Type": "application/json", Origin: "https://wavecast.example", "x-forwarded-for": "198.51.100.74" } });
    const response = await withEmailDeliveryStatus(() => auth.handler(failedRequest));
    expect(response.status).toBe(503);
    expect(await response.text()).not.toContain("private provider details");
  });
});
