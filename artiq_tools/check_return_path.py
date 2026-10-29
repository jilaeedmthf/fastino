"""Replay phase-controlled MISO into the exact pinned Kasli SerDes class.

This is a digital transport sensitivity check, not a model of physical PLL,
EEM delay, receiver bit-slip or the complete Fastino top. It establishes why
an unqualified cache index/bit alignment must not be assumed by the probe.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import random

from migen import *
from migen.sim import run_simulation
from misoc.cores.liteeth_mini.mac.crc import LiteEthMACCRCEngine


PINNED_FASTLINK_SHA256 = "6c914f5f123d944f121117d5242026cae70b7e286e3a5e8edfda671b15cde2ea"


def load_serializer(path):
    source = path.read_bytes()
    if hashlib.sha256(source).hexdigest() != PINNED_FASTLINK_SHA256:
        raise ValueError("Expected the recorded installed ARTIQ 8 fastlink.py")
    tree = ast.parse(source)
    serializer = next(node for node in tree.body
                      if isinstance(node, ast.ClassDef) and node.name == "SerDes")
    # Compile the unchanged class, avoiding ARTIQ's unrelated package imports.
    namespace = dict(globals())
    exec(compile(ast.Module(body=[serializer], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["SerDes"]


def replay(serializer, words, delay_ticks):
    class Receiver(Module):
        def __init__(self):
            self.clock_domains.cd_rio_phy = ClockDomain("rio_phy")
            self.submodules.serializer = serializer(n_data=8, t_clk=7, n_frame=14)
            self.address = Signal(4)
            self.capture = Signal(14)
            self.capture_address = Signal(4)
            self.capture_strobe = Signal()
            # Same current-address cache association as the installed Fastino PHY.
            self.sync.rio_phy += [
                self.capture_strobe.eq(self.serializer.stb),
                If(self.serializer.stb,
                   self.capture.eq(self.serializer.readback),
                   self.capture_address.eq(self.address),
                   self.address.eq(self.address + 1))]

    receiver = Receiver()
    captures = []
    def bit(tick):
        if tick < 0:
            return 0
        # Fastino transmits each status word MSB first, one bit per 28 ns
        # word clock. Kasli samples DDR at two samples per 8 ns RTIO cycle.
        word = words[(tick // 98) % 16]
        return (word >> (13 - (tick % 98) // 7)) & 1
    def stimulus():
        for cycle in range(49 * 16 * 3 + 1):
            if (yield receiver.capture_strobe):
                captures.append(((yield receiver.capture_address),
                                 (yield receiver.capture)))
            # The first generator activation follows the first rio_phy edge:
            # the serializer counter has already consumed the first pair.
            tick = cycle * 2 + 2 - delay_ticks
            # data[0] is the newest sample in the receive shift register.
            yield receiver.serializer.data[-1].eq(bit(tick + 1) | (bit(tick) << 1))
            yield
    run_simulation(receiver, {"rio_phy": stimulus()}, clocks={"rio_phy": 8})
    cache = dict(captures[-16:])
    if len(cache) != 16:
        raise AssertionError("Incomplete cache capture")
    # Independent sampling equation: the final sample of each 98-tick frame
    # and every seventh older sample form the 14-bit cache word, newest first.
    # Start a full 16-word period later so delay never addresses startup fill.
    reference = [sum(bit(98 * (address + 17) - 1 - delay_ticks - 7 * sample) << sample
                     for sample in range(14)) for address in range(16)]
    if [cache[i] for i in range(16)] != reference:
        raise AssertionError("RTL cache differs from independent sampling equation")
    shifts = [shift for shift in range(16)
              if all(cache[address] == words[(address - shift) % 16] for address in range(16))]
    return {"delay_serial_ticks": delay_ticks, "delay_ns": delay_ticks * 4,
            "cache_words": [cache[i] for i in range(16)],
            "independent_sampling_equation_matches": True,
            "whole_word_address_shifts": shifts,
            "all_words_directly_equal_same_address": all(cache[i] == words[i] for i in range(16))}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fastlink-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    serializer = load_serializer(args.fastlink_source)
    rng = random.Random(20261028)
    words = rng.sample(range(1 << 14), 16)
    words[5] = (0xA51 << 2) | 3
    cases = [replay(serializer, words, delay) for delay in (0, 1, 6, 7, 14, 49, 98, 105)]
    assert cases[0]["whole_word_address_shifts"] == [0]
    assert cases[1]["whole_word_address_shifts"] == [0]
    assert cases[2]["whole_word_address_shifts"] == [0]
    assert cases[3]["whole_word_address_shifts"] == []
    assert cases[6]["whole_word_address_shifts"] == [1]
    assert cases[7]["whole_word_address_shifts"] == []
    report = {"passed": True, "fastlink_sha256": PINNED_FASTLINK_SHA256,
              "source_words": words, "cases": cases,
              "actual_SerDes_class_used": True,
              "cache_address_logic": "matches installed Fastino PHY current header.addr association",
              "physical_phase_or_delay_measured": False,
              "full_link_PLL_frame_decoder_modeled": False,
              "conclusion": "An integer-frame return delay changes cache address; a status-bit delay can splice adjacent words. No universal cache index or bit-phase mapping is established."}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(report, handle, indent=2)
        handle.write("\n")
    print(json.dumps({"passed": True, "cases": [{k: c[k] for k in ("delay_ns", "whole_word_address_shifts")} for c in cases]}))


if __name__ == "__main__":
    main()
