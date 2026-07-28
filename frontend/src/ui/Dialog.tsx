import { useEffect, useRef, type ReactNode } from "react";
import { Button } from "./Button";

/**
 * Modal built on <dialog>, so focus trapping, Escape handling and the top layer
 * come from the platform. Replaces the window.prompt/confirm calls the tutor
 * pages were using.
 */
export function Dialog({
  open,
  onClose,
  title,
  description,
  children,
  footer,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  footer?: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => {
        // Clicks land on the backdrop only when the target is the dialog itself.
        if (e.target === ref.current) onClose();
      }}
      className="w-[min(30rem,calc(100vw-2rem))] rounded-card border border-slate-200 p-0 shadow-pop backdrop:bg-slate-900/40"
    >
      <div className="px-5 py-4">
        <h2 className="font-semibold text-slate-900">{title}</h2>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
        {children && <div className="mt-4">{children}</div>}
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-200 bg-surface-sunken px-5 py-3">
        {footer ?? (
          <Button variant="secondary" onClick={onClose}>
            Close
          </Button>
        )}
      </div>
    </dialog>
  );
}

/** Confirmation with a destructive primary action — the confirm() replacement. */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  description,
  confirmLabel = "Confirm",
  pending,
}: {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  pending?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title={title}
      description={description}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={pending}>
            {pending ? "Working…" : confirmLabel}
          </Button>
        </>
      }
    />
  );
}
