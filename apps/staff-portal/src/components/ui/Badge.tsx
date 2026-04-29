import type { ReactNode } from "react";
import { classNames } from "../../lib/format";

type Tone = "neutral" | "brand" | "positive" | "warning" | "negative";

const toneMap: Record<Tone, string> = {
  neutral: "bg-[var(--color-surface-subtle)] text-[var(--color-ink-secondary)]",
  brand: "bg-[var(--color-brand-50)] text-[var(--color-brand-700)]",
  positive: "bg-[var(--color-positive-50)] text-[var(--color-positive-700)]",
  warning: "bg-[var(--color-warning-50)] text-[var(--color-warning-700)]",
  negative: "bg-[var(--color-negative-50)] text-[var(--color-negative-700)]",
};

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: ReactNode;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={classNames(
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold",
        toneMap[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
