import { classNames } from "../../lib/format";

interface Segment<T extends string> {
  value: T;
  label: string;
}

export function SegmentedControl<T extends string>({
  segments,
  value,
  onChange,
  ariaLabel,
}: {
  segments: Segment<T>[];
  value: T;
  onChange: (v: T) => void;
  ariaLabel?: string;
}) {
  return (
    <div
      role="radiogroup"
      aria-label={ariaLabel}
      className="inline-flex gap-1 rounded-xl bg-[var(--color-surface-subtle)] p-1"
    >
      {segments.map((s) => {
        const active = s.value === value;
        return (
          <button
            key={s.value}
            role="radio"
            aria-checked={active}
            onClick={() => onChange(s.value)}
            className={classNames(
              "rounded-lg px-3.5 py-1.5 text-sm font-medium transition-all duration-200",
              active
                ? "bg-[var(--color-surface)] text-[var(--color-ink-primary)] shadow-[var(--shadow-card)]"
                : "text-[var(--color-ink-muted)] hover:text-[var(--color-ink-primary)]",
            )}
          >
            {s.label}
          </button>
        );
      })}
    </div>
  );
}
