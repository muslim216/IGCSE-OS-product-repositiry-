import { useState } from "react";
import type { Contact, NotificationChannel } from "../api/notifications";
import { CHANNEL_LABEL, contactState, suppressedLabel } from "../lib/notifications";
import { friendlyError } from "../lib/errors";
import { Button, Field, Input } from "./controls";

const PLACEHOLDER: Record<NotificationChannel, string> = {
  whatsapp: "+201001234567",
  email: "name@example.com",
};

const HINT: Record<NotificationChannel, string> = {
  whatsapp: "International format, starting with + and the country code.",
  email: "Used when WhatsApp isn't available for this person.",
};

/**
 * One person's address on one channel: enter it, then confirm it.
 *
 * Saving is not confirming. The saved address is shown back on its own line
 * and nothing is sent to it until someone presses "This is right" — a mistyped
 * number would otherwise deliver a named child's record to a stranger every
 * week, and a wrong-but-valid number never bounces (threat review F5). Changing
 * the address asks for confirmation again.
 */
export default function ContactEditor({
  who,
  channel,
  contact,
  onSave,
  onConfirm,
}: {
  /** Whose address this is, for the labels: "Sara", "Sara's parent Mona", "you". */
  who: string;
  channel: NotificationChannel;
  contact: Contact | undefined;
  onSave: (address: string) => Promise<unknown>;
  onConfirm: (contactId: number) => Promise<unknown>;
}) {
  const [draft, setDraft] = useState(contact?.address ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const state = contactState(contact);
  const label = `${CHANNEL_LABEL[channel]} for ${who}`;
  const changed = draft.trim() !== (contact?.address ?? "");

  const run = async (action: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (err) {
      setError(friendlyError(err, "That didn't save. Try again."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <form
        className="space-y-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run(() => onSave(draft.trim()));
        }}
      >
        <Field label={label} hint={HINT[channel]} error={error}>
          <Input
            type={channel === "email" ? "email" : "tel"}
            inputMode={channel === "email" ? "email" : "tel"}
            autoComplete="off"
            placeholder={PLACEHOLDER[channel]}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
        </Field>
        <Button
          type="submit"
          variant="secondary"
          size="sm"
          disabled={busy || !changed || draft.trim().length < 3}
        >
          Save
        </Button>
      </form>

      {contact && state === "unconfirmed" && (
        <div
          role="group"
          aria-label={`Confirm ${label}`}
          className="mt-2 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warn-100 bg-warn-100/40 px-3 py-2 text-sm"
        >
          <p className="text-ink-900">
            Check it carefully: <span className="font-medium tabular-nums">{contact.address}</span>
            <span className="block text-xs text-ink-700">
              Nothing is sent here until you confirm it.
            </span>
          </p>
          <Button size="sm" disabled={busy} onClick={() => void run(() => onConfirm(contact.id))}>
            This is right
          </Button>
        </div>
      )}
      {contact && state === "ready" && (
        <p className="mt-1 text-xs text-ok-700">
          Confirmed — messages go to <span className="tabular-nums">{contact.address}</span>.
        </p>
      )}
      {contact && state === "suppressed" && (
        <p className="mt-1 text-xs text-risk-600">{suppressedLabel(contact)}.</p>
      )}
    </div>
  );
}
