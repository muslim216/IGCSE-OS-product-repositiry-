import type { SelectHTMLAttributes } from "react";
import { cn } from "./cn";

export interface SelectOption<T extends string | number = string> {
  value: T;
  label: string;
}

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, "size"> {
  /** Render options from data instead of children. */
  options?: SelectOption<string | number>[];
  invalid?: boolean;
}

/**
 * A native <select> with the platform arrow replaced by our own chevron, so it
 * matches the rest of the controls while keeping native keyboard and mobile
 * behaviour. Pass `options` for simple lists or `children` for grouped markup.
 */
export function Select({ options, invalid, className, children, ...props }: SelectProps) {
  return (
    <select
      {...props}
      aria-invalid={invalid || undefined}
      className={cn(
        "select-chevron h-10 w-full rounded-control border bg-surface px-3 text-sm text-slate-800",
        "transition-colors hover:border-slate-400",
        "disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-slate-400",
        invalid ? "border-risk-500" : "border-slate-300",
        className,
      )}
    >
      {options
        ? options.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))
        : children}
    </select>
  );
}
