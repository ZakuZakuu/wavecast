import { AsyncLocalStorage } from "node:async_hooks";

// Better Auth 1.7.6 catches sendVerificationOTP errors. Carry only a boolean
// through this request, so the route can report failed delivery without leaking
// an address/code or sharing mutable state between concurrent requests.
const delivery = new AsyncLocalStorage<{ failed: boolean }>();

export function markEmailDeliveryFailed(): void {
  const state = delivery.getStore();
  if (state) state.failed = true;
}

export async function withEmailDeliveryStatus(run: () => Promise<Response>): Promise<Response> {
  return delivery.run({ failed: false }, async () => {
    const response = await run();
    return delivery.getStore()?.failed
      ? Response.json({ code: "EMAIL_DELIVERY_UNAVAILABLE", message: "Email delivery unavailable" }, { status: 503 })
      : response;
  });
}

/** Server-only mail adapter. Never log provider bodies, addresses or OTPs. */
export function isEmailOtpConfigured(): boolean {
  return Boolean(process.env.RESEND_API_KEY?.trim() && process.env.WAVECAST_EMAIL_FROM?.trim());
}

export async function sendLoginOtp({ email, otp }: { email: string; otp: string }): Promise<void> {
  if (!isEmailOtpConfigured() || !/^\d{6}$/.test(otp)) {
    throw new Error("Email delivery unavailable");
  }
  try {
    const response = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${process.env.RESEND_API_KEY}`,
        "Content-Type": "application/json",
      },
      signal: AbortSignal.timeout(10_000),
      body: JSON.stringify({
        from: process.env.WAVECAST_EMAIL_FROM,
        to: [email],
        subject: "你的 WaveCast 登录验证码",
        text: `你的 WaveCast 登录验证码是：${otp}\n5 分钟内有效，请勿分享给他人。\n如果不是你本人操作，请忽略这封邮件。`,
        html: `<div style="font-family:Arial,sans-serif;max-width:440px;margin:32px auto;padding:32px;background:#f6f4ef;border-radius:20px;color:#1d1d1f"><p style="font-weight:700;letter-spacing:2px">WAVECAST</p><h1 style="font-size:24px">回来接着听</h1><p>你的登录验证码</p><p style="font-size:36px;font-weight:700;letter-spacing:8px">${otp}</p><p style="font-size:14px;color:#666">5 分钟内有效，请勿分享给他人。<br>如果不是你本人操作，请忽略这封邮件。</p></div>`,
      }),
    });
    if (!response.ok) throw new Error("Email delivery unavailable");
  } catch {
    // Provider errors can include recipient addresses or request contents.
    throw new Error("Email delivery unavailable");
  }
}
