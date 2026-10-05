import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { myOrganization } from "../api/auth";
import { setOrganizationSettings } from "../api/notifications";
import { Button, Select } from "../components/controls";
import { SectionSkeleton } from "../components/page";
import { friendlyError } from "../lib/errors";

// Monday first, matching the server's weekday numbers (Mon = 0 … Sun = 6).
const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
const HOURS = Array.from({ length: 24 }, (_, h) => h);
const LANGUAGES = [
  { value: "en", label: "English" },
  { value: "ar", label: "Arabic" },
];

function hourLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

/**
 * When the weekly send goes out, and the language it is written in (AV-88,
 * AV-89, AV-66). One moment for everyone in the account, on the organisation's
 * own clock: a parent abroad gets it when the tutor's week ends.
 */
export default function WeeklySendSetting() {
  const queryClient = useQueryClient();
  const org = useQuery({ queryKey: ["my-organization"], queryFn: myOrganization });
  const save = useMutation({
    mutationFn: setOrganizationSettings,
    onSuccess: (data) => {
      queryClient.setQueryData(["my-organization"], data);
      // Weekday, hour and AI language decide whether the account is on defaults.
      void queryClient.invalidateQueries({ queryKey: ["onboarding"] });
    },
  });

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">The weekly summary</h3>
      <p className="mt-1 text-sm text-ink-500">
        Once a week you, your students and their parents each get a summary of the week. Everyone
        gets it at the same moment, on your organisation&apos;s clock.
      </p>

      {org.isLoading ? (
        <div className="mt-4">
          <SectionSkeleton rows={2} label="Loading the weekly summary settings" />
        </div>
      ) : org.isError || !org.data ? (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-risk-600">
            These settings didn&apos;t load.
          </p>
          <Button variant="secondary" size="sm" onClick={() => org.refetch()}>
            Try again
          </Button>
        </div>
      ) : (
        <div className="mt-4 grid gap-3 sm:grid-cols-3">
          <label className="text-sm text-ink-900">
            Day
            <Select
              className="mt-1.5"
              value={org.data.weekly_send_weekday}
              disabled={save.isPending}
              onChange={(e) => save.mutate({ weekly_send_weekday: Number(e.target.value) })}
            >
              {DAYS.map((day, i) => (
                <option key={day} value={i}>
                  {day}
                </option>
              ))}
            </Select>
          </label>
          <label className="text-sm text-ink-900">
            Time
            <Select
              className="mt-1.5"
              value={org.data.weekly_send_hour}
              disabled={save.isPending}
              onChange={(e) => save.mutate({ weekly_send_hour: Number(e.target.value) })}
            >
              {HOURS.map((h) => (
                <option key={h} value={h}>
                  {hourLabel(h)}
                </option>
              ))}
            </Select>
          </label>
          <label className="text-sm text-ink-900">
            Written in
            <Select
              className="mt-1.5"
              value={org.data.ai_language}
              disabled={save.isPending}
              onChange={(e) => save.mutate({ ai_language: e.target.value as "en" | "ar" })}
            >
              {LANGUAGES.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </Select>
          </label>
        </div>
      )}
      {save.isError && (
        <p role="alert" className="mt-2 text-sm text-risk-600">
          {friendlyError(save.error, "That didn't save. Try again.")}
        </p>
      )}
    </div>
  );
}
