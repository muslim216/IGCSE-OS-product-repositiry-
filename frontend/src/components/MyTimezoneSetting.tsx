import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { myTimezone, setMyTimezone } from "../api/auth";
import { friendlyError } from "../lib/errors";
import { detectedTimezone, supportedTimezones } from "../lib/timezones";
import { useApplyUser } from "../auth/AuthContext";
import { Button, Field, Select } from "./controls";
import { SectionSkeleton } from "./page";
import { SectionCard, SectionHeader } from "./ui";

/**
 * The signed-in user's own time zone (AV-67) — distinct from the
 * organization's, which TimezoneSetting owns. A student or parent may sit in
 * a different country from the tutor whose organization they belong to; this
 * is their say in what "today" means for surfaces addressed to them.
 *
 * Unset is shown as unset and names what is being followed instead (PROD-2):
 * "the organization's zone", never a silent default. Clearing the control
 * returns to that default rather than to UTC.
 *
 * Mounted on the student's and parent's Account page and on the tutor's
 * Settings, so the wording below names the default in the reader's own terms:
 * a student or parent follows their tutor's zone, a tutor their organization's.
 */
export default function MyTimezoneSetting() {
  const queryClient = useQueryClient();
  const applyUser = useApplyUser();
  const me = useQuery({ queryKey: ["my-timezone"], queryFn: myTimezone });

  const save = useMutation({
    mutationFn: setMyTimezone,
    onSuccess: (user) => {
      queryClient.setQueryData(["my-timezone"], user);
      // The signed-in identity carries time_zone, and every screen that renders
      // a date reads it from there. It is React state in AuthProvider, not a
      // query — there is no ["me"] key to invalidate, and an invalidation aimed
      // at one would be a silent no-op standing in for the update. Without this
      // call the save confirms here and nothing else moves until a reload,
      // which is indistinguishable from the setting not working.
      applyUser(user);
    },
  });

  const current = me.data?.time_zone ?? null;
  const isStaff = me.data?.role === "tutor" || me.data?.role === "admin";
  const fallbackName = isStaff ? "your organisation's time zone" : "your tutor's time zone";
  // A stored zone this browser does not list would otherwise vanish from the
  // picker and look unset — same guard as the organization picker. The detected
  // zone is included for the same reason it is there: where
  // Intl.supportedValuesOf is missing the list is empty, and an unset user
  // would be left with nothing to choose.
  const detected = detectedTimezone();
  const options = [
    ...new Set([
      ...supportedTimezones(),
      ...(detected ? [detected] : []),
      ...(current ? [current] : []),
    ]),
  ].sort();

  return (
    <SectionCard>
      <SectionHeader
        title="Your time zone"
        description="Decides when “today” and “due tomorrow” turn over for you."
      />

      {/* Loading and failure are stated, not rendered as absence. Returning
          null on error removed the whole control, which reads as "this setting
          does not exist for me" rather than "it could not be loaded" — and
          leaves no way to retry. Same shape as TimezoneSetting (PROD-2). */}
      <div className="mt-4">
        {me.isLoading ? (
          <SectionSkeleton rows={2} label="Loading your time zone" />
        ) : me.isError ? (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-risk-600">Couldn&apos;t load your time zone.</p>
            <Button variant="secondary" size="sm" onClick={() => void me.refetch()}>
              Try again
            </Button>
          </div>
        ) : (
          <Field
            label="Time zone"
            hint={
              current
                ? save.isSuccess
                  ? `Saved. Dates addressed to you now follow ${current}.`
                  : `Dates addressed to you follow ${current}.`
                : `Not set — you're following ${fallbackName}.`
            }
            error={
              save.isError ? friendlyError(save.error, "Couldn't save that. Try again.") : null
            }
          >
            <Select
              value={current ?? ""}
              disabled={save.isPending}
              onChange={(e) => save.mutate(e.target.value || null)}
              className="sm:max-w-sm"
            >
              <option value="">Follow {fallbackName}</option>
              {options.map((zone) => (
                <option key={zone} value={zone}>
                  {zone.replace(/_/g, " ")}
                </option>
              ))}
            </Select>
          </Field>
        )}
      </div>
    </SectionCard>
  );
}
