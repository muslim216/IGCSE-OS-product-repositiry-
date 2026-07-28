import { useRef, useState, type DragEvent } from "react";
import { Button } from "./Button";
import { cn } from "./cn";

function formatSize(bytes: number): string {
  return bytes < 1024 * 1024
    ? `${Math.round(bytes / 1024)} KB`
    : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Drag-and-drop or click-to-browse file input. Wraps a real hidden <input
 * type="file"> so keyboard access and the native picker still work.
 */
export function DropZone({
  accept,
  multiple,
  files,
  onFiles,
  label,
  hint,
}: {
  accept?: string;
  multiple?: boolean;
  files: File[];
  onFiles: (files: File[]) => void;
  label: string;
  hint?: string;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);

  function take(list: FileList | null) {
    if (!list || list.length === 0) return;
    const picked = Array.from(list);
    onFiles(multiple ? [...files, ...picked] : picked.slice(0, 1));
  }

  function onDrop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    take(e.dataTransfer.files);
  }

  return (
    <div>
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        onClick={() => inputRef.current?.click()}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            inputRef.current?.click();
          }
        }}
        role="button"
        tabIndex={0}
        className={cn(
          "cursor-pointer rounded-card border-2 border-dashed px-6 py-10 text-center transition-colors",
          dragging
            ? "border-brand-500 bg-brand-50"
            : "border-slate-300 bg-surface hover:border-brand-400 hover:bg-brand-50/40",
        )}
      >
        <div className="text-3xl leading-none">📄</div>
        <p className="mt-2 font-medium text-slate-800">{label}</p>
        {hint && <p className="mt-1 text-sm text-slate-500">{hint}</p>}
        <input
          ref={inputRef}
          type="file"
          accept={accept}
          multiple={multiple}
          className="hidden"
          onChange={(e) => {
            take(e.target.files);
            // Let the same file be picked again after being removed.
            e.target.value = "";
          }}
        />
      </div>

      {files.length > 0 && (
        <ul className="mt-3 space-y-1.5">
          {files.map((file, i) => (
            <li
              key={`${file.name}-${i}`}
              className="flex items-center justify-between gap-3 rounded-control bg-surface-muted px-3 py-2 text-sm"
            >
              <span className="min-w-0 truncate text-slate-700">{file.name}</span>
              <span className="flex shrink-0 items-center gap-2">
                <span className="text-xs text-slate-500">{formatSize(file.size)}</span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => onFiles(files.filter((_, j) => j !== i))}
                >
                  Remove
                </Button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
