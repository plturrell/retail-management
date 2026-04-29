import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CheckCircle2, AlertCircle, X } from "lucide-react";
import { classNames } from "../../lib/format";

type ToastTone = "success" | "error" | "info";
interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastContextValue {
  show: (message: string, tone?: ToastTone) => void;
}

const ToastContext = createContext<ToastContextValue | undefined>(undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const show = useCallback((message: string, tone: ToastTone = "info") => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t, { id, tone, message }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 3500);
  }, []);

  const dismiss = (id: number) => setToasts((t) => t.filter((x) => x.id !== id));

  return (
    <ToastContext.Provider value={{ show }}>
      {children}
      <div className="pointer-events-none fixed inset-x-0 top-3 z-[60] flex flex-col items-center gap-2 px-4 safe-top sm:top-5">
        {toasts.map((t) => (
          <ToastItem key={t.id} toast={t} onDismiss={() => dismiss(t.id)} />
        ))}
      </div>
    </ToastContext.Provider>
  );
}

function ToastItem({ toast, onDismiss }: { toast: Toast; onDismiss: () => void }) {
  const Icon = toast.tone === "success" ? CheckCircle2 : toast.tone === "error" ? AlertCircle : CheckCircle2;
  return (
    <div
      className={classNames(
        "pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-2xl border px-4 py-3 shadow-[var(--shadow-floating)]",
        "animate-rise backdrop-blur-md",
        toast.tone === "success" && "border-[var(--color-positive-600)]/20 bg-white/95 text-[var(--color-ink-primary)]",
        toast.tone === "error" && "border-[var(--color-negative-600)]/20 bg-white/95 text-[var(--color-ink-primary)]",
        toast.tone === "info" && "border-[var(--color-border)] bg-white/95 text-[var(--color-ink-primary)]",
      )}
      role="status"
    >
      <Icon
        size={20}
        strokeWidth={2.25}
        className={
          toast.tone === "success"
            ? "shrink-0 text-[var(--color-positive-600)]"
            : toast.tone === "error"
            ? "shrink-0 text-[var(--color-negative-600)]"
            : "shrink-0 text-[var(--color-brand-600)]"
        }
      />
      <p className="flex-1 text-sm font-medium leading-tight">{toast.message}</p>
      <button
        aria-label="Dismiss"
        onClick={onDismiss}
        className="shrink-0 rounded-md text-[var(--color-ink-muted)] hover:text-[var(--color-ink-primary)]"
      >
        <X size={16} />
      </button>
    </div>
  );
}

export function useToast() {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToast must be used within ToastProvider");
  return ctx;
}

