import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../auth/AuthContext";
import {
  myPreferences,
  setMyPreferences,
  type NotificationChannel,
  type Preference,
} from "../api/notifications";
import { CHANNEL_LABEL, KINDS_FOR_ROLE, KIND_LABEL } from "../lib/notifications";
import { friendlyError } from "../lib/errors";
import { Button } from "./controls";
import { SectionSkeleton } from "./page";
import { SectionCard, SectionHeader } from "./ui";

const CHANNELS: NotificationChannel[] = ["whatsapp", "email"];

/**
 * Which messages the signed-in person gets, per channel — "the reminder on my
 * phone, the summary by email" is a choice only they can make (task 8.7's
 * per-channel opt-out, built on 8.1). Everything is on until switched off, and
 * only the kinds this role is ever sent are offered.
 */
export default function NotificationPreferences() {
  const { user } = useAuth();
  const queryClient = useQueryClient();
  const prefs = useQuery({ queryKey: ["notification-preferences"], queryFn: myPreferences });
  const save = useMutation({
    mutationFn: (item: Preference) => setMyPreferences([item]),
    onSuccess: (data) => queryClient.setQueryData(["notification-preferences"], data),
  });
  if (!user) return null;
  const kinds = KINDS_FOR_ROLE[user.role] ?? [];
  const enabled = (kind: string, channel: string) =>
    prefs.data?.find((p) => p.kind === kind && p.channel === channel)?.enabled ?? true;

  return (
    <SectionCard>
      <SectionHeader title="Messages" />
      <p className="mt-1 text-sm text-ink-500">
        Choose what reaches you and where. You can also reply STOP to any WhatsApp message to turn
        everything off.
      </p>
      {prefs.isLoading ? (
        <div className="mt-4">
          <SectionSkeleton rows={3} label="Loading your message settings" />
        </div>
      ) : prefs.isError ? (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-risk-600">
            Your message settings didn&apos;t load.
          </p>
          <Button variant="secondary" size="sm" onClick={() => prefs.refetch()}>
            Try again
          </Button>
        </div>
      ) : (
        <table className="mt-4 w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-ink-500">
              <th scope="col" className="pb-2 font-normal">
                Message
              </th>
              {CHANNELS.map((c) => (
                <th key={c} scope="col" className="w-24 pb-2 text-center font-normal">
                  {CHANNEL_LABEL[c]}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {kinds.map((kind) => (
              <tr key={kind}>
                <th scope="row" className="py-2.5 text-left font-normal text-ink-900">
                  {KIND_LABEL[kind]}
                </th>
                {CHANNELS.map((channel) => (
                  <td key={channel} className="py-2.5 text-center">
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-brand-600"
                      aria-label={`${KIND_LABEL[kind]} by ${CHANNEL_LABEL[channel]}`}
                      checked={enabled(kind, channel)}
                      disabled={save.isPending}
                      onChange={(e) => save.mutate({ kind, channel, enabled: e.target.checked })}
                    />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {save.isError && (
        <p role="alert" className="mt-2 text-sm text-risk-600">
          {friendlyError(save.error, "That didn't save. Try again.")}
        </p>
      )}
    </SectionCard>
  );
}
