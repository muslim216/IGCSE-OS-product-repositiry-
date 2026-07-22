export default function ArcadeEmpty({
  text = "NO DATA",
  blink,
}: {
  text?: string;
  blink?: boolean;
}) {
  return (
    <p
      className={`py-3 text-center font-mono text-xs uppercase tracking-widest text-slate-500 ${blink ? "animate-arcade-blink" : ""}`}
    >
      {`-- ${text} --`}
    </p>
  );
}
