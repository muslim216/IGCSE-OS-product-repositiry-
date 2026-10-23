import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  dataExportFileUrl,
  dataExportStatus,
  isBuilding,
  requestDataExport,
  type ExportAsker,
} from "../api/dataExport";
import { Button } from "./controls";
import { friendlyError } from "../lib/errors";

const POLL_MS = 2000;

/** Asks for a child's data as a ZIP, waits while it is built, then saves it.
 *  The file is kept for seven days; a tutor or a linked parent may ask. */
export default function DownloadChildData({
  asker,
  studentId,
}: Readonly<{ asker: ExportAsker; studentId: number }>) {
  const [exportId, setExportId] = useState<number | null>(null);
  const saved = useRef<number | null>(null);

  const request = useMutation({
    mutationFn: () => requestDataExport(asker, studentId),
    onSuccess: (e) => {
      saved.current = null;
      setExportId(e.id);
    },
  });

  const status = useQuery({
    queryKey: ["data-export", asker, studentId, exportId],
    queryFn: () => dataExportStatus(asker, studentId, exportId!),
    enabled: exportId !== null,
    refetchInterval: (q) => (isBuilding(q.state.data) ? POLL_MS : false),
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
      setTimeout(() => URL.revokeObjectURL(url), 10_000);
    },
  });

  const state = status.data?.status;
  const { mutate: save } = download;
  // Saved once per export, as soon as it is ready.
  useEffect(() => {
    if (state === "ready" && exportId !== null && saved.current !== exportId) {
      saved.current = exportId;
      save(exportId);
    }
  }, [state, exportId, save]);

  const busy =
    request.isPending || (exportId !== null && isBuilding(status.data)) || download.isPending;

  let message = "";
  if (request.isError) message = friendlyError(request.error, "Couldn't start that. Try again.");
  else if (status.isError)
    message = friendlyError(status.error, "Couldn't check on that. Try again.");
  else if (state === "failed")
    message = status.data?.error ?? "The export could not be built. Try again.";
  else if (state === "expired") message = "That file has expired. Ask again for a new one.";
  else if (download.isError)
    message = friendlyError(download.error, "Couldn't download the file. Try again.");
  else if (busy) message = "Preparing the file. This can take a minute.";
  else if (state === "ready" && download.isSuccess)
    message = "Downloaded. The file is deleted from Avora after seven days.";

  const failed =
    state === "failed" ||
    state === "expired" ||
    request.isError ||
    status.isError ||
    download.isError;

  return (
    <div>
      <Button variant="secondary" disabled={busy} onClick={() => request.mutate()}>
        Download this child&apos;s data
      </Button>
      {message && (
        <output className={`mt-2 block text-sm ${failed ? "text-risk-600" : "text-ink-700"}`}>
          {message}
        </output>
      )}
    </div>
  );
}
