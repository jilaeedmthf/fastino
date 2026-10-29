"""Fail closed on the final route's clock checks and the 7 ns sys-to-SPI bound."""
import json
from pathlib import Path
import re
import sys


def check(text):
    attempts = re.findall(r"^Seed (\d+)$", text, re.MULTILINE)
    final = re.split(r"^Seed \d+$", text, flags=re.MULTILINE)[-1]
    if "Program finished normally." not in final or "ERROR:" in final:
        raise ValueError("Final routing attempt did not finish successfully")
    clocks = {}
    for clock, frequency, status, target in re.findall(
            r"Max frequency for clock\s+'([^']+)': ([\d.]+) MHz \((PASS|FAIL) at ([\d.]+) MHz\)", final):
        clocks[clock] = {"maximum_mhz": float(frequency), "required_mhz": float(target), "status": status}
    if set(clocks) != {"sys_clk", "spi_clk", "sr_clk"}:
        raise ValueError("Missing expected clock timing reports")
    targets = {"sys_clk": 35.71, "spi_clk": 47.62, "sr_clk": 250.0}
    if any(clocks[name]["required_mhz"] != target for name, target in targets.items()):
        raise ValueError("Clock constraints differ from the reviewed frequencies")
    if any(c["status"] != "PASS" or c["maximum_mhz"] < c["required_mhz"] for c in clocks.values()):
        raise ValueError("A required clock failed timing")
    edges = dict((name, (launch, capture)) for name, launch, capture in re.findall(
        r"Critical path report for clock '([^']+)' \((posedge|negedge) -> (posedge|negedge)\):", final))
    periods = {"sys_clk": 28.0, "spi_clk": 21.0, "sr_clk": 4.0}
    for name, period in periods.items():
        if name not in edges:
            raise ValueError("Missing critical-path edge classification: " + name)
        launch, capture = edges[name]
        fraction = 1.0 if launch == capture else 0.5
        clocks[name].update({
            "critical_path_edges": launch + " -> " + capture,
            "clock_period_ns": period,
            "available_edge_interval_ns": fraction*period,
            "approximate_setup_allowance_ns": fraction*(period-1000.0/clocks[name]["maximum_mhz"]),
        })
    delays = re.findall(r"Max delay posedge sys_clk -> posedge spi_clk:\s+([\d.]+) ns", final)
    if not delays or float(delays[-1]) >= 7.0:
        raise ValueError("Final sys-to-SPI delay must be strictly below 7 ns")
    return {"passed": True, "attempted_seeds": attempts, "clocks": clocks,
            "sys_to_spi_ns": float(delays[-1]), "sys_to_spi_limit_ns": 7.0,
            "sys_to_spi_allowance_ns": 7.0-float(delays[-1]),
            "allowance_note": "Derived from rounded Fmax and reported edge class; not external-pin timing or a new hold-time signoff",
            "warnings": re.findall(r"^Warning: .*$", text, re.MULTILINE)}


if __name__ == "__main__":
    result = check(Path(sys.argv[1]).read_text())
    print(json.dumps(result, indent=2, sort_keys=True))
