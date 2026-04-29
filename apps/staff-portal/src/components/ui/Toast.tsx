import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { Icon } from "../Icon";

type ToastVariant = "info" | "success" | "warning" | "error";

interface Toast {
  id: number;
  variant: ToastVariant;
  title: string;
  body?: string;
  durationMs: number;
}

interface ToastContextValue {
  push(t: Omit<Toast, "id" | "durationMs"> & { durationMs?: number }): void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

const variantStyles: Record<ToastVariant, { bar: string; icon: "check-circle" | "alert" | "x-mark" }> = {
  info: { bar: "border-blue-300 bg-blue-50 text-blue-900", icon: "alert" },
  success: { bar: "border-green-300 bg-green-50 text-green-900", icon: "check-circle" },
  warning: { bar: "border-amber-300 bg-amber-50 text-amber-900", icon: "alert" },
  error: { bar: "border-red-300 bg-red-50 text-red-900", icon: "x-mark" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const idRef = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((curr) => curr.filter((t) => t.id !== id));
  }, []);

  const push: ToastContextValue["push"] = useCallback((t) => {
    const id = ++idRef.current;
    const toast: Toast = {
      id,
      variant: t.variant,
      title: t.title,
      body: t.body,
      durationMs: t.durationMs ?? 5000,
    };
    setToasts((curr) => [...curr, toast]);
  }, []);

  const value = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      <ToastViewport toasts={toasts} onDismiss={dismiss} />
    </ToastContext.Provider>
  );
}

// Soft no-op when no provider is mounted — keeps components that opportunistically
// fire toasts from crashing the tree (e.g. test renders that don't wrap in
// ToastProvider). Real provider always supplies the live push().
const NOOP_TOAST: ToastContextValue = { push: () => {} };

export function useToast(): ToastContextValue {
  return useContext(ToastContext) ?? NOOP_TOAST;
}

function ToastViewport({
  toasts,
  onDismiss,
}: {
  toasts: Toast[];
  onDismiss(id: number): void;
}) {
  return (
    <div
      aria-live="polite"
      aria-atomic="true"
      className="pointer-events-none fixed bottom-4 right-4 z-[100] flex w-full max-w-sm flex-col gap-2"
    >
      {toasts.map((t) => (
        <ToastCard key={t.id} toast={t} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastCard({ toast, onDismiss }: { toast: Toast; onDismiss(id: number): void }) {
  const { id, variant, title, body, durationMs } = toast;
  useEffect(() => {
    const handle = window.setTimeout(() => onDismiss(id), durationMs);
    return () => window.clearTimeout(handle);
  }, [id, durationMs, onDismiss]);

  const style = variantStyles[variant];
  return (
    <div
      role="status"
      className={`pointer-events-auto flex items-start gap-3 rounded-lg border px-3 py-2.5 shadow-md ${style.bar}`}
    >
      <Icon name={style.icon} className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="text-sm font-semibold">{title}</div>
        {body && <div className="mt-0.5 text-xs opacity-90 break-words">{body}</div>}
      </div>
      <button
        type="button"
        onClick={() => onDismiss(id)}
        className="rounded p-1 text-current opacity-60 hover:opacity-100"
        aria-label="Dismiss notification"
      >
        <Icon name="x" className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}
