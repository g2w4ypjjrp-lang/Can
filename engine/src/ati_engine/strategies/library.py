"""Bağımsız strateji kütüphanesi (14 strateji).

Her strateji klasik ve yaygın bilinen bir kuralı uygular; parametreler sabittir ve sonuçları
Aşama 8 backtest'i ile Aşama 9 sanal yarışmasında ayrı ayrı ölçülür. Hiçbir stratejinin kârlı
olduğu varsayılmaz.
"""

from __future__ import annotations

from ati_engine.strategies.base import (
    MarketKind,
    Strategy,
    StrategySignal,
    StrategyView,
    clamp,
)

BOTH: tuple[MarketKind, ...] = ("spot", "usdm_futures")
FUTURES: tuple[MarketKind, ...] = ("usdm_futures",)


class EmaTrend:
    name = "ema_trend"
    title = "EMA trend takibi"
    description = (
        "EMA9 > EMA21 > EMA50 ve fiyat EMA200 üzerindeyse long; tam tersi dizilimde short. "
        "Güç, ortalamalar arası açıklığın ATR'ye oranıyla artar."
    )
    markets = BOTH
    category = "trend"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s = view.now
        up = s.ema9 > s.ema21 > s.ema50 and s.close > s.ema200
        down = s.ema9 < s.ema21 < s.ema50 and s.close < s.ema200
        if not (up or down):
            return None
        spread = abs(s.ema9 - s.ema50) / s.atr
        direction = 1 if up else -1
        return StrategySignal(
            self.name,
            direction,
            clamp(0.3 + spread / 4),
            f"EMA dizilimi {'yükseliş' if up else 'düşüş'} yönünde, "
            f"EMA9-EMA50 açıklığı {spread:.1f} ATR",
            stop_atr=2.0,
            target_atr=4.0,
        )


class MacdMomentum:
    name = "macd_momentum"
    title = "MACD momentum kesişimi"
    description = "MACD histogramı sıfırı yukarı keserse long, aşağı keserse short."
    markets = BOTH
    category = "momentum"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s, p = view.now, view.prev
        if p is None:
            return None
        if p.macd_hist <= 0 < s.macd_hist:
            direction = 1
        elif p.macd_hist >= 0 > s.macd_hist:
            direction = -1
        else:
            return None
        trend_ok = (s.close > s.ema200) == (direction == 1)
        strength = clamp(abs(s.macd) / s.atr / 2 + (0.3 if trend_ok else 0.0))
        return StrategySignal(
            self.name,
            direction,
            strength,
            f"MACD histogramı sıfırı {'yukarı' if direction == 1 else 'aşağı'} kesti"
            + ("; EMA200 ile aynı yönde" if trend_ok else "; EMA200'e karşı"),
        )


class RsiReversion:
    name = "rsi_reversion"
    title = "RSI aşırı bölgeden dönüş"
    description = (
        "Yükselen trendde (fiyat EMA200 üzerinde) RSI 30 altından yukarı dönerse long; "
        "düşen trendde RSI 70 üzerinden aşağı dönerse short."
    )
    markets = BOTH
    category = "mean_reversion"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s, p = view.now, view.prev
        if p is None:
            return None
        if p.rsi < 30 and s.rsi > p.rsi and s.close > s.ema200:
            return StrategySignal(
                self.name,
                1,
                clamp((30 - p.rsi) / 15 + 0.3),
                f"RSI {p.rsi:.0f} aşırı satımdan yukarı döndü, ana trend yukarı",
                stop_atr=1.2,
                target_atr=2.0,
            )
        if p.rsi > 70 and s.rsi < p.rsi and s.close < s.ema200:
            return StrategySignal(
                self.name,
                -1,
                clamp((p.rsi - 70) / 15 + 0.3),
                f"RSI {p.rsi:.0f} aşırı alımdan aşağı döndü, ana trend aşağı",
                stop_atr=1.2,
                target_atr=2.0,
            )
        return None


