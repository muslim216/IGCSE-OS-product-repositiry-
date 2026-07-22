import { useEffect, useState } from "react";

const DAY_MS = 24 * 60 * 60 * 1000;
const HOUR_MS = 60 * 60 * 1000;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

export default function CountdownTimer({ target }: { target: string }) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const targetMs = new Date(target).getTime();
  const remaining = targetMs - now;

  if (remaining <= 0) {
    return (
      <span className="font-mono text-2xl font-black tracking-widest text-arcade-magenta animate-arcade-flash">
        TIME UP!
      </span>
    );
  }

  const days = Math.floor(remaining / DAY_MS);
  const hours = Math.floor((remaining % DAY_MS) / HOUR_MS);
  const minutes = Math.floor((remaining % HOUR_MS) / (60 * 1000));
  const seconds = Math.floor((remaining % (60 * 1000)) / 1000);

  const color =
    remaining >= DAY_MS ? "text-arcade-mint" : remaining >= HOUR_MS ? "text-arcade-gold" : "text-arcade-magenta";

  return (
    <span className={`font-mono text-2xl font-black tracking-widest ${color}`}>
      {pad(days)}D<span className="animate-arcade-blink">:</span>
      {pad(hours)}H<span className="animate-arcade-blink">:</span>
      {pad(minutes)}M<span className="animate-arcade-blink">:</span>
      {pad(seconds)}S
    </span>
  );
}
