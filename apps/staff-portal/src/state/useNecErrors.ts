import { useCallback, useEffect, useRef, useState } from "react";
import type { CagErrorEntry } from "../lib/master-data-api";
import { useToast } from "../components/ui/Toast";

// Lazily resolve the cag API so importing this hook (e.g. transitively from
// AppShell) doesn't pull `lib/firebase` into module load — vitest suites that
// mock AuthContext but not firebase rely on this to keep passing.
async function loadCagExportApi() {
  const mod = await import("../lib/master-data-api");
  return mod.cagExportApi;
}

const ACK_STORAGE_KEY = "nec.errors.acked.v1";
const POLL_INTERVAL_MS = 60_000;

function entryId(e: CagErrorEntry): string {
  return `${e.source_file ?? "inline"}:${e.line}:${e.message}`;
}

function loadAcked(): Set<string> {
  try {
    const raw = window.localStorage.getItem(ACK_STORAGE_KEY);
    if (!raw) return new Set();
    const arr = JSON.parse(raw) as unknown;
    return new Set(Array.isArray(arr) ? arr.filter((x): x is string => typeof x === "string") : []);
  } catch {
    return new Set();
  }
}

function saveAcked(acked: Set<string>) {
  try {
    window.localStorage.setItem(ACK_STORAGE_KEY, JSON.stringify(Array.from(acked)));
  } catch {
    // localStorage can throw in private mode / when full — degrade silently.
  }
}

export interface UseNecErrorsResult {
  errors: CagErrorEntry[];
  unacked: CagErrorEntry[];
  unackedCount: number;
  loading: boolean;
  /** Last error from the polling fetch, surfaced for diagnostics. */
  fetchError: string | null;
  /**
   * True once the backend has reported the CAG SFTP isn't configured (HTTP
   * 503 from ``/api/cag/export/errors``). Polling stops until the page is
   * reloaded so we don't spam the console once a minute on dev boxes.
   */
  notConfigured: boolean;
  ackAll(): void;
  refresh(): Promise<void>;
}

// `cagRequest` throws ``new Error(\`API ${status}: ${body}\`)`` so the status
// is recoverable from the message without changing the error contract.
const NOT_CONFIGURED_RE = /^API 503:/;

function isNotConfiguredError(err: unknown): boolean {
  const msg = err instanceof Error ? err.message : String(err);
  return NOT_CONFIGURED_RE.test(msg);
}

/**
 * Polls ``GET /api/cag/export/errors`` every 60s, tracks per-entry ack state in
 * localStorage so the badge survives reloads, and fires a toast the first time
 * a never-before-seen entry appears. Used by the header bell.
 *
 * Pass ``enabled=false`` to short-circuit polling for users who shouldn't see
 * NEC errors (e.g. non-owner roles); the hook still returns a stable shape.
 */
export function useNecErrors(enabled: boolean): UseNecErrorsResult {
  const toast = useToast();
  const [errors, setErrors] = useState<CagErrorEntry[]>([]);
  const [acked, setAcked] = useState<Set<string>>(loadAcked);
  const [loading, setLoading] = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [notConfigured, setNotConfigured] = useState(false);
  // Tracks ids we've already toasted on this mount so a brief network blip
  // doesn't fire the same toast on every poll.
  const toastedRef = useRef<Set<string>>(new Set());
  // Tracks the previous poll's id set to detect what's truly new across polls.
  const lastSeenRef = useRef<Set<string> | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled || notConfigured) return;
    setLoading(true);
    try {
      const cagExportApi = await loadCagExportApi();
      const next = await cagExportApi.errors(50);
      setErrors(next);
      setFetchError(null);

      // Toast only entries that are: (a) not previously acked,
      // (b) new since the last successful poll, (c) not yet toasted this session.
      const nextIds = new Set(next.map(entryId));
      const ackedNow = acked;
      const lastSeen = lastSeenRef.current;
      if (lastSeen) {
        for (const e of next) {
          const id = entryId(e);
          if (lastSeen.has(id)) continue;
          if (ackedNow.has(id)) continue;
          if (toastedRef.current.has(id)) continue;
          toastedRef.current.add(id);
          toast.push({
            variant: e.status.toLowerCase() === "failed" ? "error" : "warning",
            title: `NEC ${e.status} — line ${e.line}`,
            body: e.message,
          });
        }
      }
      lastSeenRef.current = nextIds;
    } catch (err) {
      // 503 from the endpoint means CAG SFTP isn't configured on this
      // backend — that's a deployment state, not a transient fetch error.
      // Latch into a terminal "not configured" mode (cleared on reload) so
      // the polling effect tears down and the bell shows an empty state
      // instead of a misleading red strip.
      if (isNotConfiguredError(err)) {
        setErrors([]);
        setFetchError(null);
        setNotConfigured(true);
        return;
      }
      setFetchError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [enabled, notConfigured, acked, toast]);

  // Initial fetch + 60s polling, restarted whenever ``enabled`` flips.
  // Once ``notConfigured`` latches true the interval tears down for the
  // remainder of the page lifetime — a hard reload is the recovery path.
  useEffect(() => {
    if (!enabled || notConfigured) return;
    void refresh();
    const handle = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(handle);
  }, [enabled, notConfigured, refresh]);

  const ackAll = useCallback(() => {
    setAcked((prev) => {
      const next = new Set(prev);
      for (const e of errors) next.add(entryId(e));
      saveAcked(next);
      return next;
    });
  }, [errors]);

  const unacked = errors.filter((e) => !acked.has(entryId(e)));

  return {
    errors,
    unacked,
    unackedCount: unacked.length,
    loading,
    fetchError,
    notConfigured,
    ackAll,
    refresh,
  };
}
