/** UA detection is a hint, never a claim that playback is supported or blocked. */
export function browserGuidance(userAgent: string, maxTouchPoints = 0): "wechat-ios" | "wechat-other" | "desktop" | "none" {
  const ios = /iPhone|iPad|iPod/i.test(userAgent) || (/Macintosh/i.test(userAgent) && maxTouchPoints > 1);
  if (/MicroMessenger/i.test(userAgent)) return ios ? "wechat-ios" : "wechat-other";
  if (!ios && !/Android|Mobile/i.test(userAgent)) return "desktop";
  return "none";
}
