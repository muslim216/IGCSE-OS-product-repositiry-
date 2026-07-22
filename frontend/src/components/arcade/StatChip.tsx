export type StatChipColor = "mint" | "magenta" | "gold" | "default";

const COLOR_CLASSES: Record<StatChipColor, string> = {
  mint: "text-arcade-mint",
  magenta: "text-arcade-magenta",
  gold: "text-arcade-gold",
  default: "text-slate-100",
};

export default function StatChip({
  label,
  value,
  color = "default",
}: {
  label: string;
  value: string;
  color?: StatChipColor;
}) {
  return (
    <div className="border-4 border-black bg-arcade-panel p-3 shadow-[4px_4px_0px_0px_rgba(0,0,0,1)]">
      <p className="font-mono text-[10px] font-black uppercase tracking-wider text-arcade-mint">{label}</p>
      <p className={`mt-1.5 font-mono text-2xl font-black ${COLOR_CLASSES[color]}`}>{value}</p>
    </div>
  );
}
