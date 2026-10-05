import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  channelStatus,
  confirmMyContact,
  myContacts,
  setMyContact,
  undelivered,
  type NotificationChannel,
} from "../api/notifications";
import ContactEditor from "../components/ContactEditor";
import NotificationPreferences from "../components/NotificationPreferences";
import { Button } from "../components/controls";
import { SectionSkeleton } from "../components/page";
import { KIND_LABEL, UNDELIVERED_LABEL } from "../lib/notifications";

const CHANNELS: NotificationChannel[] = ["whatsapp", "email"];

/** Whether the server can actually send. Said plainly, because until WhatsApp
 *  is connected every message is recorded and none goes out — a tutor who has
 *  confirmed every number would otherwise have no way to know why. */
function ChannelStatusLine() {
  const status = useQuery({ queryKey: ["notification-status"], queryFn: channelStatus });
  if (!status.data) return null;
  const { whatsapp_configured: wa, email_configured: em } = status.data;
  if (wa) return null;
  return (
    <p role="status" className="rounded-lg border border-line bg-surface p-4 text-sm text-ink-700">
      <span className="font-medium text-ink-900">WhatsApp isn&apos;t connected yet.</span>{" "}
      {em
        ? "Until it is, messages go by email to anyone with a confirmed email address."
        : "Until it is, messages are recorded but not sent. You can still add and confirm numbers now so everything is ready."}
    </p>
  );
}

function MyContacts() {
  const queryClient = useQueryClient();
  const contacts = useQuery({ queryKey: ["my-contacts"], queryFn: myContacts });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["my-contacts"] });

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">Where Avora reaches you</h3>
      <p className="mt-1 text-sm text-ink-500">
        Lesson reminders, your weekly summary and a nudge when work is waiting for review.
      </p>
      {contacts.isLoading ? (
        <div className="mt-4">
          <SectionSkeleton rows={2} label="Loading your contact details" />
        </div>
      ) : contacts.isError ? (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-risk-600">
            Your contact details didn&apos;t load.
          </p>
          <Button variant="secondary" size="sm" onClick={() => contacts.refetch()}>
            Try again
          </Button>
        </div>
      ) : (
        <div className="mt-4 grid gap-5 sm:grid-cols-2">
          {CHANNELS.map((channel) => (
            <ContactEditor
              key={channel}
              who="you"
              channel={channel}
              contact={contacts.data?.find((c) => c.channel === channel)}
              onSave={(address) => setMyContact({ channel, address }).then(refresh)}
              onConfirm={(id) => confirmMyContact(id).then(refresh)}
            />
          ))}
        </div>
      )}
    </div>
  );
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/** Messages that reached nobody. Shown only when there are some: a parent who
 *  never gets the weekly summary is otherwise invisible to the tutor. */
function Undelivered() {
  const rows = useQuery({ queryKey: ["notifications-undelivered"], queryFn: undelivered });
  if (!rows.data || rows.data.length === 0) return null;
  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">Messages that didn&apos;t reach anyone</h3>
      <p className="mt-1 text-sm text-ink-500">
        From the last 30 days. Most are fixed by adding or confirming a number on the student&apos;s
        page.
      </p>
      <ul className="mt-3 divide-y divide-line text-sm">
        {rows.data.map((row) => (
          <li key={row.id} className="flex flex-wrap items-baseline justify-between gap-x-4 py-2">
            <span className="text-ink-900">
              {row.recipient_name}{" "}
              <span className="text-ink-500">
                · {row.recipient_role} · {KIND_LABEL[row.kind]}
              </span>
            </span>
            <span className="text-ink-500">
              {UNDELIVERED_LABEL[row.status] ?? "Not delivered"} · {shortDate(row.created_at)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** The tutor's side of messaging: whether the server can send, where the tutor
 *  is reached, what they want to receive, and what failed to arrive. Students'
 *  and parents' numbers are set on each student's own page. */
export default function MessagesSetting() {
  return (
    <div className="space-y-6">
      <ChannelStatusLine />
      <MyContacts />
      <NotificationPreferences />
      <Undelivered />
    </div>
  );
}
