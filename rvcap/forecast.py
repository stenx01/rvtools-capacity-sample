from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd


def linear_forecast(
    dates: list[date],
    values: list[float],
    periods: int = 12,
    step_days: int = 7,
) -> pd.DataFrame | None:
    pairs = [
        (d, float(v))
        for d, v in zip(dates, values)
        if v is not None and not (isinstance(v, float) and np.isnan(v))
    ]
    if len(pairs) < 4:
        return None
    xs = np.array([(d - pairs[0][0]).days for d, _ in pairs], dtype=float)
    ys = np.array([v for _, v in pairs], dtype=float)
    if np.allclose(ys, ys[0]):
        slope = 0.0
        intercept = ys[0]
    else:
        slope, intercept = np.polyfit(xs, ys, 1)
    last = pairs[-1][0]
    rows = []
    for i in range(1, periods + 1):
        future = last + timedelta(days=step_days * i)
        x = (future - pairs[0][0]).days
        rows.append({"date": future, "value": float(intercept + slope * x)})
    return pd.DataFrame(rows)