class BollingerReversion:
    name = "bollinger_reversion"
    title = "Bollinger bandına dönüş"
    description = (
        "Önceki mum alt bandın altında kapandı ve bu mum bandın içine döndüyse long; üst bant "
        "için short."
    )
    markets = BOTH
    category = "mean_reversion"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s, p = view.now, view.prev
        if p is None:
            return None
        if p.close < p.bb_lower and s.close > s.bb_lower:
            depth = (p.bb_lower - p.close) / p.atr
            return StrategySignal(
                self.name,
                1,
                clamp(0.3 + depth / 2),
                "Fiyat alt Bollinger bandının altından banda geri döndü",
                stop_atr=1.0,
                target_atr=(s.bb_middle - s.close) / s.atr if s.bb_middle > s.close else 1.0,
            )
        if p.close > p.bb_upper and s.close < s.bb_upper:
            depth = (p.close - p.bb_upper) / p.atr
            return StrategySignal(
                self.name,
                -1,
                clamp(0.3 + depth / 2),
                "Fiyat üst Bollinger bandının üstünden banda geri döndü",
                stop_atr=1.0,
                target_atr=(s.close - s.bb_middle) / s.atr if s.close > s.bb_middle else 1.0,
            )
        return None


class SqueezeBreakout:
    name = "squeeze_breakout"
    title = "Bollinger sıkışma kırılımı"
    description = (
        "Bant genişliği son 120 mumun en dar %15'indeyken fiyat bandın dışına kapanırsa "
        "kırılım yönünde sinyal."
    )
    markets = BOTH
    category = "breakout"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s, p = view.now, view.prev
        if p is None or p.bb_width_rank > 0.15:
            return None
        if s.close > s.bb_upper:
            direction = 1
        elif s.close < s.bb_lower:
            direction = -1
        else:
            return None
        return StrategySignal(
            self.name,
            direction,
            clamp(0.4 + max(s.volume_z, 0) / 4),
            f"Dar banttan (son 120 mumun %{p.bb_width_rank * 100:.0f}'lik diliminde) "
            f"{'yukarı' if direction == 1 else 'aşağı'} kırılım, hacim z={s.volume_z:.1f}",
            stop_atr=1.5,
            target_atr=3.5,
        )


class DonchianBreakout:
    name = "donchian_breakout"
    title = "Donchian kanal kırılımı (20)"
    description = "Kapanış önceki 20 mumun en yükseğini aşarsa long, en düşüğünü kırarsa short."
    markets = BOTH
    category = "breakout"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s = view.now
        if s.donchian_high is None or s.donchian_low is None:
            return None
        if s.close > s.donchian_high:
            excess = (s.close - s.donchian_high) / s.atr
            return StrategySignal(
                self.name,
                1,
                clamp(0.35 + excess / 2),
                f"Kapanış 20 mumluk zirveyi {excess:.2f} ATR aştı",
                stop_atr=2.0,
                target_atr=4.0,
            )
        if s.close < s.donchian_low:
            excess = (s.donchian_low - s.close) / s.atr
            return StrategySignal(
                self.name,
                -1,
                clamp(0.35 + excess / 2),
                f"Kapanış 20 mumluk dibi {excess:.2f} ATR kırdı",
                stop_atr=2.0,
                target_atr=4.0,
            )
        return None


class IchimokuTrend:
    name = "ichimoku_trend"
    title = "Ichimoku bulut trendi"
    description = (
        "Fiyat bulutun üstünde, Tenkan > Kijun ve fiyat 26 mum önceki kapanışın üstündeyse "
        "long; tam tersi short."
    )
    markets = BOTH
    category = "trend"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s = view.now
        top, bottom = s.cloud_top, s.cloud_bottom
        if top is None or bottom is None or s.lagging_ref is None:
            return None
        if s.close > top and s.tenkan > s.kijun and s.close > s.lagging_ref:
            direction = 1
            distance = (s.close - top) / s.atr
        elif s.close < bottom and s.tenkan < s.kijun and s.close < s.lagging_ref:
            direction = -1
            distance = (bottom - s.close) / s.atr
        else:
            return None
        return StrategySignal(
            self.name,
            direction,
            clamp(0.3 + distance / 4),
            f"Fiyat bulutun {'üstünde' if direction == 1 else 'altında'} "
            f"({distance:.1f} ATR), Tenkan/Kijun ve gecikmeli çizgi aynı yönde",
            stop_atr=2.0,
            target_atr=4.0,
        )


