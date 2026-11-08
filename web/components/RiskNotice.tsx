import Link from "next/link";

/** Her sayfada görünen kısa risk uyarısı. Ayrıntı: /yasal/risk-bildirimi */
export function RiskNotice({ compact = false }: { compact?: boolean }) {
  return (
    <p className={compact ? "text-xs text-muted" : "text-sm text-muted"}>
      <strong className="font-semibold text-fg">Risk uyarısı:</strong> Kripto varlık işlemleri yüksek risk
      taşır; yatırdığınız paranın tamamını kaybedebilirsiniz. AI Trading Intelligence bir analiz ve işlem
      yazılımıdır, yatırım tavsiyesi vermez ve kazanç garantisi sunmaz. Geçmiş performans ve backtest
      sonuçları gelecekteki sonuçların göstergesi değildir.{" "}
      <Link href="/yasal/risk-bildirimi" className="text-link underline underline-offset-2">
        Risk bildirimini okuyun
      </Link>
      .
    </p>
  );
}
