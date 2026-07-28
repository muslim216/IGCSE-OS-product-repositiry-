import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { cn } from "./cn";

export interface TabItem {
  to: string;
  label: string;
  /** Rendered after the label — typically a CountBadge. */
  badge?: ReactNode;
  /** Match this path exactly. Use for the tab that sits on the parent route. */
  end?: boolean;
}

/**
 * Route-driven tabs. Each tab is a real URL so a section can be linked to,
 * bookmarked, and survives a refresh — which a useState tab index would not.
 */
export function Tabs({ items, className }: { items: TabItem[]; className?: string }) {
  return (
    <div className={cn("border-b border-slate-200", className)}>
      <nav className="-mb-px flex gap-1 overflow-x-auto" aria-label="Sections">
        {items.map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            className={({ isActive }) =>
              cn(
                "flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-sm transition-colors",
                isActive
                  ? "border-brand-600 font-medium text-brand-700"
                  : "border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-800",
              )
            }
          >
            {item.label}
            {item.badge}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}
