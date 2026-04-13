import { AlertTriangle, CheckCircle2, Info } from "lucide-react";

import { cn } from "@/lib/utils";

interface NoticeBannerProps {
  tone: "notice" | "error" | "warning";
  message: string;
}

export function NoticeBanner({ tone, message }: NoticeBannerProps) {
  const Icon = tone === "error" ? AlertTriangle : tone === "warning" ? Info : CheckCircle2;

  return (
    <div
      className={cn(
        "flex items-start gap-3 rounded-xl border px-4 py-3 text-sm",
        tone === "notice" && "border-emerald-200 bg-emerald-50 text-emerald-800",
        tone === "warning" && "border-amber-200 bg-amber-50 text-amber-800",
        tone === "error" && "border-rose-200 bg-rose-50 text-rose-800"
      )}
    >
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <p>{message}</p>
    </div>
  );
}