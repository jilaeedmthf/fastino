"""Generate real Migen serializer/interpolator RTL for pin-level simulation."""
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys

from migen import *
from migen.fhdl import verilog

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from multispi import MultiSPI
from interpolator import Interpolator


class Pads:
    def __init__(self):
        self.dacs = [Record([("clk", 1), ("nss", 1), ("sdi", 1), ("ldacn", 1)])
                     for _ in range(32)]

    def request(self, name, number):
        assert name == "dac"
        return self.dacs[number]


class Top(Module):
    def __init__(self, serializer, interpolated=False, interpolator_class=Interpolator):
        self.clock_domains.cd_spi = ClockDomain("spi")
        pads = Pads()
        self.submodules.serializer = spi = serializer(pads)
        soft_clear = Signal(name_override="soft_clear")
        clr_n = Signal(name_override="clr_n")
        startup_clear = Signal(name_override="startup_clear")
        busy = Signal(name_override="busy")
        sclk = Signal(32, name_override="sclk")
        nss = Signal(32, name_override="nss")
        sdi = Signal(32, name_override="sdi")
        ldacn = Signal(32, name_override="ldacn")
        self.ios = {self.cd_spi.clk, self.cd_spi.rst, soft_clear, clr_n,
                    startup_clear, busy, sclk, nss, sdi, ldacn}
        self.comb += [
            startup_clear.eq(spi.startup_clear if hasattr(spi, "startup_clear") else 0),
            clr_n.eq(~(soft_clear | self.cd_spi.rst | startup_clear)),
            busy.eq(spi.busy),
            sclk.eq(Cat(p.clk for p in pads.dacs)),
            nss.eq(Cat(p.nss for p in pads.dacs)),
            sdi.eq(Cat(p.sdi for p in pads.dacs)),
            ldacn.eq(Cat(p.ldacn for p in pads.dacs)),
        ]
        if not interpolated:
            data = Signal(544, name_override="data")
            stb = Signal(name_override="stb")
            self.ios |= {data, stb}
            self.comb += [spi.data.eq(data), spi.stb.eq(stb)]
        else:
            self.submodules.int0 = ClockDomainsRenamer("spi")(interpolator_class)(n_channels=16)
            self.submodules.int1 = ClockDomainsRenamer("spi")(interpolator_class)(n_channels=16)
            frame_stb = Signal(name_override="frame_stb")
            frame_typ = Signal(name_override="frame_typ")
            frame_enable = Signal(32, name_override="frame_enable")
            frame_data = Signal(512, name_override="frame_data")
            producer_stb = Signal(name_override="producer_stb")
            producer_enable = Signal(32, name_override="producer_enable")
            self.ios |= {frame_stb, frame_typ, frame_enable, frame_data,
                         producer_stb, producer_enable}
            self.sync.spi += [
                self.int0.stb_in.eq(frame_stb), self.int1.stb_in.eq(frame_stb),
                self.int0.typ.eq(frame_typ), self.int1.typ.eq(frame_typ),
                Cat(self.int0.en_in, self.int1.en_in).eq(frame_enable),
                Cat(self.int0.x, self.int1.x).eq(frame_data),
            ]
            self.comb += [
                spi.stb.eq(self.int0.stb_out & self.int0.cic.ce),
                spi.data.eq(Cat(self.int0.en_out, self.int1.en_out,
                                self.int0.y, self.int1.y)),
                producer_stb.eq(spi.stb),
                producer_enable.eq(Cat(self.int0.en_out, self.int1.en_out)),
            ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    baseline = output / "baseline_multispi.py"
    baseline.write_bytes(subprocess.check_output(
        ["git", "show", "d451a0e88b3302b5f1a7f5e6c1ef48f7a109ab10:multispi.py"], cwd=ROOT))
    spec = importlib.util.spec_from_file_location("baseline_multispi", baseline)
    old = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old)
    old_interpolator = output / "baseline_interpolator.py"
    old_interpolator.write_bytes(subprocess.check_output(
        ["git", "show", "d451a0e88b3302b5f1a7f5e6c1ef48f7a109ab10:interpolator.py"], cwd=ROOT))
    spec = importlib.util.spec_from_file_location("baseline_interpolator", old_interpolator)
    old_int = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(old_int)
    for name, serializer, interpolated in (("candidate", MultiSPI, False),
                                           ("baseline", old.MultiSPI, False),
                                           ("integrated", MultiSPI, True)):
        top = Top(serializer, interpolated)
        verilog.convert(top, ios=top.ios, name=name).write(str(output / (name + ".v")))
    top = Top(MultiSPI, True, old_int.Interpolator)
    verilog.convert(top, ios=top.ios, name="legacy_integrated").write(str(output / "legacy_integrated.v"))


if __name__ == "__main__":
    main()
