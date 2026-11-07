"""Model kayıt defteri ve ONNX çıkarımı.

Her model ``models/<kimlik>/`` altında saklanır:

* ``model.onnx``: çıkarım (ONNX Runtime; LightGBM kurulu olmadan da çalışır)
* ``model.txt``: LightGBM yerel biçimi (yeniden eğitim/inceleme)
* ``meta.json``: özellik listesi, etiket tanımı, eğitim dönemi, örneklem dışı metrikler,
  ONNX dosyasının SHA-256 özeti

Yükleme sırasında özet doğrulanır; değiştirilmiş model dosyası kullanılmaz. Dışa aktarımdan
sonra ONNX tahminleri LightGBM tahminleriyle karşılaştırılır; fark varsa model kaydedilmez.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import onnxruntime as ort

from ati_engine.ml.train import TrainReport

_ID_RE = re.compile(r"^[a-z0-9_.-]{1,120}$")
PARITY_TOLERANCE = 1e-4


class ModelError(RuntimeError):
    pass


@dataclass
class ModelMeta:
    id: str
    created_ms: int
    market: str
    symbols: list[str]
    interval: str
    horizon: int
    side: str
    threshold: float
    cost: float
    feature_names: list[str]
    train_start_ms: int
    train_end_ms: int
    rows: int
    onnx_sha256: str
    parity_max_abs_diff: float
    report: dict[str, Any] = field(default_factory=dict)
    disclaimer: str = (
        "Örneklem dışı metrikler geçmiş veride ölçülmüştür; gelecekteki kazancı garanti etmez."
    )


def export_onnx(booster: lgb.Booster, n_features: int) -> bytes:
    from onnxmltools import convert_lightgbm
    from onnxmltools.convert.common.data_types import FloatTensorType

    model = convert_lightgbm(
        booster,
        initial_types=[("input", FloatTensorType([None, n_features]))],
        zipmap=False,
        target_opset=15,
    )
    return bytes(model.SerializeToString())


class Predictor:
    def __init__(self, meta: ModelMeta, onnx_bytes: bytes) -> None:
        self.meta = meta
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        self._session = ort.InferenceSession(
            onnx_bytes, sess_options=options, providers=["CPUExecutionProvider"]
        )
        self._input = self._session.get_inputs()[0].name
        outputs = [o.name for o in self._session.get_outputs()]
        self._prob_output = "probabilities" if "probabilities" in outputs else outputs[-1]

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Pozitif sınıf olasılığı (ör. long modelinde "maliyeti aşan yükseliş")."""
        data = np.ascontiguousarray(X, dtype=np.float32)
        if data.ndim == 1:
            data = data[None, :]
        if data.shape[1] != len(self.meta.feature_names):
            raise ModelError("Özellik sayısı modelle uyuşmuyor")
        (probs,) = self._session.run([self._prob_output], {self._input: data})
        return np.asarray(probs)[:, 1].astype(np.float64)


class ModelRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root

    def _dir(self, model_id: str) -> Path:
        if not _ID_RE.match(model_id):
            raise ModelError("Geçersiz model kimliği")
        return self.root / model_id

    def save(
        self,
        booster: lgb.Booster,
        report: TrainReport,
        *,
        market: str,
        symbols: list[str],
        interval: str,
        horizon: int,
        feature_names: tuple[str, ...],
        train_start_ms: int,
        train_end_ms: int,
        parity_sample: np.ndarray,
    ) -> ModelMeta:
        onnx_bytes = export_onnx(booster, len(feature_names))
        created = int(time.time() * 1000)
        model_id = (
            f"{market}-{'-'.join(s.lower() for s in symbols[:3])}"
            f"{'-plus' if len(symbols) > 3 else ''}-{interval}-h{horizon}-{report.side}-{created}"
        )
        meta = ModelMeta(
            id=model_id,
            created_ms=created,
            market=market,
            symbols=symbols,
            interval=interval,
            horizon=horizon,
            side=report.side,
            threshold=report.threshold,
            cost=report.cost,
            feature_names=list(feature_names),
            train_start_ms=train_start_ms,
            train_end_ms=train_end_ms,
            rows=report.rows,
            onnx_sha256=hashlib.sha256(onnx_bytes).hexdigest(),
            parity_max_abs_diff=0.0,
            report=asdict(report),
        )
        # ONNX ile LightGBM aynı tahmini üretmeli; aksi halde model kaydedilmez.
        predictor = Predictor(meta, onnx_bytes)
        sample = np.ascontiguousarray(parity_sample, dtype=np.float32)
        diff = float(np.max(np.abs(predictor.predict(sample) - booster.predict(sample))))
        if not diff <= PARITY_TOLERANCE:
            raise ModelError(f"ONNX tahminleri LightGBM ile uyuşmuyor (en büyük fark {diff})")
        meta.parity_max_abs_diff = diff
        target = self._dir(model_id)
        target.mkdir(parents=True, exist_ok=False)
        (target / "model.onnx").write_bytes(onnx_bytes)
        booster.save_model(str(target / "model.txt"))
        (target / "meta.json").write_text(
            json.dumps(asdict(meta), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return meta

    def list(self) -> list[ModelMeta]:
        if not self.root.exists():
            return []
        metas = []
        for path in sorted(self.root.glob("*/meta.json")):
            try:
                metas.append(ModelMeta(**json.loads(path.read_text(encoding="utf-8"))))
            except (ValueError, TypeError):
                continue
        return sorted(metas, key=lambda m: -m.created_ms)

    def load(self, model_id: str) -> Predictor:
        target = self._dir(model_id)
        meta_path = target / "meta.json"
        if not meta_path.exists():
            raise ModelError("Model bulunamadı")
        meta = ModelMeta(**json.loads(meta_path.read_text(encoding="utf-8")))
        onnx_bytes = (target / "model.onnx").read_bytes()
        if hashlib.sha256(onnx_bytes).hexdigest() != meta.onnx_sha256:
            raise ModelError("Model dosyası değiştirilmiş (SHA-256 uyuşmuyor); yüklenmedi")
        return Predictor(meta, onnx_bytes)
