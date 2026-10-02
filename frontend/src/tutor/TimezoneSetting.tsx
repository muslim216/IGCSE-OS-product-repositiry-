import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { myOrganization, setOrganizationTimezone } from "../api/auth";
import { Button, Select } from "../components/controls";
import { SectionSkeleton } from "../components/page";
import { friendlyError } from "../lib/errors";
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
      <h3 className="font-medium text-ink-900">Your organisation's time zone</h3>
      <p className="mt-1 text-sm text-ink-500">
        Used for anything that names a day — today's lessons, and the weekly update parents get.
      </p>

      {org.isLoading ? (
        <div className="mt-4">
          <SectionSkeleton rows={2} label="Loading your time zone" />
        </div>
      ) : org.isError ? (
        <div className="mt-3 flex flex-wrap items-center gap-3">
          <p role="alert" className="text-sm text-risk-600">
            Your organisation's time zone didn't load.
          </p>
          <Button variant="secondary" size="sm" onClick={() => org.refetch()}>
            Try again
          </Button>
        </div>
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
            <div className="w-full sm:w-72">
              <Select
                id="org-timezone"
                value={current ?? ""}
                disabled={save.isPending}
                onChange={(e) => save.mutate(e.target.value || null)}
              >
                <option value="">Not set (UTC)</option>
                {options.map((zone) => (
                  <option key={zone} value={zone}>
                    {zone}
                  </option>
                ))}
              </Select>
            </div>

            {detected && detected !== current && (
              <Button
                variant="secondary"
                disabled={save.isPending}
                onClick={() => save.mutate(detected)}
              >
                Use this device's ({detected})
              </Button>
            )}
          </div>

          {save.isError && (
            <p role="alert" className="mt-2 text-sm text-risk-600">
              {friendlyError(save.error, "That didn't save. Try again.")}
            </p>
          )}
        </>
      )}
    </div>
  );
}
