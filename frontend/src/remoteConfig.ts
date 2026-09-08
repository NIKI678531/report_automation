export const REMOTE_BASE = "/remote/fund-cmt-auto";
export const API_BASE = `${REMOTE_BASE}/api/v1`;

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`;
}

// FastAPI signs the internal /api/v1 URL. Add only the external proxy prefix;
// do not parse/re-encode the signature query string.
export function artifactUrl(path: string): string {
  if (!path.startsWith("/api/v1/artifacts/")) throw new Error("Invalid artifact download URL");
  return `${REMOTE_BASE}${path}`;
}
