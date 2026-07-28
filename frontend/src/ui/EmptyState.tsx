import type { ReactNode } from "react";
import { Button, ButtonLink } from "./Button";
import { cn } from "./cn";

/**
 * Page- or section-level "you have nothing here yet" block. Every use should give
 * the reader a next step, so `action` is the norm rather than the exception — the
 * one fair exception is when the action genuinely lives outside the app.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  className,
}: {
  icon?: ReactNode;
  title: string;
  description?: ReactNode;
  action?: { label: string; to?: string; onClick?: () => void };
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center rounded-card border border-dashed border-slate-300",
        "bg-surface px-6 py-10 text-center",
        className,
      )}
    >
      {icon && <div className="mb-3 text-3xl leading-none">{icon}</div>}
      <p className="font-medium text-slate-800">{title}</p>
      {description && (
        <p className="mt-1 max-w-md text-sm text-slate-500">{description}</p>
      )}
      {action && (
        <div className="mt-4">
          {action.to ? (
            <ButtonLink to={action.to} variant="primary">
              {action.label}
            </ButtonLink>
          ) : (
            <Button onClick={action.onClick}>{action.label}</Button>
          )}
        </div>
      )}
    </div>
  );
}