class StochRsiCross:
    name = "stoch_rsi_cross"
    title = "Stochastic RSI kesişimi"
    description = "%K, %D'yi 20 altında yukarı keserse long; 80 üstünde aşağı keserse short."
    markets = BOTH
    category = "momentum"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s, p = view.now, view.prev
        if p is None or s.stoch_d is None or p.stoch_d is None:
            return None
        if p.stoch_k <= p.stoch_d and s.stoch_k > s.stoch_d and p.stoch_k < 20:
            return StrategySignal(
                self.name,
                1,
                clamp((20 - p.stoch_k) / 20 + 0.3),
                f"Stoch RSI %K ({s.stoch_k:.0f}) aşırı satımda %D'yi yukarı kesti",
                stop_atr=1.2,
                target_atr=2.0,
            )
        if p.stoch_k >= p.stoch_d and s.stoch_k < s.stoch_d and p.stoch_k > 80:
            return StrategySignal(
                self.name,
                -1,
                clamp((p.stoch_k - 80) / 20 + 0.3),
                f"Stoch RSI %K ({s.stoch_k:.0f}) aşırı alımda %D'yi aşağı kesti",
                stop_atr=1.2,
                target_atr=2.0,
            )
        return None


class VwapReclaim:
    name = "vwap_reclaim"
    title = "VWAP geri alımı"
    description = (
        "Fiyat oturum VWAP'ını yüksek hacimle (z > 1) yukarı keserse long, aşağı keserse short."
    )
    markets = BOTH
    category = "flow"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s, p = view.now, view.prev
        if p is None or s.vwap is None or p.vwap is None or s.volume_z < 1.0:
            return None
        if p.close <= p.vwap < s.close and s.close > s.vwap:
            direction = 1
        elif p.close >= p.vwap > s.close and s.close < s.vwap:
            direction = -1
        else:
            return None
        return StrategySignal(
            self.name,
            direction,
            clamp(0.3 + (s.volume_z - 1) / 4),
            f"Fiyat VWAP'ı {'yukarı' if direction == 1 else 'aşağı'} kesti "
            f"(hacim z={s.volume_z:.1f})",
            stop_atr=1.0,
            target_atr=2.0,
        )


class VolumeThrust:
    name = "volume_thrust"
    title = "Hacimli itki"
    description = (
        "Mum gövdesi 1,5 ATR'den büyük, hacim z > 2 ve agresif alış oranı aynı yöndeyse "
        "(alışta > %60, satışta < %40) devam sinyali."
    )
    markets = BOTH
    category = "flow"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s = view.now
        body = (s.close - s.open) / s.atr
        if abs(body) < 1.5 or s.volume_z < 2.0:
            return None
        if body > 0 and s.taker_buy_ratio > 0.6:
            direction = 1
        elif body < 0 and s.taker_buy_ratio < 0.4:
            direction = -1
        else:
            return None
        return StrategySignal(
            self.name,
            direction,
            clamp(0.3 + (abs(body) - 1.5) / 3 + (s.volume_z - 2) / 6),
            f"{abs(body):.1f} ATR'lik {'yükseliş' if direction == 1 else 'düşüş'} mumu, "
            f"hacim z={s.volume_z:.1f}, agresif alış oranı %{s.taker_buy_ratio * 100:.0f}",
            stop_atr=1.5,
            target_atr=3.0,
        )


class LevelBounce:
    name = "level_bounce"
    title = "Destek/direnç tepkisi"
    description = (
        "Fiyat en az 3 kez test edilmiş bir desteğe 0,5 ATR'den yakınken RSI yukarı dönerse "
        "long; dirence yakınken aşağı dönerse short."
    )
    markets = BOTH
    category = "mean_reversion"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s, p = view.now, view.prev
        if p is None or not view.levels:
            return None
        for level in view.levels:
            if level.touches < 3:
                continue
            distance = abs(s.close - level.price) / s.atr
            if distance > 0.5:
                continue
            if level.kind == "support" and s.rsi > p.rsi and s.close >= level.price:
                return StrategySignal(
                    self.name,
                    1,
                    clamp(0.3 + level.strength / 200 + level.touches / 20),
                    f"{level.touches} kez test edilmiş {level.price:.6g} desteğinde tepki "
                    f"(uzaklık {distance:.2f} ATR)",
                    stop_atr=1.0,
                    target_atr=2.5,
                )
            if level.kind == "resistance" and s.rsi < p.rsi and s.close <= level.price:
                return StrategySignal(
                    self.name,
                    -1,
                    clamp(0.3 + level.strength / 200 + level.touches / 20),
                    f"{level.touches} kez test edilmiş {level.price:.6g} direncinde tepki "
                    f"(uzaklık {distance:.2f} ATR)",
                    stop_atr=1.0,
                    target_atr=2.5,
                )
        return None


