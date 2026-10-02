import {
  cloneElement,
  forwardRef,
  isValidElement,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactElement,
  type ReactNode,
  type SelectHTMLAttributes,
  type TextareaHTMLAttributes,
} from "react";
import { Loader2, Upload } from "lucide-react";

/* Form and action primitives. Before these existed every page hand-rolled its
   own button and input classes — ten variants of the primary button alone —
   so the same action looked different from one screen to the next. Pages
   compose these instead of restating the classes. */

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
export type ButtonSize = "sm" | "md" | "lg";

const VARIANTS: Record<ButtonVariant, string> = {
  primary: "bg-brand-600 text-canvas shadow-[0_1px_0_rgba(44,26,14,0.12)] hover:bg-brand-700",
  // `avora-control` carries the edge colour — see index.css for why a
  // `border-line-control` utility cannot.
  secondary: "avora-control border bg-surface text-ink-900",
  ghost: "text-ink-700 hover:bg-surface-muted hover:text-ink-900",
  danger: "bg-risk-600 text-canvas hover:opacity-90",
};

const SIZES: Record<ButtonSize, string> = {
  sm: "h-8 gap-1.5 px-3 text-sm",
  md: "h-10 gap-2 px-4 text-sm",
  lg: "h-11 gap-2 px-5 text-[15px]",
};

/** The classes for a button, so a `<Link>` can look like one without nesting. */
export function buttonClasses(
  variant: ButtonVariant = "primary",
  size: ButtonSize = "md",
  extra = "",
): string {
  return `inline-flex shrink-0 items-center justify-center rounded-md font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${VARIANTS[variant]} ${SIZES[size]} ${extra}`;
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  size?: ButtonSize;
  /** Shows a spinner and blocks a second click while a request is in flight. */
  loading?: boolean;
};

/** Forwards its ref, so a page can move focus to a button it just revealed. */
export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  {
    variant = "primary",
    size = "md",
    loading = false,
    className = "",
    children,
    disabled,
    type = "button",
    ...rest
  },
  ref,
) {
  return (
    <button
      ref={ref}
      type={type}
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={buttonClasses(variant, size, className)}
      {...rest}
    >
      {loading && <Loader2 aria-hidden className="h-4 w-4 animate-spin" />}
      {children}
    </button>
  );
});

const CONTROL =
  "avora-control rounded-md border bg-surface px-3 text-sm text-ink-900 transition-colors placeholder:text-ink-500 disabled:cursor-not-allowed disabled:bg-surface-muted";

/**
 * Default sizing a caller can override. Without tailwind-merge, two width
 * utilities on one element resolve by their order in the generated CSS, not
 * the order written — so `w-full` from here could silently beat a caller's
 * `w-24`. A default is dropped when the caller supplies the same dimension.
 */
function sized(defaults: string, className: string): string {
  const has = (prefix: string) =>
    className.split(/\s+/).some((c) => c.replace(/^[a-z]+:/, "").startsWith(prefix));
  return defaults
    .split(" ")
    .filter((d) => {
      if (d.startsWith("w-")) return !has("w-");
      if (d.startsWith("min-h-")) return !has("min-h-");
      if (d.startsWith("h-")) return !has("h-");
      return true;
    })
    .join(" ");
}

export const inputClasses = `h-10 w-full ${CONTROL}`;

export function Input({ className = "", ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input className={`${sized("h-10 w-full", className)} ${CONTROL} ${className}`} {...rest} />
  );
}

export function Select({ className = "", ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      className={`${sized("h-10 w-full", className)} appearance-none bg-[url('data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 20 20%22 fill=%22%23786351%22><path d=%22M5.3 7.3a1 1 0 0 1 1.4 0L10 10.6l3.3-3.3a1 1 0 1 1 1.4 1.4l-4 4a1 1 0 0 1-1.4 0l-4-4a1 1 0 0 1 0-1.4z%22/></svg>')] bg-[length:1.1rem] bg-[right_0.6rem_center] bg-no-repeat pr-9 ${CONTROL} ${className}`}
      {...rest}
    />
  );
}

export function Textarea({ className = "", ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      className={`${sized("min-h-[5rem] w-full", className)} resize-y py-2 ${CONTROL} ${className}`}
      {...rest}
    />
  );
}

/**
 * A labelled form field. The label is tied to its control by id, so clicking
 * the label focuses the field and a screen reader announces it — before this,
 * most forms had a visual label with nothing connecting it to the input.
 */
export function Field({
  label,
  hint,
  error,
  optional,
  className = "",
  children,
}: {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  optional?: boolean;
  className?: string;
  children: ReactElement<{ id?: string; "aria-describedby"?: string; "aria-invalid"?: boolean }>;
}) {
  const id = useId();
  const hintId = `${id}-hint`;
  const errorId = `${id}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ");
  const control = isValidElement(children)
    ? cloneElement(children, {
        id: children.props.id ?? id,
        "aria-describedby": describedBy || undefined,
        "aria-invalid": error ? true : undefined,
      })
    : children;
  return (
    <div className={className}>
      <label htmlFor={children.props.id ?? id} className="block text-sm font-medium text-ink-900">
        {label}
        {optional && <span className="ml-1 font-normal text-ink-500">(optional)</span>}
      </label>
      <div className="mt-1.5">{control}</div>
      {hint && !error && (
        <p id={hintId} className="mt-1.5 text-xs text-ink-500">
          {hint}
        </p>
      )}
      {error && (
        <p id={errorId} role="alert" className="mt-1.5 text-xs text-risk-600">
          {error}
        </p>
      )}
    </div>
  );
}

/**
 * A file picker that looks like part of the product rather than the browser's
 * "Choose File · No file chosen". The real input stays in the DOM (visually
 * hidden, still focusable through the label) so keyboard and screen-reader use
 * is unchanged.
 */
export function FileInput({
  accept,
  multiple,
  onFiles,
  prompt = "Choose a file",
  hint,
  id,
  disabled,
  "aria-describedby": describedBy,
  "aria-invalid": invalid,
}: {
  "aria-describedby"?: string;
  "aria-invalid"?: boolean;
  accept?: string;
  multiple?: boolean;
  onFiles: (files: File[]) => void;
  prompt?: string;
  hint?: string;
  id?: string;
  disabled?: boolean;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const [names, setNames] = useState<string[]>([]);
  const fallbackId = useId();
  const inputId = id ?? fallbackId;
  return (
    <label
      htmlFor={inputId}
      className={`avora-control flex min-h-10 cursor-pointer items-center gap-3 rounded-md border border-dashed bg-surface px-3 py-2 text-sm transition-colors hover:bg-brand-50 focus-within:outline focus-within:outline-2 focus-within:outline-offset-2 focus-within:outline-brand-600 ${disabled ? "pointer-events-none opacity-50" : ""}`}
    >
      <Upload aria-hidden className="h-4 w-4 shrink-0 text-brand-600" />
      <span className="min-w-0 flex-1">
        <span className="block truncate font-medium text-ink-900">
          {names.length === 0
            ? prompt
            : names.length === 1
              ? names[0]
              : `${names.length} files selected`}
        </span>
        {hint && <span className="block text-xs text-ink-500">{hint}</span>}
      </span>
      <input
        ref={ref}
        id={inputId}
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        aria-describedby={describedBy}
        aria-invalid={invalid}
        className="sr-only"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          setNames(files.map((f) => f.name));
          onFiles(files);
        }}
      />
    </label>
  );
}
