import { CandlestickChart, Cpu, Lock, Server, Smartphone, type LucideIcon } from "lucide-react";
import { Fragment } from "react";

interface Node {
  icon: LucideIcon;
  title: string;
  lines: string[];
  highlight?: boolean;
}

const NODES: Node[] = [
  { icon: CandlestickChart, title: "Binance", lines: ["Spot ve vadeli piyasa", "İşlem yetkili, çekim yetkisiz anahtar"] },
  { icon: Cpu, title: "Bilgisayarınız", lines: ["İşlem motoru ve risk kapısı", "Anahtarlar şifreli kasada (DPAPI)"], highlight: true },
  { icon: Server, title: "Aktarma sunucusu", lines: ["Yalnızca şifreli mesaj taşır", "İçeriği ve anahtarı göremez"] },
  { icon: Smartphone, title: "iPhone", lines: ["İzleme ve acil durdurma", "Kritik komutlar Face ID ile"] },
];

const LINKS = ["Doğrudan API (TLS)", "Uçtan uca şifreli", "Uçtan uca şifreli"];

/** Güvenlik mimarisi: anahtarlar bilgisayarda; telefon ile bilgisayar arası uçtan uca şifreli. */
export function Architecture() {
  return (
    <div className="relative">
      <ol className="grid items-stretch gap-0 lg:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr]">
        {NODES.map((node, i) => (
          <Fragment key={node.title}>
            <li
              className={`relative rounded-3xl border p-5 ${
                node.highlight ? "gradient-border shadow-glow" : "border-border bg-surface"
              }`}
            >
              <span
                className={`inline-flex h-11 w-11 items-center justify-center rounded-2xl ${
                  node.highlight ? "bg-brand text-white" : "bg-surface-2 text-accent-text"
                }`}
              >
                <node.icon aria-hidden="true" className="h-5 w-5" />
              </span>
              <h3 className="mt-4 font-semibold text-fg">{node.title}</h3>
              <ul className="mt-2 space-y-1 text-sm text-muted">
                {node.lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </li>
            {i < LINKS.length ? (
              <li aria-hidden="true" className="flex flex-col items-center justify-center gap-2 py-3 lg:px-2 lg:py-0">
                <span className="flow-y h-8 w-0.5 lg:hidden" />
                <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full border border-border bg-surface-2 px-2.5 py-1 text-[11px] font-medium text-fg">
                  {i > 0 ? <Lock className="h-3 w-3 text-accent-text" /> : null}
                  {LINKS[i]}
                </span>
                <span className="flow-x hidden h-0.5 w-full min-w-16 lg:block" />
                <span className="flow-y h-8 w-0.5 lg:hidden" />
              </li>
            ) : null}
          </Fragment>
        ))}
      </ol>
    </div>
  );
}