class FundingContrarian:
    name = "funding_contrarian"
    title = "Aşırı funding karşıtı"
    description = (
        "Funding çok yüksek (> 3 baz puan) ve kalabalık long ağırlıklıysa short; çok düşükse "
        "(< -3 baz puan) long. Kalabalığın tek tarafa yığılmasından kaynaklanan sıkışma "
        "riskini hedefler."
    )
    markets = FUTURES
    category = "futures"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s = view.now
        if s.funding_rate is None:
            return None
        bps = s.funding_rate * 10_000
        crowd = s.global_long_short
        if bps > 3 and (crowd is None or crowd > 1.5):
            direction = -1
        elif bps < -3 and (crowd is None or crowd < 0.8):
            direction = 1
        else:
            return None
        return StrategySignal(
            self.name,
            direction,
            clamp(0.3 + (abs(bps) - 3) / 10),
            f"Funding {bps:+.1f} baz puan"
            + (f", genel long/short oranı {crowd:.2f}" if crowd is not None else "")
            + f": kalabalık {'long' if direction == -1 else 'short'} tarafta",
            stop_atr=2.0,
            target_atr=3.0,
        )


class OpenInterestTrend:
    name = "open_interest_trend"
    title = "Açık pozisyon teyitli trend"
    description = (
        "Son 4 mumda fiyat ve açık pozisyon birlikte artıyorsa (yeni long'lar) long; fiyat "
        "düşerken açık pozisyon artıyorsa (yeni short'lar) short."
    )
    markets = FUTURES
    category = "futures"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        s, p = view.now, view.prev
        if s.oi_change_4 is None or p is None:
            return None
        price_up = s.close > s.ema21 and s.ema9 > s.ema21
        price_down = s.close < s.ema21 and s.ema9 < s.ema21
        if s.oi_change_4 < 0.01:
            return None  # açık pozisyon belirgin artmıyor
        if price_up:
            direction = 1
        elif price_down:
            direction = -1
        else:
            return None
        return StrategySignal(
            self.name,
            direction,
            clamp(0.3 + s.oi_change_4 * 10),
            f"Açık pozisyon 4 mumda %{s.oi_change_4 * 100:.1f} arttı, fiyat "
            f"{'yükseliyor' if direction == 1 else 'düşüyor'}: yeni pozisyonlar trendi "
            "destekliyor",
        )


class ModelEdge:
    name = "model_edge"
    title = "Makine öğrenmesi modeli"
    description = (
        "Long ve short modellerinin olasılıklarının kendi temel oranlarından farkı. Fark 0,05'ten "
        "büyükse o yönde sinyal. (Modeller tek başına maliyet sonrası kârlı değil; yardımcı "
        "bileşendir.)"
    )
    markets = BOTH
    category = "model"

    def evaluate(self, view: StrategyView) -> StrategySignal | None:
        m = view.model
        if m is None:
            return None
        edge_long = (
            m.p_long - m.base_long if m.p_long is not None and m.base_long is not None else 0.0
        )
        edge_short = (
            m.p_short - m.base_short if m.p_short is not None and m.base_short is not None else 0.0
        )
        edge = edge_long - edge_short
        if abs(edge) < 0.05:
            return None
        direction = 1 if edge > 0 else -1
        return StrategySignal(
            self.name,
            direction,
            clamp(abs(edge) * 4),
            f"Model olasılıkları temel orana göre {'long' if direction == 1 else 'short'} "
            f"yönünde {abs(edge) * 100:.1f} puan farklı",
        )


ALL_STRATEGIES: tuple[Strategy, ...] = (
    EmaTrend(),
    MacdMomentum(),
    RsiReversion(),
    BollingerReversion(),
    SqueezeBreakout(),
    DonchianBreakout(),
    IchimokuTrend(),
    StochRsiCross(),
    VwapReclaim(),
    VolumeThrust(),
    LevelBounce(),
    FundingContrarian(),
    OpenInterestTrend(),
    ModelEdge(),
)


def strategies_for(market: MarketKind) -> tuple[Strategy, ...]:
    return tuple(s for s in ALL_STRATEGIES if market in s.markets)
