"""Elaborate the actual Fastino top level for controlled PLL-fault simulation."""
import argparse
from pathlib import Path
import sys

from migen.fhdl import verilog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastino import Platform
from fastino_phy import Fastino


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    platform = Platform()
    dut = Fastino(platform)
    ios = platform.constraint_manager.get_io_signals() | {dut.status}
    verilog.convert(dut, ios=ios, name="actual_phy",
                    special_overrides=platform.toolchain.special_overrides,
                    attr_translate=platform.toolchain.attr_translate,
                    create_clock_domains=False).write(str(args.output / "actual_phy.v"))
    connections = [".status(status)", ".cbsel(2'b0)", ".sw(2'b0)",
                   ".hw_rev(5'd2)", ".dac_clr_n(clr_n)"]
    for i in range(7):
        connections.append(".eem0_p{}(1'b0)".format("" if i == 0 else "_" + str(i)))
    for i in range(32):
        suffix = "" if i == 0 else "_" + str(i)
        for pin, bus in (("clk", "sclk"), ("nss", "nss"),
                         ("sdi", "sdi"), ("ldacn", "ldacn")):
            connections.append(".dac_{}{}({}[{}])".format(pin, suffix, bus, i))
    (args.output / "phy_connections.vh").write_text(",\n".join(connections) + "\n")


if __name__ == "__main__":
    main()
