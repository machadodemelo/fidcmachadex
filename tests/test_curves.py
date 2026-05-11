from __future__ import annotations

import unittest

from services.fidc_model.curves import (
    INTERPOLATION_METHOD_FLAT_FORWARD_252,
    INTERPOLATION_METHOD_SPLINE,
    flat_forward_252,
    interpolate_curve,
)


class CurveInterpolationTest(unittest.TestCase):
    def test_flat_forward_252_interpolates_accumulated_factors(self):
        xs = [21.0, 42.0]
        ys = [0.13, 0.15]
        x = 35.0

        left_factor = (1.0 + ys[0]) ** (xs[0] / 252.0)
        right_factor = (1.0 + ys[1]) ** (xs[1] / 252.0)
        expected_factor = left_factor * ((right_factor / left_factor) ** ((x - xs[0]) / (xs[1] - xs[0])))
        expected_rate = expected_factor ** (252.0 / x) - 1.0

        self.assertAlmostEqual(expected_rate, flat_forward_252(x, xs, ys), delta=1e-12)

    def test_flat_forward_252_preserves_vertices(self):
        xs = [21.0, 42.0, 63.0]
        ys = [0.13, 0.15, 0.16]

        self.assertAlmostEqual(0.13, flat_forward_252(21.0, xs, ys), delta=1e-12)
        self.assertAlmostEqual(0.15, flat_forward_252(42.0, xs, ys), delta=1e-12)

    def test_interpolate_curve_dispatches_methods(self):
        xs = [1.0, 10.0, 20.0]
        ys = [0.10, 0.12, 0.13]

        self.assertEqual(flat_forward_252(12.0, xs, ys), interpolate_curve(12.0, xs, ys, method=INTERPOLATION_METHOD_FLAT_FORWARD_252))
        self.assertIsInstance(interpolate_curve(12.0, xs, ys, method=INTERPOLATION_METHOD_SPLINE), float)

    def test_interpolate_curve_rejects_unknown_method(self):
        with self.assertRaisesRegex(ValueError, "Metodologia"):
            interpolate_curve(12.0, [1.0, 10.0], [0.10, 0.12], method="linear")


if __name__ == "__main__":
    unittest.main()
