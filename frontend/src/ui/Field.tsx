import type { InputHTMLAttributes, ReactNode, TextareaHTMLAttributes } from "react";
import { useId } from "react";
import { cn } from "./cn";

const CONTROL =
  "w-full rounded-control border bg-surface px-3 text-sm text-slate-800 transition-colors " +
  "placeholder:text-slate-400 hover:border-slate-400 " +
  "disabled:cursor-not-allowed disabled:bg-surface-muted disabled:text-slate-400";

/** Shared control styling, exported so bespoke inputs can match without copying classes. */
export const controlClass = cn(CONTROL, "h-10 border-slate-300");

/** Label + control + hint/error wrapper. Wires the label and description ids for you. */
export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label: string;
  hint?: string;
  error?: string;
  children: (props: { id: string; "aria-describedby"?: string }) => ReactNode;
  className?: string;
}) {
  const id = useId();
  const noteId = error || hint ? `${id}-note` : undefined;
  return (
    <div className={cn("min-w-0", className)}>
      <label htmlFor={id} className="mb-1 block text-sm font-medium text-slate-700">
        {label}
      </label>
      {children({ id, "aria-describedby": noteId })}
      {(error || hint) && (
        <p id={noteId} className={cn("mt-1 text-xs", error ? "text-risk-600" : "text-slate-500")}>
          {error || hint}
        </p>
      )}
    </div>
  );
}

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  invalid?: boolean;
}

export function Input({ invalid, className, ...props }: InputProps) {
  return (
    <input
      {...props}
      aria-invalid={invalid || undefined}
      className={cn(CONTROL, "h-10", invalid ? "border-risk-500" : "border-slate-300", className)}
    />
  );
}

export function Textarea({
  className,
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(CONTROL, "border-slate-300 py-2", className)} />;
}
