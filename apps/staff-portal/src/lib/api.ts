import { auth } from "./firebase";
import { previewMatch } from "./preview-fixtures";

const BASE_URL = import.meta.env.VITE_API_URL || "http://localhost:8000/api";
const PREVIEW = import.meta.env.VITE_PREVIEW_AUTH === "1";

async function getAuthHeaders(): Promise<HeadersInit> {
  const user = auth.currentUser;
  if (!user) throw new Error("Not authenticated");
  const token = await user.getIdToken();
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

export async function apiFetch<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (PREVIEW) {
    const fixture = previewMatch(path, (options.method as string) ?? "GET");
    if (fixture !== undefined) {
      await new Promise((r) => setTimeout(r, 300));
      return fixture as T;
    }
  }
  const headers = await getAuthHeaders();
  const res = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: { ...headers, ...(options.headers as Record<string, string>) },
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  get: <T>(path: string) => apiFetch<T>(path),
  post: <T>(path: string, data: unknown) =>
    apiFetch<T>(path, { method: "POST", body: JSON.stringify(data) }),
  put: <T>(path: string, data: unknown) =>
    apiFetch<T>(path, { method: "PUT", body: JSON.stringify(data) }),
  delete: <T>(path: string) => apiFetch<T>(path, { method: "DELETE" }),
};
