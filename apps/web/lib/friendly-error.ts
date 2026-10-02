/** Shows backend/provider messages only when they are already listener-facing Chinese. */
export function friendlyError(message: string | null | undefined, fallback: string): string {
  return message && /[一-鿿]/.test(message) ? message : fallback;
}
