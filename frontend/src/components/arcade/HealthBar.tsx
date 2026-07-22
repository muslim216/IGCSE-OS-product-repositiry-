function fillColor(value: number): string {
  if (value >= 70) return "bg-arcade-mint";
  if (value >= 50) return "bg-arcade-gold";
  return "bg-arcade-magenta";
}

export default function HealthBar({
  value,
  segments = 10,
  label,
}: {
  value: number;
  segments?: number;
  label?: string;
}) {
  const clamped = Math.max(0, Math.min(100, value));
  const filled = Math.round((clamped / 100) * segments);
  const color = fillColor(clamped);

  return (
    <div className="flex items-center gap-2">
      {label && <span className="shrink-0 font-mono text-[10px] uppercase tracking-wider text-slate-400">{label}</span>}
      <div
        role="meter"
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
        className="flex flex-1 gap-0.5"
      >
        {Array.from({ length: segments }, (_, i) => (
          <div
            key={i}
            className={`h-4 flex-1 border-2 border-black ${i < filled ? color : "bg-black/60"}`}
          />
        ))}
      </div>
      <span className="shrink-0 font-mono text-xs font-black text-slate-200">
        {String(Math.round(clamped)).padStart(3, "0")}/100
      </span>
    </div>
  );
}
