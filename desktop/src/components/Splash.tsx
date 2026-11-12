import { CheckCircle2, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { LogoMark, Wordmark } from "./Logo";

interface Step {
  label: string;
  done: boolean;
}

/** Açılış ekranı: motor yanıt verene kadar (en az kısa bir an) neon logo ve hazırlık adımları.
 * Hareket azaltma tercihinde animasyon yapılmaz. */
export function Splash({ ready, steps, onDone }: { ready: boolean; steps: Step[]; onDone: () => void }) {
  const [minElapsed, setMinElapsed] = useState(false);
  const [leaving, setLeaving] = useState(false);

  useEffect(() => {
    const id = window.setTimeout(() => setMinElapsed(true), 1300);
    return () => window.clearTimeout(id);
  }, []);

  useEffect(() => {
    if (ready && minElapsed) setLeaving(true);
  }, [ready, minElapsed]);

  useEffect(() => {
    if (!leaving) return;
    const id = window.setTimeout(onDone, 450); // solma geçişinden sonra kaldırılır
    return () => window.clearTimeout(id);
  }, [leaving, onDone]);

  return (
    <div className={`splash ${leaving ? "leaving" : ""}`} role="status" aria-live="polite" data-testid="splash">
      <div className="splash-orb a" aria-hidden="true" />
      <div className="splash-orb b" aria-hidden="true" />
      <div className="splash-grid" aria-hidden="true" />
      <div className="splash-card">
        <div className="splash-logo" aria-hidden="true">
          <span className="ring r1" />
          <span className="ring r2" />
          <LogoMark size={104} />
        </div>
        <h1 className="splash-title">
          <Wordmark large />
        </h1>
        <p className="splash-sub">Piyasa analizi · risk kontrollü otomatik işlem</p>
        <ul className="splash-steps">
          {steps.map((step) => (
            <li key={step.label} className={step.done ? "done" : ""}>
              {step.done ? <CheckCircle2 size={16} aria-hidden="true" /> : <Loader2 size={16} className="spin" aria-hidden="true" />}
              {step.label}
            </li>
          ))}
        </ul>
        <div className="splash-bar" aria-hidden="true">
          <span style={{ width: `${(steps.filter((s) => s.done).length / Math.max(steps.length, 1)) * 100}%` }} />
        </div>
      </div>
    </div>
  );
}
