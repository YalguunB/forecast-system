"""profile — цувааны хэв шинж зөвхөн сургалтын цонхноос (FR-S2, FR-E3).

ADI/CV² ангилал: Syntetos, Boylan & Croston (2005)-ын босго 1.32 ба 0.49.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ADI_CUT = 1.32
CV2_CUT = 0.49


def classify(adi: float | None, cv2: float | None) -> str:
    if adi is None or cv2 is None or np.isnan(adi):
        return "no_demand"
    if adi < ADI_CUT:
        return "smooth" if cv2 < CV2_CUT else "erratic"
    return "intermittent" if cv2 < CV2_CUT else "lumpy"


def profile_series(y_train: pd.Series) -> dict:
    """y_train: зорилтын цуваа (NaN = хасагдсан өдөр), сургалтын цонх л."""
    obs = y_train.dropna()
    n = len(obs)
    pos = obs[obs > 0]
    n_pos = int(len(pos))
    zero_share = float((obs == 0).mean()) if n else 1.0
    adi = float(n / n_pos) if n_pos else None
    cv2 = float((pos.std(ddof=0) / pos.mean()) ** 2) if n_pos >= 2 else (0.0 if n_pos == 1 else None)
    acf7 = None
    if n > 14 and obs.std() > 0:
        acf7 = float(obs.autocorr(lag=7))
    strength = None
    if n >= 28 and obs.std() > 0:
        # Улирлын хүч: 1 − Var(R)/Var(S + R), долоо хоногийн дунджийн задлалаар (хөнгөн хувилбар)
        trend = obs.rolling(7, center=True, min_periods=4).mean()
        detr = obs - trend
        seas = detr.groupby(detr.index.dayofweek).transform("mean")
        rem = detr - seas
        denom = np.nanvar(seas + rem)
        if denom > 0:
            strength = float(max(0.0, 1 - np.nanvar(rem) / denom))
    return {"train_n_days": int(len(y_train)), "n_pos": n_pos, "adi": adi, "cv2": cv2,
            "zero_share": zero_share, "acf7": acf7, "seasonal_strength": strength,
            "class": classify(adi, cv2)}
