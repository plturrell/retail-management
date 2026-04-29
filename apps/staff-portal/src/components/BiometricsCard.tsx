/**
 * Biometric / passkey management card for the Profile page.
 *
 * Lets the signed-in user:
 *   1. Register a new passkey (Face ID / Touch ID / Windows Hello / Android
 *      fingerprint / security key) for this device.
 *   2. List all their registered passkeys with "last used" timestamps.
 *   3. Remove a lost / stale one.
 *
 * Uses @simplewebauthn/browser which handles the base64url <-> ArrayBuffer
 * conversions required by the WebAuthn APIs; we just hand it the options
 * object the backend produced.
 */
import { useEffect, useState } from "react";
import { browserSupportsWebAuthn, startRegistration } from "@simplewebauthn/browser";
import { api } from "../lib/api";
import ConfirmDialog from "./ConfirmDialog";

interface Credential {
  id: string;
  name: string;
  transports: string[];
  created_at: string | null;
  last_used_at: string | null;
}

interface RegisterStart {
  options: Record<string, unknown>;
  challenge_id: string;
}

function defaultDeviceName(): string {
  // Best-effort nickname so the list is readable without forcing the user to
  // type one. They can still rename via the prompt.
  const ua = navigator.userAgent;
  if (/iPhone/i.test(ua)) return "iPhone";
  if (/iPad/i.test(ua)) return "iPad";
  if (/Android/i.test(ua)) return "Android phone";
  if (/Macintosh/i.test(ua)) return "Mac";
  if (/Windows/i.test(ua)) return "Windows PC";
  if (/Linux/i.test(ua)) return "Linux PC";
  return "This device";
}

function relTime(iso: string | null): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 2) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs} hr ago`;
  const days = Math.round(hrs / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return d.toLocaleDateString();
}

export default function BiometricsCard() {
  const [supported] = useState(browserSupportsWebAuthn());
  const [creds, setCreds] = useState<Credential[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [msg, setMsg] = useState("");
  const [pendingRemove, setPendingRemove] = useState<Credential | null>(null);

  const load = async () => {
    setErr("");
    try {
      const res = await api.get<{ data: Credential[] }>("/webauthn/credentials");
      setCreds(res.data);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not load passkeys");
    }
  };

  useEffect(() => { void load(); }, []);

  const register = async () => {
    setErr(""); setMsg("");
    const suggested = defaultDeviceName();
    const name = window.prompt("Name this device (shown in your passkey list):", suggested) || suggested;
    setBusy(true);
    try {
      // 1. Ask the server for registration options + a scoped challenge.
      const start = await api.post<RegisterStart>("/webauthn/register/start", {});
      // 2. Invoke the browser's passkey flow (triggers Face ID / Touch ID /
      //    platform chooser). @simplewebauthn handles all b64/ArrayBuffer
      //    conversions for us.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const attestation = await startRegistration(start.options as any);
      // 3. Send the attestation back; server verifies + persists.
      await api.post<{ data: Credential }>("/webauthn/register/finish", {
        challenge_id: start.challenge_id,
        credential: attestation,
        name,
      });
      setMsg(`${name} registered. You can now sign in with biometrics.`);
      await load();
    } catch (e) {
      // Users who cancel the native prompt produce a specific DOMException
      // shape we don't want to log as an error.
      const m = e instanceof Error ? e.message : String(e);
      if (/cancell|NotAllowed/i.test(m)) {
        setErr("Registration was cancelled.");
      } else {
        setErr(m);
      }
    } finally {
      setBusy(false);
    }
  };

  const remove = async (c: Credential) => {
    setPendingRemove(null);
    setBusy(true);
    setErr(""); setMsg("");
    try {
      await api.delete<{ ok: boolean }>(`/webauthn/credentials/${encodeURIComponent(c.id)}`);
      setMsg(`Removed "${c.name}"`);
      await load();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not remove");
    } finally {
      setBusy(false);
    }
  };

  if (!supported) {
    return (
      <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
        <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Biometric sign-in</h2>
        <p className="mt-2 text-xs text-gray-500">
          Your browser doesn't support passkeys. Try Chrome, Safari, Edge, or Firefox on a device with
          Face ID, Touch ID, Windows Hello, or a fingerprint sensor.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-lg border border-gray-200 bg-white p-5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div>
          <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Biometric sign-in</h2>
          <p className="mt-0.5 text-[11px] text-gray-500">
            Sign in with Face ID, Touch ID, Windows Hello, or a fingerprint sensor — no password typing.
            One passkey per device.
          </p>
        </div>
        <button
          type="button"
          onClick={register}
          disabled={busy}
          className="shrink-0 rounded bg-blue-600 px-2.5 py-1 text-[11px] font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {busy ? "Working…" : "+ Register this device"}
        </button>
      </div>

      {err && <div className="mb-2 rounded border border-red-200 bg-red-50 px-2 py-1 text-xs text-red-700">{err}</div>}
      {msg && <div className="mb-2 rounded border border-green-200 bg-green-50 px-2 py-1 text-xs text-green-700">{msg}</div>}

      {creds === null ? (
        <div className="text-xs text-gray-400">Loading…</div>
      ) : creds.length === 0 ? (
        <div className="rounded border border-dashed border-gray-200 px-3 py-4 text-center text-xs text-gray-500">
          No passkeys registered yet. Tap <span className="font-semibold">Register this device</span> and approve the prompt to set one up.
        </div>
      ) : (
        <ul className="divide-y divide-gray-100 text-sm">
          {creds.map((c) => (
            <li key={c.id} className="flex items-center justify-between gap-3 py-2">
              <div className="min-w-0">
                <div className="font-medium text-gray-800">{c.name}</div>
                <div className="mt-0.5 text-[11px] text-gray-500">
                  Added {relTime(c.created_at)} · Last used {relTime(c.last_used_at)}
                  {c.transports.length > 0 && <> · {c.transports.join(", ")}</>}
                </div>
              </div>
              <button
                onClick={() => setPendingRemove(c)}
                disabled={busy}
                className="shrink-0 rounded border border-gray-200 px-2 py-1 text-[11px] font-medium text-gray-600 hover:border-red-300 hover:text-red-600 disabled:opacity-40"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={pendingRemove !== null}
        title={`Remove ${pendingRemove?.name ?? "passkey"}?`}
        body="This device will no longer be able to use that passkey for biometric sign-in until it is registered again."
        confirmLabel="Remove passkey"
        tone="danger"
        busy={busy}
        onCancel={() => setPendingRemove(null)}
        onConfirm={() => pendingRemove && void remove(pendingRemove)}
      />
    </div>
  );
}
