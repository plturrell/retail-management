import { classNames } from "../../lib/format";

export function Skeleton({ className }: { className?: string }) {
  return (
    <div
      className={classNames(
        "animate-shimmer rounded-md bg-[var(--color-surface-subtle)]",
        className,
      )}
    />
  );
}

export function CardSkeleton({ lines = 2 }: { lines?: number }) {
  return (
    <div className="rounded-[14px] border border-[var(--color-border)] bg-[var(--color-surface)] p-5 shadow-[var(--shadow-card)]">
      <Skeleton className="h-3 w-24" />
      <Skeleton className="mt-3 h-7 w-32" />
      {Array.from({ length: lines - 1 }).map((_, i) => (
        <Skeleton key={i} className="mt-2 h-3 w-16" />
      ))}
    </div>
  );
}
