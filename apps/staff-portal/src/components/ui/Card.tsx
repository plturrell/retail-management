import type { HTMLAttributes, ReactNode } from "react";
import { classNames } from "../../lib/format";

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  padding?: "none" | "sm" | "md" | "lg";
  elevated?: boolean;
  children: ReactNode;
}

const paddingMap = {
  none: "",
  sm: "p-3",
  md: "p-4",
  lg: "p-5 sm:p-6",
};

export function Card({ padding = "md", elevated, className, children, ...rest }: CardProps) {
  return (
    <div
      className={classNames(
        "rounded-[14px] border border-[var(--color-border)] bg-[var(--color-surface)]",
        elevated ? "shadow-[var(--shadow-elevated)]" : "shadow-[var(--shadow-card)]",
        paddingMap[padding],
        className,
      )}
      {...rest}
    >
      {children}
    </div>
  );
}
