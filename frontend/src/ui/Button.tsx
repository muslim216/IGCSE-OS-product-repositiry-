import type { ButtonHTMLAttributes } from "react";
import { Link } from "react-router-dom";
import { cn } from "./cn";

type Variant = "primary" | "secondary" | "ghost" | "danger";
type Size = "sm" | "md";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-brand-600 text-white hover:bg-brand-700 disabled:hover:bg-brand-600",
  secondary:
    "border border-slate-300 bg-surface text-slate-700 hover:border-slate-400 hover:bg-surface-muted",
  ghost: "text-slate-600 hover:bg-surface-muted hover:text-slate-900",
  danger: "border border-risk-500/40 bg-risk-50 text-risk-600 hover:bg-risk-500 hover:text-white",
};

const SIZES: Record<Size, string> = {
  sm: "h-8 px-3 text-sm",
  md: "h-10 px-4 text-sm",
};

function classesFor(variant: Variant, size: Size, className?: string): string {
  return cn(
    "inline-flex items-center justify-center gap-1.5 rounded-control font-medium transition-colors",
    "disabled:cursor-not-allowed disabled:opacity-50",
    VARIANTS[variant],
    SIZES[size],
    className,
  );
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
}

export function Button({ variant = "primary", size = "md", className, ...props }: ButtonProps) {
  return <button {...props} className={classesFor(variant, size, className)} />;
}

/** Same visual treatment as Button, but navigates. */
export function ButtonLink({
  to,
  variant = "secondary",
  size = "md",
  className,
  children,
}: {
  to: string;
  variant?: Variant;
  size?: Size;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <Link to={to} className={classesFor(variant, size, className)}>
      {children}
    </Link>
  );
}
