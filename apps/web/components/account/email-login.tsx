"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";
import { authClient } from "../../lib/auth-client";

function errorMessage(error: { code?: string; status?: number }, sending: boolean): string {
  if (error.status === 429) return "操作有点频繁，请稍等一分钟再试。";
  if (error.code === "OTP_EXPIRED") return "验证码已过期，请重新获取。";
  if (error.code === "TOO_MANY_ATTEMPTS") return "尝试次数已用完，请重新获取验证码。";
  if (error.code === "INVALID_OTP") return "验证码不正确，请检查后再试。";
  return sending ? "验证码暂时没发出去，请稍后再试。" : "暂时无法登录，请稍后再试。";
}

export function EmailLogin({ disabled, onBusyChange, onSuccess }: {
  disabled: boolean;
  onBusyChange: (busy: boolean) => void;
  onSuccess: () => void;
}) {
  const [email, setEmail] = useState("");
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [otp, setOtp] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const lock = useRef(false);
  const [resendAt, setResendAt] = useState(0);
  const [remaining, setRemaining] = useState(0);
  const codeInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const tick = () => setRemaining(Math.max(0, Math.ceil((resendAt - Date.now()) / 1000)));
    tick();
    if (!resendAt) return;
    const timer = window.setInterval(tick, 1000);
    return () => window.clearInterval(timer);
  }, [resendAt]);

  useEffect(() => {
    if (sentTo) codeInput.current?.focus();
  }, [sentTo]);

  async function run(sending: boolean) {
    if (lock.current || disabled) return;
    const address = sentTo ?? email.trim().toLowerCase();
    if (sending && Date.now() < resendAt) return;
    lock.current = true;
    setBusy(true);
    onBusyChange(true);
    setError(null);
    try {
      const result = sending
        ? await authClient.emailOtp.sendVerificationOtp({ email: address, type: "sign-in" })
        : await authClient.signIn.emailOtp({ email: address, otp });
      if (result.error) {
        setError(errorMessage(result.error, sending));
        if (result.error.status === 429) setResendAt(Date.now() + 60_000);
      } else if (sending) {
        setSentTo(address);
        setOtp("");
        setResendAt(Date.now() + 60_000);
      } else {
        onSuccess();
      }
    } catch {
      setError(errorMessage({}, sending));
    } finally {
      lock.current = false;
      setBusy(false);
      onBusyChange(false);
    }
  }

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run(!sentTo);
  }

  return (
    <form className="login-email" onSubmit={submit} aria-label="邮箱验证码登录">
      {sentTo ? (
        <>
          <p className="login-email-note" role="status">验证码已发送至 <strong>{sentTo}</strong></p>
          <label htmlFor="login-otp">验证码</label>
          <input ref={codeInput} id="login-otp" type="text" inputMode="numeric" autoComplete="one-time-code"
            pattern="[0-9]{6}" maxLength={6} required placeholder="6 位验证码" value={otp}
            onChange={(event) => setOtp(event.target.value.replace(/\D/g, ""))} disabled={busy || disabled}
            aria-describedby="login-email-help" aria-invalid={Boolean(error)} />
          <button className="login-button is-email" type="submit" disabled={busy || disabled || otp.length !== 6}>
            {busy ? "正在处理…" : "登录并继续"}
          </button>
          <div className="login-email-options">
            <button type="button" disabled={busy || disabled} onClick={() => { setSentTo(null); setOtp(""); setError(null); }}>
              换个邮箱
            </button>
            <button type="button" disabled={busy || disabled || remaining > 0} onClick={() => void run(true)}>
              {remaining > 0 ? `${remaining} 秒后重发` : "重新发送"}
            </button>
          </div>
        </>
      ) : (
        <>
          <label htmlFor="login-email">邮箱</label>
          <input id="login-email" type="email" autoComplete="email" autoCapitalize="none" spellCheck={false}
            maxLength={254} required placeholder="输入你的邮箱" value={email}
            onChange={(event) => setEmail(event.target.value)} disabled={busy || disabled}
            aria-describedby="login-email-help" />
          <button className="login-button is-email" type="submit" disabled={busy || disabled || !email.trim() || remaining > 0}>
            {busy ? "正在发送…" : remaining > 0 ? `${remaining} 秒后可发送` : "获取验证码"}
          </button>
        </>
      )}
      <p id="login-email-help" className="login-foot">{sentTo ? "5 分钟内有效，没收到可以看看垃圾邮件。" : "无需密码，首次登录会自动创建账号。"}</p>
      {error ? <p className="login-error" role="alert">{error}</p> : null}
    </form>
  );
}
