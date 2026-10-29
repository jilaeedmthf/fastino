from math import gcd

from migen import *
from migen.genlib.cdc import AsyncResetSynchronizer, MultiReg

from interpolator import Interpolator
from frame import Frame
from multispi import MultiSPI
from link import Link


class Fastino(Module):
    def __init__(self, platform):
        n_bits = 16
        n_frame = 14
        t_clk = 4.

        self.submodules.link = Link(
            clk=platform.request("eem0_p", 0),
            data=[platform.request("eem0_p", i + 1) for i in range(6)],
            platform=platform,
            t_clk=t_clk)

        cd_sys = ClockDomain("sys")
        self.clock_domains += cd_sys
        self.comb += [
            cd_sys.rst.eq(ResetSignal("word")),
            cd_sys.clk.eq(ClockSignal("word")),
        ]
        # platform.add_period_constraint(cd_sys.clk, t_clk*link.n_div)

        self.submodules.frame = Frame()
        self.comb += self.frame.word.eq(self.link.word)

        adr = Signal(4)
        cfg = Record([
            ("rst", 1),
            ("afe_pwr_n", 1),
            ("dac_clr", 1),
            ("clr_err", 1),
            ("led", 8),
            ("typ", 1),
            ("reserved", 7),
        ])
        cfg_comb = Record(cfg.layout)
        unlock = Signal(reset=1)
        spi_ready = Signal()

        # slow MISO lane, TBD
        sdo = Signal()
        self.specials += [
            Instance(
                "SB_IO",
                p_PIN_TYPE=C(0b010100, 6),  # output registered
                p_IO_STANDARD="SB_LVCMOS",
                i_OUTPUT_CLK=ClockSignal("word"),
                o_PACKAGE_PIN=platform.request("eem0_p", 7),
                i_D_OUT_0=sdo),  # falling SCK
            Instance(
                "SB_IO",
                p_PIN_TYPE=C(0b011100, 6),  # output registered inverted
                p_IO_STANDARD="SB_LVCMOS",
                i_OUTPUT_CLK=ClockSignal("word"),
                o_PACKAGE_PIN=platform.request("eem0_n", 7),
                i_D_OUT_0=sdo),  # falling SCK
        ]
        sr = Signal(n_frame, reset_less=True)
        # status register
        status = Signal((1 << len(adr))*len(sr))
        status_ = Cat(C(0xfa, 8),  # ID
                      platform.request("cbsel"),
                      platform.request("sw"),
                      platform.request("hw_rev"),
                      C(1, 3),  # fork status ABI v1; not an upstream release
                      unlock,
                      self.link.delay,
                      self.link.align_err,
                      self.frame.crc_err,
                      cfg.raw_bits(),
                      spi_ready)  # bit 61; legacy offsets above stay unchanged
        # One source-coherent diagnostic word. Ready means serializer startup
        # completed, not CIC initialization, valid gain or a fresh host read.
        # Word 5: ready, reset_seen, 12-bit signature/version 0xa51.
        status_ = Cat(status_, C(0, 70 - len(status_)),
                      spi_ready, unlock, C(0xa51, 12))
        self.status = status
        assert len(status_) <= len(status)

        self.comb += [
            cfg_comb.raw_bits().eq(self.frame.body),
            status.eq(status_),
            sdo.eq(sr[-1]),  # MSB first
            adr.eq(self.frame.body[len(cfg):]),
        ]
        have_crc_err = Signal()
        self.sync += [
            sr[1:].eq(sr),
            If(self.frame.stb,
                cfg.raw_bits().eq(cfg_comb.raw_bits()),
                # grab data from status register according to address
                sr.eq(Array([status[i*n_frame:(i + 1)*n_frame]
                    for i in range(1 << len(adr))])[adr]),
            ),
            If(cfg.clr_err,
                self.frame.crc_err.eq(0),
            ),
            have_crc_err.eq(self.frame.crc_err != 0),
        ]
        have_align_err = Signal()
        self.sync.word += [
            If(cfg.clr_err,
                self.link.align_err.eq(0),
            ),
            have_align_err.eq(self.link.align_err != 0)
        ]

        # set up spi clock to 7*t_clk*3/4 = 21 ns
        cd_spi = ClockDomain("spi")
        self.clock_domains += cd_spi
        divr = 3 - 1
        divf = 4 - 1
        divq = 4
        t_out = t_clk*self.link.n_div*(divr + 1)/(divf + 1)  # *2**divq
        assert t_out >= 20., t_out
        assert t_out < t_clk*self.link.n_div
        platform.add_period_constraint(cd_spi.clk, t_out)
        # calculate the minimum delay between the 28 ns word clock
        # and the 21 ns SPI clock: 7ns, if this is large enough we don't need a
        # synchronizer (see below)
        print("Check 'Max delay posedge sys_clk -> posedge spi_clk' <",
            min((i*t_out) % (t_clk*self.link.n_div)
                for i in range(1, (divf + 1)//gcd(divr + 1, divf + 1))))
        t_idle = n_frame*t_clk*self.link.n_div - (n_bits + 1)*t_out
        assert t_idle >= 0, t_idle
        t_vco = t_out/2**divq
        assert .533 <= 1/t_vco <= 1.066, 1/t_vco

        locked = Signal()
        self.specials += [
            Instance(
                "SB_PLL40_CORE",
                p_FEEDBACK_PATH="DELAY",
                p_DIVR=divr,  # input
                p_DIVF=divf,  # feedback
                p_DIVQ=divq,  # vco
                p_FILTER_RANGE=1,
                p_PLLOUT_SELECT="GENCLK",
                p_ENABLE_ICEGATE=1,
                p_DELAY_ADJUSTMENT_MODE_FEEDBACK="DYNAMIC",
                p_FDA_FEEDBACK=0xf,
                p_DELAY_ADJUSTMENT_MODE_RELATIVE="DYNAMIC",
                p_FDA_RELATIVE=0xf,
                i_BYPASS=0,
                i_RESETB=~(cfg.rst | ResetSignal("word")),
                i_DYNAMICDELAY=Cat(self.link.delay, self.link.delay_relative),
                i_REFERENCECLK=ClockSignal("link"),
                i_LATCHINPUTVALUE=0,
                o_LOCK=locked,
                o_PLLOUTGLOBAL=cd_spi.clk,
                # o_PLLOUTCORE=,
            ),
            AsyncResetSynchronizer(cd_spi, ~locked),
        ]

        self.submodules.int0 = ClockDomainsRenamer("spi")(Interpolator)(
            n_channels=16)
        self.submodules.int1 = ClockDomainsRenamer("spi")(Interpolator)(
            n_channels=16)

        # no cdc, assume timing is synchronous and comensurate such that
        # max data delay sys-spi < min sys-spi clock delay over all alignments
        body = Cat(
                self.int0.en_in,
                self.int1.en_in,
                self.int0.x,
                self.int1.x,
        )
        self.sync.spi += [  # this should be comb but the stb path is long
            self.int0.stb_in.eq(self.frame.stb),
            self.int1.stb_in.eq(self.frame.stb),
            body.eq(self.frame.body[-len(body):]),
            self.int0.typ.eq(cfg_comb.typ),
            self.int1.typ.eq(cfg_comb.typ),
        ]

        self.submodules.spi = MultiSPI(platform)
        assert len(body) == len(self.spi.data)
        assert len(cfg) + len(adr) + len(self.spi.data) == len(self.frame.body)

        body = Cat(
                self.int0.en_out,
                self.int1.en_out,
                self.int0.y,
                self.int1.y,
        )
        assert len(body) == len(self.spi.data)
        self.comb += [
            self.spi.stb.eq(self.int0.stb_out & self.int0.cic.ce),
            self.spi.data.eq(body),
        #    self.spi.data.eq(self.frame.body[-len(self.spi.data):]),
        #    self.spi.stb.eq(self.frame.stb),
        ]

        # Capture every assertion of the existing asynchronous SPI reset chain,
        # even if SPI or word clocks stop. A native async-set flop retains the
        # event; sys-domain synchronizers keep its asynchronous output out of
        # the serialized status logic. Reset assertion dominates acknowledgement.
        reset_seen = Signal()
        ready_raw = Signal()
        clr_err_previous = Signal()
        acknowledge_armed = Signal()
        acknowledge = Signal()
        self.comb += [
            ready_raw.eq(~(ResetSignal("spi") | self.spi.startup_clear)),
            acknowledge.eq(cfg.clr_err & ~clr_err_previous &
                           acknowledge_armed & spi_ready & ready_raw &
                           ~ResetSignal("sys")),
        ]
        self.sync += clr_err_previous.eq(cfg.clr_err)
        self.specials += [
            # A reset invalidates even a pending acknowledgement while sys is
            # stopped. Only an actual low frame after reset release can rearm;
            # cfg's reset default is not a received command. High consumes the
            # arm even if readiness rejects acknowledgement at that edge.
            Instance("SB_DFFR", i_C=ClockSignal("sys"),
                     i_R=ResetSignal("spi") | ResetSignal("sys"),
                     i_D=(self.frame.stb & ~cfg_comb.clr_err) |
                         (acknowledge_armed & ~cfg.clr_err),
                     o_Q=acknowledge_armed),
            Instance("SB_DFFS", i_C=ClockSignal("sys"),
                     i_S=ResetSignal("spi") | ResetSignal("sys"),
                     i_D=reset_seen & ~acknowledge, o_Q=reset_seen),
            MultiReg(reset_seen, unlock, "sys", reset=1),
            MultiReg(ready_raw, spi_ready, "sys"),
        ]

        self.comb += [
            # SPI reset intentionally clears previously commanded outputs.
            # Keep assertion independent of a running SPI clock; release only
            # after the serializer has completed its startup midscale transfer.
            platform.request("dac_clr_n").eq(
                ~(cfg.dac_clr | ResetSignal("spi") | self.spi.startup_clear)),
            platform.request("en_afe_pwr").eq(~cfg.afe_pwr_n),
            #platform.request("test_point", 2).eq(self.link.delay[0]),
            #platform.request("test_point", 3).eq(self.link.delay[1]),
            #platform.request("test_point", 3).eq(self.spi.busy),
            #platform.request("test_point", 4).eq(self.frame.stb),
            Cat(platform.request("user_led", i) for i in range(9)).eq(Cat(
                cfg.led,
                ResetSignal("spi") | have_align_err | have_crc_err,  # RED
            )),
        ]
        self.specials += [
            Instance(
                "SB_IO",
                p_PIN_TYPE=C(0b010000, 6),  # output registered DDR
                p_IO_STANDARD="SB_LVCMOS",
                i_OUTPUT_CLK=ClockSignal("link"),
                #i_CLOCK_ENABLE=1,
                o_PACKAGE_PIN=platform.request("test_point", 0),
                i_D_OUT_0=1,
                i_D_OUT_1=0),
            Instance(
                "SB_IO",
                p_PIN_TYPE=C(0b010000, 6),  # output registered DDR
                p_IO_STANDARD="SB_LVCMOS",
                i_OUTPUT_CLK=ClockSignal("word"),
                #i_CLOCK_ENABLE=1,
                o_PACKAGE_PIN=platform.request("test_point", 1),
                i_D_OUT_0=1,
                i_D_OUT_1=0),
        ]


if __name__ == "__main__":
    from fastino import Platform
    platform = Platform()
    platform.toolchain.nextpnr_build_template[1:2] = [
        "for seed in `seq 1 10`; do",
        "echo Seed $seed",
        ("nextpnr-ice40 {pnr_pkg_opts} --pcf {build_name}.pcf --json {build_name}.json "
        "--asc {build_name}.txt --pre-pack {build_name}_pre_pack.py --seed $seed && break"),
        "done"
    ]
    fastino = Fastino(platform)
    platform.build(fastino, build_name="fastino")
