import { gradeForPct } from "../../lib/grades";

const SIZE_CLASSES = {
  sm: "h-7 w-7 text-xs",
  md: "h-9 w-9 text-sm",
  lg: "h-12 w-12 text-lg",
};

export default function GradeBadge({
  pct,
  flash,
  size = "md",
}: {
  pct: number | null | undefined;
  flash?: boolean;
  size?: "sm" | "md" | "lg";
}) {
  const info = gradeForPct(pct);

  if (!info) {
    return (
      <div
        className={`grid place-items-center border-4 border-black bg-arcade-panel-2 font-mono font-black text-slate-500 shadow-[3px_3px_0px_0px_rgba(0,0,0,1)] ${SIZE_CLASSES[size]}`}
        aria-label="Grade unavailable"
      >
        --
      </div>
    );
  }

  const shouldFlash = flash ?? (info.grade === "A*" || info.grade === "A");

  return (
    <div
      className={`grid place-items-center border-4 border-black font-mono font-black shadow-[3px_3px_0px_0px_rgba(0,0,0,1)] ${info.bg} ${info.text} ${SIZE_CLASSES[size]} ${shouldFlash ? "animate-arcade-flash" : ""}`}
      aria-label={`Grade ${info.grade}`}
    >
      {info.grade}
    </div>
  );
}
