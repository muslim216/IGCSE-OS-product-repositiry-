import { useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  dataExportFileUrl,
  dataExportStatus,
  isBuilding,
  requestDataExport,
  type ExportAsker,
} from "../api/dataExport";
import { FileFetchError } from "../api/homework";
import { Button } from "./controls";
import { friendlyError } from "../lib/errors";

/** How long an object URL is kept after the click, so the browser has started
 *  the save before it is released. */
const REVOKE_MS = 1000;

/** Asks for a child's data as a ZIP, waits while it is built, then offers the
 *  file. The save is a button the person presses, not something that starts by
 *  itself: Safari blocks a download that does not follow a click. The file is
 *  kept for seven days; a tutor or a linked parent may ask.
 *
 *  Mount it with `key={studentId}` so switching child starts it afresh. */
export default function DownloadChildData({
  asker,
  studentId,
  name,
  pollMs = 2000,
}: Readonly<{ asker: ExportAsker; studentId: number; name: string; pollMs?: number }>) {
  const [exportId, setExportId] = useState<number | null>(null);

  // Set the moment a press is accepted, before React has re-rendered, so a
  // second press in the same tick cannot start a second request.
  const asking = useRef(false);
  const request = useMutation({
    mutationFn: () => requestDataExport(asker, studentId),
    onSuccess: (e) => setExportId(e.id),
    onSettled: () => {
      asking.current = false;
    },
  });

  const status = useQuery({
    queryKey: ["data-export", asker, studentId, exportId],
    queryFn: () => dataExportStatus(asker, studentId, exportId!),
    enabled: exportId !== null,
    refetchInterval: (q) => (isBuilding(q.state.data) ? pollMs : false),
  });

  const download = useMutation({
    mutationFn: async (id: number) => {
      const url = await dataExportFileUrl(asker, studentId, id);
      const link = document.createElement("a");
      link.href = url;
      link.download = `avora-student-${studentId}-data.zip`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), REVOKE_MS);
    },
  });

  const state = status.data?.status;
  const building = exportId !== null && isBuilding(status.data);
  // Not `disabled`: a disabled button drops keyboard focus, and the person would
  // lose their place while the file is prepared.
  const busy = request.isPending || building || download.isPending;
  const ready = state === "ready" && !building;

  function ask() {
    if (busy || asking.current) return;
    asking.current = true;
    download.reset();
    request.mutate();
  }

  let message = "";
  let failed = false;
  if (request.isError) {
    failed = true;
    message = friendlyError(request.error, "Couldn't start that. Try again.");
  } else if (status.isError) {
    failed = true;
    message = friendlyError(status.error, "Couldn't check on that. Try again.");
  } else if (state === "failed") {
    failed = true;
    message = status.data?.error ?? "The export could not be built. Try again.";
  } else if (state === "expired" || (download.error as FileFetchError | null)?.status === 410) {
    failed = true;
    message = "That file has expired; request a new one.";
  } else if (download.isError) {
    failed = true;
    message = friendlyError(download.error, "Couldn't download the file. Try again.");
  } else if (request.isPending || building) {
    message = "Preparing the file. This can take a minute.";
  } else if (download.isSuccess) {
    message = "Downloaded. The file is deleted from Avora after seven days.";
  } else if (ready) {
    message = "The file is ready. It is deleted from Avora after seven days.";
  }

  const expired = state === "expired" || (download.error as FileFetchError | null)?.status === 410;
  const offerSave = ready && !expired && !failed;

  return (
    <div>
      <div className="flex flex-wrap gap-3">
        <Button variant="secondary" aria-disabled={busy} onClick={ask}>
          Request {name}&apos;s data
        </Button>
        {offerSave && (
          <Button
            aria-disabled={download.isPending}
            onClick={() => {
              if (!download.isPending && exportId !== null) download.mutate(exportId);
            }}
          >
            Download {name}&apos;s data (ZIP)
          </Button>
        )}
      </div>
      {/* Always mounted, so a change in it is announced; a failure is an alert. */}
      <div aria-live="polite" className="mt-2 text-sm">
        {message &&
          (failed ? (
            <p role="alert" className="text-risk-600">
              {message}
            </p>
          ) : (
            <p className="text-ink-700">{message}</p>
          ))}
      </div>
    </div>
  );
}
