// Remembers the last tab page so the player's 收起 returns there without
// relying on browser history (which may leave the app on a cold open).
let lastTabPath: string | null = null;

export function rememberTabPath(path: string): void {
  lastTabPath = path;
}

export function lastTabPathOr(fallback = "/"): string {
  return lastTabPath ?? fallback;
}
