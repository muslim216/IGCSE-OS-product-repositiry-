import type { ReactNode } from "react";
import { cn } from "./cn";

type Tone = "neutral" | "brand" | "ready" | "caution" | "risk";

const TONES: Record<Tone, string> = {
  neutral: "bg-surface-muted text-slate-600",
  brand: "bg-brand-50 text-brand-700",
  ready: "bg-ready-50 text-ready-600",
  caution: "bg-caution-50 text-caution-600",
  risk: "bg-risk-50 text-risk-600",
};

export function Badge({
  tone = "neutral",
  className,
  children,
}: {
  tone?: Tone;
  className?: string;
  children: ReactNode;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

/** Small count pill for "N awaiting review"-style signals. Renders nothing at zero. */
export function CountBadge({ count, tone = "brand" }: { count: number; tone?: Tone }) {
  if (count <= 0) return null;
  return <Badge tone={tone}>{count}</Badge>;
}
