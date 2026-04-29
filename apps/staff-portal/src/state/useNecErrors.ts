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
  ackAll(): void;
  refresh(): Promise<void>;
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
  // Tracks ids we've already toasted on this mount so a brief network blip
  // doesn't fire the same toast on every poll.
  const toastedRef = useRef<Set<string>>(new Set());
  // Tracks the previous poll's id set to detect what's truly new across polls.
  const lastSeenRef = useRef<Set<string> | null>(null);

  const refresh = useCallback(async () => {
    if (!enabled) return;
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
      setFetchError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [enabled, acked, toast]);

  // Initial fetch + 60s polling, restarted whenever ``enabled`` flips.
  useEffect(() => {
    if (!enabled) return;
    void refresh();
    const handle = window.setInterval(() => {
      void refresh();
    }, POLL_INTERVAL_MS);
    return () => window.clearInterval(handle);
  }, [enabled, refresh]);

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
    ackAll,
    refresh,
  };
}
