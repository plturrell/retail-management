import { useEffect, useRef, useState } from "react";
import { Icon } from "../Icon";
import { useAuth } from "../../contexts/AuthContext";
import { useNecErrors } from "../../state/useNecErrors";

/**
 * Header notification bell. Polls NEC SFTP error logs in the background and
 * surfaces a count badge + popover with the unacked entries. Owner-only:
 * non-owners see nothing (the bell is not even rendered).
 */
export function Bell() {
  const { isOwner } = useAuth();
  const { errors, unackedCount, fetchError, ackAll } = useNecErrors(isOwner);
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement | null>(null);

  // Click-outside to close.
  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handle);
    return () => document.removeEventListener("mousedown", handle);
  }, [open]);

  if (!isOwner) return null;

  return (
    <div className="relative" ref={popoverRef}>
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="relative rounded-md p-2 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
        aria-label={`NEC alerts (${unackedCount} unread)`}
        aria-expanded={open}
      >
        <Icon name="bell" className="h-5 w-5" />
        {unackedCount > 0 && (
          <span
            className="absolute -right-0.5 -top-0.5 inline-flex min-w-[1.1rem] items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-semibold leading-4 text-white"
            aria-hidden="true"
          >
            {unackedCount > 99 ? "99+" : unackedCount}
          </span>
        )}
      </button>

      {open && (
        <div className="absolute right-0 z-50 mt-2 w-80 origin-top-right rounded-lg border border-gray-200 bg-white shadow-lg">
          <div className="flex items-center justify-between border-b border-gray-100 px-3 py-2">
            <div className="text-sm font-semibold text-gray-700">NEC alerts</div>
            <button
              type="button"
              onClick={() => {
                ackAll();
                setOpen(false);
              }}
              disabled={unackedCount === 0}
              className="rounded-md px-2 py-1 text-xs font-medium text-blue-600 hover:bg-blue-50 disabled:cursor-not-allowed disabled:text-gray-400 disabled:hover:bg-transparent"
            >
              Mark all read
            </button>
          </div>
          <div className="max-h-80 overflow-y-auto">
            {fetchError && (
              <div className="px-3 py-2 text-xs text-amber-700">
                Couldn't load NEC errors: {fetchError}
              </div>
            )}
            {errors.length === 0 && !fetchError && (
              <div className="px-3 py-6 text-center text-xs text-gray-500">
                No NEC errors in the last cycle.
              </div>
            )}
            {errors.map((e, i) => (
              <div
                key={`${e.source_file ?? "inline"}:${e.line}:${i}`}
                className={`border-b border-gray-100 px-3 py-2 last:border-b-0 ${
                  e.status.toLowerCase() === "failed" ? "bg-red-50/40" : "bg-amber-50/40"
                }`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-block rounded-full px-1.5 py-0.5 text-[10px] font-semibold uppercase ${
                      e.status.toLowerCase() === "failed"
                        ? "bg-red-100 text-red-800"
                        : "bg-amber-100 text-amber-800"
                    }`}
                  >
                    {e.status}
                  </span>
                  <span className="text-[11px] text-gray-500">line {e.line}</span>
                </div>
                <div className="mt-1 break-words text-xs text-gray-700">{e.message}</div>
                {e.source_file && (
                  <div className="mt-0.5 truncate text-[10px] text-gray-400">{e.source_file}</div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
