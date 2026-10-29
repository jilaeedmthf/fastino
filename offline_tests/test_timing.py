"""Check routed-timing acceptance boundaries and half-cycle reporting."""
import math
import unittest

from check_timing import check


REPORT = """Seed 2
Info: Critical path report for clock 'sys_clk' (posedge -> posedge):
Info: Critical path report for clock 'spi_clk' (posedge -> posedge):
Info: Critical path report for clock 'sr_clk' (negedge -> posedge):
Info: Max frequency for clock 'sys_clk': 72.06 MHz (PASS at 35.71 MHz)
Info: Max frequency for clock 'spi_clk': 68.01 MHz (PASS at 47.62 MHz)
Info: Max frequency for clock 'sr_clk': 313.28 MHz (PASS at 250.00 MHz)
Info: Max delay posedge sys_clk -> posedge spi_clk: 3.39 ns
Info: Program finished normally.
"""


class TimingReportTest(unittest.TestCase):
    def test_half_cycle_allowance(self):
        result = check(REPORT)
        serial = result["clocks"]["sr_clk"]
        self.assertEqual(serial["available_edge_interval_ns"], 2.0)
        self.assertTrue(math.isclose(serial["approximate_setup_allowance_ns"],
                                     0.4039836568, abs_tol=1e-9))
        self.assertAlmostEqual(result["sys_to_spi_allowance_ns"], 3.61)

    def test_only_final_route_counts(self):
        result = check("Seed 1\nERROR: timing failed\n" + REPORT)
        self.assertEqual(result["attempted_seeds"], ["1", "2"])
        with self.assertRaises(ValueError):
            check(REPORT + "Seed 3\nERROR: routing failed\n")

    def test_rejects_missing_or_relaxed_evidence(self):
        replacements = [
            ("Program finished normally.", "unfinished"),
            ("(negedge -> posedge)", "(unknown edges)"),
            ("PASS at 250.00 MHz", "PASS at 249.00 MHz"),
            ("313.28 MHz", "249.99 MHz"),
            ("PASS at 47.62 MHz", "FAIL at 47.62 MHz"),
            ("3.39 ns", "7.00 ns"),
            ("clock 'spi_clk':", "clock 'unexpected_clk':"),
        ]
        for old, new in replacements:
            with self.subTest(old=old, new=new), self.assertRaises(ValueError):
                check(REPORT.replace(old, new))


if __name__ == "__main__":
    unittest.main()
