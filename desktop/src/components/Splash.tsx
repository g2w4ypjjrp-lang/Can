import { CheckCircle2, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";

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
          <svg viewBox="0 0 32 32" width="54" height="54" focusable="false">
            <path className="splash-line" d="M6 23l7-8 4.5 4.5L26 9" fill="none" strokeWidth="2.8" strokeLinecap="round" strokeLinejoin="round" />
            <circle cx="26" cy="9" r="2.3" />
          </svg>
        </div>
        <h1 className="splash-title">
          AI Trading <span>Intelligence</span>
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
