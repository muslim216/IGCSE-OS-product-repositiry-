import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { myOrganization, setOrganizationTimezone } from "../api/auth";
import { ApiError } from "../api/client";
import { supportedTimezones, detectedTimezone } from "../lib/timezones";

/**
 * The zone every "today" in the product is computed in — today's lessons, the
 * weekly parent narrative, anything that names a day.
 *
 * Unset is shown as unset, with the UTC fallback stated rather than implied
 * (PROD-2): a tutor whose lesson list is a day out needs to be able to see
 * why, and a silent default hides exactly that.
 */
export default function TimezoneSetting() {
  const queryClient = useQueryClient();
  const org = useQuery({ queryKey: ["my-organization"], queryFn: myOrganization });

  const save = useMutation({
    mutationFn: setOrganizationTimezone,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["my-organization"] }),
  });

  const zones = supportedTimezones();
  const detected = detectedTimezone();
  const current = org.data?.timezone ?? null;
  // A stored zone this browser does not list would otherwise vanish from the
  // picker and look unset.
  const options = [
    ...new Set([...zones, ...(detected ? [detected] : []), ...(current ? [current] : [])]),
  ].sort();

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">Time zone</h3>
      <p className="mt-1 text-sm text-ink-500">
        Used for anything that names a day — today's lessons, and the weekly update parents get.
      </p>

      {org.isLoading ? (
        <p className="mt-3 text-sm text-ink-500">Loading…</p>
      ) : org.isError ? (
        <p className="mt-3 text-sm text-risk-600">Couldn't load your time zone.</p>
      ) : (
        <>
          <p className="mt-3 text-sm text-ink-700">
            {current ? (
              <>
                Currently <span className="font-medium text-ink-900">{current}</span>.
              </>
            ) : (
              "Not set — days are worked out in UTC, which may be a day off from yours."
            )}
          </p>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <label htmlFor="org-timezone" className="sr-only">
              Time zone
            </label>
            <select
              id="org-timezone"
              value={current ?? ""}
              disabled={save.isPending}
              onChange={(e) => save.mutate(e.target.value || null)}
              className="rounded-md border border-line-control bg-canvas px-3 py-2 text-sm text-ink-900"
            >
              <option value="">Not set (UTC)</option>
              {options.map((zone) => (
                <option key={zone} value={zone}>
                  {zone}
                </option>
              ))}
            </select>

            {detected && detected !== current && (
              <button
                type="button"
                disabled={save.isPending}
                onClick={() => save.mutate(detected)}
                className="rounded-md border border-line px-3 py-2 text-sm text-ink-700 transition hover:bg-surface-muted"
              >
                Use this device's ({detected})
              </button>
            )}
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
