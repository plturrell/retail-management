import type { ButtonHTMLAttributes, ReactNode } from "react";
import { classNames } from "../../lib/format";

type Variant = "primary" | "secondary" | "ghost" | "danger" | "success";
type Size = "sm" | "md" | "lg";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  fullWidth?: boolean;
  leadingIcon?: ReactNode;
}

const variantMap: Record<Variant, string> = {
  primary:
    "bg-[var(--color-brand-600)] text-white hover:bg-[var(--color-brand-700)] active:bg-[var(--color-brand-700)] shadow-sm",
  secondary:
    "bg-[var(--color-surface)] text-[var(--color-ink-primary)] border border-[var(--color-border)] hover:bg-[var(--color-surface-subtle)]",
  ghost:
    "bg-transparent text-[var(--color-ink-secondary)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink-primary)]",
  danger:
    "bg-[var(--color-negative-600)] text-white hover:bg-[var(--color-negative-700)] shadow-sm",
  success:
    "bg-[var(--color-positive-600)] text-white hover:bg-[var(--color-positive-700)] shadow-sm",
};

const sizeMap: Record<Size, string> = {
  sm: "h-9 px-3 text-sm rounded-lg",
  md: "h-11 px-4 text-sm rounded-xl",
  lg: "h-12 px-5 text-base rounded-2xl",
};

export function Button({
  variant = "primary",
  size = "md",
  fullWidth,
  leadingIcon,
  className,
  children,
  ...rest
}: ButtonProps) {
  return (
    <button
      className={classNames(
        "inline-flex items-center justify-center gap-2 font-semibold",
        "transition-all duration-150 active:scale-[0.98]",
        "disabled:opacity-50 disabled:pointer-events-none",
        variantMap[variant],
        sizeMap[size],
        fullWidth && "w-full",
        className,
      )}
      {...rest}
    >
      {leadingIcon}
      {children}
    </button>
  );
}

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  variant?: "ghost" | "secondary";
}

export function IconButton({
  label,
  variant = "ghost",
  className,
  children,
  ...rest
}: IconButtonProps) {
  return (
    <button
      aria-label={label}
      className={classNames(
        "inline-flex h-11 w-11 items-center justify-center rounded-full transition-all",
        "active:scale-[0.94] disabled:opacity-50",
        variant === "ghost"
          ? "text-[var(--color-ink-secondary)] hover:bg-[var(--color-surface-subtle)] hover:text-[var(--color-ink-primary)]"
          : "border border-[var(--color-border)] bg-[var(--color-surface)] text-[var(--color-ink-secondary)] hover:bg-[var(--color-surface-subtle)]",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
}
