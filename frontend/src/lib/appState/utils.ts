import type { RouteKey } from "./types";

export const routes: RouteKey[] = ["workspace", "chat", "notebook", "quiz", "source", "developer"];

export function getInitialRoute(): RouteKey {
  const hash = window.location.hash.replace("#", "") as RouteKey;
  return routes.includes(hash) ? hash : "workspace";
}

export function formatDateTime(value?: string): string {
  if (!value) {
    return "Never";
  }
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

export function formatRelative(value?: string): string {
  if (!value) {
    return "not yet";
  }
  const delta = Date.now() - new Date(value).getTime();
  const mins = Math.max(0, Math.round(delta / 60000));
  if (mins < 1) {
    return "just now";
  }
  if (mins < 60) {
    return `${mins}m ago`;
  }
  const hours = Math.round(mins / 60);
  if (hours < 24) {
    return `${hours}h ago`;
  }
  return `${Math.round(hours / 24)}d ago`;
}

export async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  throw new Error("Clipboard unavailable");
}
