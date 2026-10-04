import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  disconnectIntegration,
  getAuthorizeUrl,
  listIntegrations,
  PROVIDER_LABEL,
  type IntegrationStatus,
  type MeetingProvider,
} from "../api/integrations";
import { Button } from "../components/controls";
import { SectionSkeleton } from "../components/page";
import { friendlyError } from "../lib/errors";

/** Where the callback page finds the `state` we sent, as a second check. The
 *  server verifies the signed state; this only catches a callback that began in
 *  a different browser. */
export const stateKey = (provider: MeetingProvider) => `avora-integration-state-${provider}`;

function ProviderRow({ item }: { item: IntegrationStatus }) {
  const queryClient = useQueryClient();
  const label = PROVIDER_LABEL[item.provider];
  const connect = useMutation({
    mutationFn: () => getAuthorizeUrl(item.provider),
    onSuccess: ({ url, state }) => {
      sessionStorage.setItem(stateKey(item.provider), state);
      window.location.assign(url);
    },
  });
  const disconnect = useMutation({
    mutationFn: () => disconnectIntegration(item.provider),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["integrations"] }),
  });

  return (
    <li className="py-4 first:pt-0 last:pb-0">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-ink-900">{label}</p>
          {item.connected ? (
            <p className="text-sm text-ink-700">
              Connected{item.account_email ? ` as ${item.account_email}` : ""}.
            </p>
          ) : item.configured ? (
            <p className="text-sm text-ink-500">Not connected.</p>
          ) : (
            <p className="text-sm text-ink-500">
              Not set up for Avora yet — {label} attendance will be available here once it is.
            </p>
          )}
        </div>
        {item.connected ? (
          <Button
            variant="secondary"
            size="sm"
            loading={disconnect.isPending}
            onClick={() => disconnect.mutate()}
          >
            Disconnect {label}
          </Button>
        ) : (
          <Button
            size="sm"
            disabled={!item.configured}
            loading={connect.isPending}
            onClick={() => connect.mutate()}
          >
            Connect {label}
          </Button>
        )}
      </div>
      <p className="mt-1 text-sm text-ink-500">{item.note}</p>
      {(connect.isError || disconnect.isError) && (
        <p role="alert" className="mt-2 text-sm text-risk-600">
          {friendlyError(connect.error ?? disconnect.error)}
        </p>
      )}
    </li>
  );
}

/** Connect Zoom or Google Meet so an online lesson's attendance can be pulled
 *  in. Each provider says plainly when it is not set up yet, and Google says up
 *  front what it needs. */
export default function IntegrationsSetting() {
  const integrations = useQuery({ queryKey: ["integrations"], queryFn: listIntegrations });

  return (
    <div className="rounded-lg border border-line bg-surface p-4">
      <h3 className="font-medium text-ink-900">Online lesson attendance</h3>
      <p className="mt-1 text-sm text-ink-500">
        Connect Zoom or Google Meet and Avora can fill in an online lesson's register from who
        joined. Avora only reads attendance — it never starts or changes a meeting. Anyone it can't
        match to a student by email is left for you to pick.
      </p>
      <div className="mt-4">
        {integrations.isLoading ? (
          <SectionSkeleton rows={2} label="Loading your connections" />
        ) : integrations.isError ? (
          <div className="flex flex-wrap items-center gap-3">
            <p role="alert" className="text-sm text-risk-600">
              {friendlyError(integrations.error)}
            </p>
            <Button variant="secondary" size="sm" onClick={() => integrations.refetch()}>
              Try again
            </Button>
          </div>
        ) : (
          <ul className="divide-y divide-line">
            {(integrations.data ?? []).map((item) => (
              <ProviderRow key={item.provider} item={item} />
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
