import type { ReactNode } from "react";
import { cn } from "./cn";

/** The standard surface for a block of content. */
export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-card border border-slate-200 bg-surface shadow-card", className)}>
      {children}
    </div>
  );
}

/**
 * Card header with a title and optional trailing actions — the
 * "heading on the left, buttons on the right" row repeated across the app.
 */
export function CardHeader({
  title,
  description,
  actions,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4">
      <div className="min-w-0">
        <h3 className="font-semibold text-slate-900">{title}</h3>
        {description && <p className="mt-0.5 text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("px-5 py-4", className)}>{children}</div>;
}
