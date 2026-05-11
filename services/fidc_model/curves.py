from __future__ import annotations

from typing import Sequence


INTERPOLATION_METHOD_SPLINE = "spline"
INTERPOLATION_METHOD_FLAT_FORWARD_252 = "flat_forward_252"


def _spline_coefficients(xs: Sequence[float], ys: Sequence[float]) -> tuple[list[float], list[float], list[float], list[float]]:
    n = len(xs)
    if n < 2:
        raise ValueError("Need at least two points for spline interpolation.")

    a = list(ys)
    b = [0.0] * (n - 1)
    c = [0.0] * n
    d = [0.0] * (n - 1)
    h = [xs[i + 1] - xs[i] for i in range(n - 1)]
    alpha = [0.0] * n
    for i in range(1, n - 1):
        alpha[i] = (3.0 / h[i]) * (a[i + 1] - a[i]) - (3.0 / h[i - 1]) * (a[i] - a[i - 1])

    l = [1.0] * n
    mu = [0.0] * n
    z = [0.0] * n
    for i in range(1, n - 1):
        l[i] = 2.0 * (xs[i + 1] - xs[i - 1]) - h[i - 1] * mu[i - 1]
        mu[i] = h[i] / l[i]
        z[i] = (alpha[i] - h[i - 1] * z[i - 1]) / l[i]

    for j in range(n - 2, -1, -1):
        c[j] = z[j] - mu[j] * c[j + 1]
        b[j] = (a[j + 1] - a[j]) / h[j] - h[j] * (c[j + 1] + 2.0 * c[j]) / 3.0
        d[j] = (c[j + 1] - c[j]) / (3.0 * h[j])

    return a, b, c, d


def cubic_spline(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) < 2:
        return float(ys[0]) if ys else 0.0

    a, b, c, d = _spline_coefficients(xs, ys)
    if x <= xs[0]:
        slope = b[0]
        return a[0] + slope * (x - xs[0])
    if x >= xs[-1]:
        span = xs[-1] - xs[-2]
        slope = b[-1] + 2.0 * c[-1] * span + 3.0 * d[-1] * (span**2)
        return a[-1] + slope * (x - xs[-1])

    i = 0
    while i < len(xs) - 1 and xs[i + 1] < x:
        i += 1
    dx = x - xs[i]
    return a[i] + b[i] * dx + c[i] * (dx**2) + d[i] * (dx**3)


def flat_forward_252(x: float, xs: Sequence[float], ys: Sequence[float]) -> float:
    if len(xs) < 2:
        return float(ys[0]) if ys else 0.0
    if x <= 0:
        return float(ys[0])

    index = 0
    if x <= xs[0]:
        index = 0
    elif x >= xs[-1]:
        index = len(xs) - 2
    else:
        while index < len(xs) - 1 and xs[index + 1] < x:
            index += 1

    left_du = float(xs[index])
    right_du = float(xs[index + 1])
    left_rate = float(ys[index])
    right_rate = float(ys[index + 1])
    if right_du == left_du:
        return left_rate
    if left_rate <= -1.0 or right_rate <= -1.0:
        raise ValueError("Flat Forward 252 exige taxas maiores que -100%.")

    left_factor = (1.0 + left_rate) ** (left_du / 252.0)
    right_factor = (1.0 + right_rate) ** (right_du / 252.0)
    weight = (x - left_du) / (right_du - left_du)
    interpolated_factor = left_factor * ((right_factor / left_factor) ** weight)
    return interpolated_factor ** (252.0 / x) - 1.0


def interpolate_curve(
    x: float,
    xs: Sequence[float],
    ys: Sequence[float],
    *,
    method: str = INTERPOLATION_METHOD_SPLINE,
) -> float:
    if method == INTERPOLATION_METHOD_FLAT_FORWARD_252:
        return flat_forward_252(x, xs, ys)
    if method == INTERPOLATION_METHOD_SPLINE:
        return cubic_spline(x, xs, ys)
    raise ValueError(f"Metodologia de interpolação inválida: {method}")
