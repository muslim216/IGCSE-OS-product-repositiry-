import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { myTimezone, setMyTimezone } from "../api/auth";
import { ApiError } from "../api/client";
import { detectedTimezone, supportedTimezones } from "../lib/timezones";
import { useApplyUser } from "../auth/AuthContext";

/**
 * The signed-in user's own time zone (AV-67) — distinct from the
 * organization's, which TimezoneSetting owns. A student or parent may sit in
 * a different country from the tutor whose organization they belong to; this
 * is their say in what "today" means for surfaces addressed to them.
 *
 * Unset is shown as unset and names what is being followed instead (PROD-2):
 * "the organization's zone", never a silent default. Clearing the control
 * returns to that default rather than to UTC.
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
      // a date reads it from there. Invalidating a query does not reach that
      // state — without this the save confirms here and nothing else moves
      // until a reload, which is indistinguishable from the setting not working.
      applyUser(user);
      queryClient.invalidateQueries({ queryKey: ["me"] });
    },
  });

  const current = me.data?.time_zone ?? null;
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
    <div className="rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">Your time zone</h3>
      <p className="mt-1 text-sm text-ink-500">
        Your own zone, overriding the account's for anything addressed to you.
      </p>

      {/* Loading and failure are stated, not rendered as absence. Returning
          null on error removed the whole control, which reads as "this setting
          does not exist for me" rather than "it could not be loaded" — and
          leaves no way to retry. Same shape as TimezoneSetting (PROD-2). */}
      {me.isLoading ? (
        <p className="mt-3 text-sm text-ink-500">Loading…</p>
      ) : me.isError ? (
        <p className="mt-3 text-sm text-risk-600">Couldn't load your time zone.</p>
      ) : (
        <>
          <p className="mt-3 text-sm text-ink-700">
            {current ? (
              <>
                Currently <span className="font-medium text-ink-900">{current}</span>.
              </>
            ) : (
              "Not set — you're following the account's time zone."
            )}
          </p>
          <div className="mt-3">
            <label htmlFor="my-timezone" className="sr-only">
              Your time zone
            </label>
            <select
              id="my-timezone"
              value={current ?? ""}
              disabled={save.isPending}
              onChange={(e) => save.mutate(e.target.value || null)}
              className="rounded-md border border-line-control bg-canvas px-3 py-2 text-sm text-ink-900"
            >
              <option value="">Follow the account's time zone</option>
              {options.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>
          </div>
          {save.isError && (
            <p className="mt-2 text-sm text-risk-600">
              {save.error instanceof ApiError ? save.error.message : "Couldn't save that."}
            </p>
          )}
        </>
      )}
    </div>
  );
}
