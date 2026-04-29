import type { ReactNode } from "react";

export function EmptyState({
  icon,
  title,
  description,
  action,
}: {
  icon?: ReactNode;
  title: string;
  description?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[14px] border border-dashed border-[var(--color-border-strong)] bg-[var(--color-surface)] px-6 py-12 text-center">
      {icon && (
        <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-full bg-[var(--color-surface-subtle)] text-[var(--color-ink-muted)]">
          {icon}
        </div>
      )}
      <p className="text-sm font-semibold text-[var(--color-ink-primary)]">{title}</p>
      {description && (
        <p className="mt-1 max-w-xs text-sm text-[var(--color-ink-muted)]">{description}</p>
      )}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}
