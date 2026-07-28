import { useEffect, useState } from "react";
import { Button, DropZone } from "../ui";

/**
 * Page order matters — the server takes it from the array order — so students
 * need to see and fix it. Reordering uses explicit move buttons rather than
 * drag-and-drop: most students are on a phone, where dragging is awkward.
 */
export function PageUploader({
  files,
  onChange,
}: {
  files: File[];
  onChange: (files: File[]) => void;
}) {
  const [previews, setPreviews] = useState<(string | null)[]>([]);

  useEffect(() => {
    const urls = files.map((f) => (f.type.startsWith("image/") ? URL.createObjectURL(f) : null));
    setPreviews(urls);
    // Object URLs leak until revoked.
    return () => urls.forEach((u) => u && URL.revokeObjectURL(u));
  }, [files]);

  function move(from: number, to: number) {
    if (to < 0 || to >= files.length) return;
    const next = [...files];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    onChange(next);
  }

  return (
    <div className="space-y-3">
      <DropZone
        label={files.length ? "Add more pages" : "Add your pages"}
        hint="Photos or a PDF. Click to browse, or drag them here."
        accept="application/pdf,image/*"
        multiple
        files={[]}
        onFiles={(picked) => onChange([...files, ...picked])}
      />

      {files.length > 0 && (
        <div>
          <p className="mb-2 text-sm text-slate-500">
            {files.length} page{files.length === 1 ? "" : "s"} — check they're in the right order.
          </p>
          <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {files.map((file, i) => (
              <li
                key={`${file.name}-${i}`}
                className="overflow-hidden rounded-card border border-slate-200 bg-surface"
              >
                <div className="relative flex h-32 items-center justify-center bg-surface-muted">
                  {previews[i] ? (
                    <img
                      src={previews[i]!}
                      alt={`Page ${i + 1}`}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <span className="text-3xl">📄</span>
                  )}
                  <span className="absolute left-2 top-2 rounded-full bg-slate-900/75 px-2 py-0.5 text-xs font-medium text-white">
                    {i + 1}
                  </span>
                </div>
                <div className="flex items-center justify-between gap-1 px-2 py-1.5">
                  <div className="flex gap-0.5">
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`Move page ${i + 1} earlier`}
                      disabled={i === 0}
                      onClick={() => move(i, i - 1)}
                    >
                      ←
                    </Button>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`Move page ${i + 1} later`}
                      disabled={i === files.length - 1}
                      onClick={() => move(i, i + 1)}
                    >
                      →
                    </Button>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    aria-label={`Remove page ${i + 1}`}
                    onClick={() => onChange(files.filter((_, j) => j !== i))}
                  >
                    Remove
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
