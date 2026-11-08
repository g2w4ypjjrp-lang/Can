"""Risk kapısı onayı: giriş emirlerinin tek kapısı.

Pozisyon açan veya büyüten her emir (``entry``, ``scale_in``), risk kapısının o emir için
ürettiği **imzalı, süreli ve tek kullanımlık** bir onayla gönderilebilir. Onayı yalnızca risk
kapısı üretebilir (anahtarı süreç belleğindedir); emir yöneticisi her giriş emrini göndermeden
önce onayı doğrular. Böylece risk kapısını atlayıp giriş emri gönderen bir kod yolu kalmaz.

Riski azaltan emirler (zarar durdur, hedef, çıkış) onay gerektirmez ama yönleri denetlenir:
Futures'ta ``reduceOnly``/``closePosition`` zorunludur; Spot'ta yalnızca satış olabilir
(Spot'ta açığa satış yoktur, satış ancak eldeki varlıkla yapılabilir).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

from ati_engine.core.models import Market, Side, TradingMode
from ati_engine.execution.venue import ExecutionBlocked, OrderRequest

if TYPE_CHECKING:
    from ati_engine.execution.engine import TradeIntent, TradingEngine

ENTRY_PURPOSES = frozenset({"entry", "scale_in"})


class ApprovalError(ExecutionBlocked):
    """Giriş emri geçerli bir risk kapısı onayı taşımıyor."""


@dataclass(frozen=True)
class RiskApproval:
    decision_id: str
    mode: TradingMode
    market: Market
    symbol: str
    side: Side
    max_quantity: Decimal
    expires_ms: int
    nonce: str
    mac: str


@dataclass(frozen=True)
class RiskReason:
    code: str
    message: str


@dataclass(frozen=True)
class RiskDecision:
    approved: bool
    reasons: tuple[RiskReason, ...] = ()
    metrics: dict[str, Any] = field(default_factory=dict)
    approval: RiskApproval | None = None

    @property
    def summary(self) -> str:
        return "; ".join(r.message for r in self.reasons) or "onaylandı"


class RiskRejected(ExecutionBlocked):
    """Risk kapısı işlemi reddetti (gerekçeler ``decision.reasons`` içinde)."""

    def __init__(self, decision: RiskDecision) -> None:
        super().__init__("Risk kapısı reddetti: " + decision.summary)
        self.decision = decision


class ApprovalVerifier(Protocol):
    def verify(
        self,
        approval: RiskApproval | None,
        request: OrderRequest,
        *,
        mode: TradingMode,
        market: Market,
    ) -> None:
        """Geçersizse ``ApprovalError`` fırlatır; geçerliyse onayı tüketir."""
        ...


class RiskGateLike(ApprovalVerifier, Protocol):
    async def evaluate(self, intent: TradeIntent, engine: TradingEngine) -> RiskDecision: ...


def check_risk_reducing(request: OrderRequest, market: Market) -> None:
    """Onaysız gönderilebilecek emirlerin riski artıramayacağını denetler."""
    if market is Market.USDM_FUTURES:
        if not (request.reduce_only or request.close_position):
            raise ApprovalError(
                f"'{request.purpose}' emri reduceOnly/closePosition olmadan gönderilemez"
            )
        return
    if request.side is not Side.SELL:
        raise ApprovalError(f"Spot'ta '{request.purpose}' emri yalnızca satış olabilir")
