import { CheckCircle2, ChevronRight, Circle, KeyRound, Smartphone, Sparkles, type LucideIcon } from "lucide-react";
import { usePoll } from "../api/hooks";
import type { LicenseStatusResponse } from "../api/types.gen";
import { useNavigate } from "../lib/nav";

interface ExecutionStatus {
  environment?: string;
  markets: Record<string, { key_stored: boolean; connected: boolean }>;
}

interface RemoteStatus {
  enabled: boolean;
  devices: { revoked: boolean }[];
}

interface Step {
  key: string;
  title: string;
  hint: string;
  done: boolean;
  page: string;
  icon: LucideIcon;
  optional?: boolean;
}

/** Kurulumdan sonraki adımlar; hepsi tamamlanınca kart gizlenir. */
export function GettingStarted({ mode }: { mode?: string }) {
  const navigate = useNavigate();
  const license = usePoll((c) => c.get<LicenseStatusResponse>("/v1/license"), 15_000);
  const live = mode === "live";
  const execution = usePoll((c) => c.get<ExecutionStatus>("/v1/execution/status", { environment: "testnet" }), 10_000);
  const liveExecution = usePoll((c) => c.get<ExecutionStatus>("/v1/execution/status", { environment: "live" }), 10_000);
  const remote = usePoll((c) => c.get<RemoteStatus>("/v1/remote/status"), 10_000);

  if (!license.data && !execution.data && !remote.data) return null;
  const keyedIn = (s?: ExecutionStatus) => Object.values(s?.markets ?? {}).some((m) => m.key_stored);
  // Gerçek hesap ya da deneme hesabı anahtarlarından biri yeterli.
  const keyed = live ? keyedIn(liveExecution.data) : keyedIn(execution.data) || keyedIn(liveExecution.data);
  const phones = (remote.data?.devices ?? []).filter((d) => !d.revoked).length;
  const steps: Step[] = [
    {
      key: "license",
      title: "Lisans etkin",
      hint: license.data?.valid ? (license.data.plan_name ?? "Etkin") : "Lisans anahtarınızı girin",
      done: Boolean(license.data?.valid) || license.data?.enforced === false,
      page: "settings",
      icon: KeyRound,
    },
    {
      key: "binance",
      title: "Binance anahtarı",
      hint: keyed ? "Bağlandı" : "binance.com → API Yönetimi (para çekme KAPALI) ya da deneme için demo.binance.com",
      done: keyed,
      page: "settings",
      icon: Sparkles,
    },
    {
      key: "phone",
      title: "Telefonu eşleştir",
      hint: phones > 0 ? `${phones} telefon eşli` : "İsteğe bağlı: QR'ı telefonun kamerasıyla okutun",
      done: phones > 0,
      page: "phone",
      icon: Smartphone,
      optional: true,
    },
  ];
  const required = steps.filter((s) => !s.optional);
  // Zorunlu adımlar bitince kart kaybolur (telefon isteğe bağlı; Telefon ekranından yapılır).
  if (required.every((s) => s.done)) return null;
  const doneCount = steps.filter((s) => s.done).length;

  return (
    <section className="getting-started" aria-labelledby="baslarken" data-testid="getting-started">
      <div className="gs-head">
        <div>
          <h2 id="baslarken">Başlarken</h2>
          <p className="muted small">
            {doneCount} / {steps.length} adım tamam.
          </p>
        </div>
        <div className="gs-progress" aria-hidden="true">
          <progress max={steps.length} value={doneCount} />
        </div>
      </div>
      <ol className="gs-steps">
        {steps.map((step) => {
          const Icon = step.icon;
          return (
            <li key={step.key}>
              <button type="button" className={`gs-step ${step.done ? "done" : ""}`} onClick={() => navigate(step.page)} data-testid={`gs-${step.key}`}>
                <span className="gs-icon" aria-hidden="true">
                  <Icon size={18} />
                </span>
                <span className="gs-text">
                  <b>
                    {step.title}
                    {step.optional ? <span className="muted small"> · isteğe bağlı</span> : null}
                  </b>
                  <span className="muted small">{step.hint}</span>
                </span>
                {step.done ? (
                  <CheckCircle2 className="gs-state ok" aria-label="Tamam" size={20} />
                ) : (
                  <span className="gs-state">
                    <Circle aria-label="Yapılacak" size={20} />
                    <ChevronRight aria-hidden="true" size={16} />
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
