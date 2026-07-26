import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createFileResource,
  createRecordingResource,
  deleteResource,
  isSafeHttpUrl,
  listResources,
  resourceFilePath,
} from "../api/resources";
import { AuthFileLink } from "../components/AuthFile";

export function GroupResourcesPanel({ groupId }: { groupId: number }) {
  const queryClient = useQueryClient();
  const resources = useQuery({
    queryKey: ["resources", groupId],
    queryFn: () => listResources(groupId),
  });

  const [kind, setKind] = useState<"file" | "recording">("recording");
  const [title, setTitle] = useState("");
  const [url, setUrl] = useState("");
  const [file, setFile] = useState<File | null>(null);

  const create = useMutation({
    mutationFn: () =>
      kind === "recording"
        ? createRecordingResource(groupId, title, url)
        : createFileResource(groupId, title, file as File),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resources", groupId] });
      setTitle("");
      setUrl("");
      setFile(null);
    },
  });

  const remove = useMutation({
    mutationFn: (id: number) => deleteResource(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["resources", groupId] }),
  });

  return (
    <section className="rounded-lg border bg-white p-4">
      <h3 className="font-medium text-slate-800">Files &amp; recordings</h3>
      <ul className="mt-2 divide-y text-sm">
        {resources.data?.map((r) => (
          <li key={r.id} className="flex items-center justify-between py-2">
            <span className="text-slate-700">
              <span className="mr-2 rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-500">
                {r.kind}
              </span>
              {r.title}
            </span>
            <div className="flex items-center gap-3">
              {r.kind === "file" ? (
                <AuthFileLink path={resourceFilePath(r.id)} label="Open" />
              ) : (
                isSafeHttpUrl(r.url) && (
                  <a href={r.url} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">
                    Watch
                  </a>
                )
              )}
              <button onClick={() => remove.mutate(r.id)} className="text-red-500 hover:underline">
                Remove
              </button>
            </div>
          </li>
        ))}
        {resources.data?.length === 0 && (
          <li className="py-2 text-slate-500">Nothing shared yet.</li>
        )}
      </ul>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate();
        }}
        className="mt-3 flex flex-wrap items-end gap-2 border-t pt-3"
      >
        <select
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          value={kind}
          onChange={(e) => setKind(e.target.value as "file" | "recording")}
        >
          <option value="recording">Recording link</option>
          <option value="file">File</option>
        </select>
        <input
          className="rounded-md border border-slate-300 px-3 py-2 text-sm"
          placeholder="Title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
        />
        {kind === "recording" ? (
          <input
            className="min-w-[16rem] rounded-md border border-slate-300 px-3 py-2 text-sm"
            placeholder="https://…"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            required
          />
        ) : (
          <input
            type="file"
            className="text-sm"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            required
          />
        )}
        <button
          type="submit"
          disabled={create.isPending}
          className="rounded-md bg-slate-700 px-3 py-2 text-sm text-white hover:bg-slate-800 disabled:opacity-50"
        >
          Add
        </button>
      </form>
    </section>
  );
}
