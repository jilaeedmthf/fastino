# Fastino startup zero on the v0.2 base

This branch establishes a known zero output after FPGA startup and SPI-domain
reset. It is based on QUARTIQ v0.2, commit
`d451a0e88b3302b5f1a7f5e6c1ef48f7a109ab10`, and was tested on Fastino PCB v1.2
with ARTIQ 8.0+6f600dd and eight-channel grouped writes in October 2026.

## Change

The FPGA asserts global DAC clear while its serializer starts, clocks one
complete `0x8000` midscale word into each of the 32 DACs, then releases clear
after the registered chip-select transition and a two-cycle guard. At the
configured SPI clock that guard is 42 ns. Startup waits for the clocked transfer
to complete, rather than releasing on an independent elapsed-time delay.

The interpolator's pending channel-enable pipeline is reset as well. An
independent regression reproduced stale enabled updates after a warm reset in
the original implementation; clearing that pipeline prevents those pending
updates from undoing the startup zero.

The patch changes only `multispi.py`, `fastino_phy.py` and `interpolator.py`.
The analog-power policy, PLL configuration, EEM protocol, interpolation
arithmetic and normal serializer timing are preserved. Software DAC clear
retains precedence. This does not identify the precise physical cause of the
original approximately -10 V cold-start output.

## Intentional behavior change

**SPI-domain reset now clears all 32 outputs and repeats the midscale transfer.**
This includes recovery from PLL unlock when it asserts that reset. Applications
must reapply desired voltages after such a reset. Writes during the startup
sequence are not queued for replay; ordinary valid writes are accepted once
startup completes. Merely stopping a clock without asserting reset is not a
guarantee that the outputs will clear.

The ARTIQ Python API and grouped-write format do not change. The pinned
ARTIQ 8 `Fastino.init()` does not assert SPI/PLL reset and is not a replacement
for explicitly commanding the desired output voltages.

## Validation

Digital tests use generated Migen RTL, the Yosys iCE40 SB_IO model and an
AD5542A DAC model. Checks cover all 32 channels, undefined/random DAC serial
register contents, clock/startup interruptions, software clear, complete first
midscale transfers, and normal transfer values/masks/timing against v0.2.
Real-interpolator warm-reset tests start from known nonzero outputs and cover
19 reset phases. The original pending-enable pipeline fails the negative
control as expected. Separate unknown-RAM cold-idle tests are retained; active
tests use the zero RAM initialization verified in the packed image.

The final FPGA build passed routing and timing with nextpnr seed 3. Seeds 1 and
2 failed the serial timing requirement and were not used. Final reported maxima
were 82.52 MHz for sys, 68.01 MHz for SPI and 313.28 MHz for serial, above the
required 35.71, 47.62 and 250 MHz respectively. The checked sys-to-SPI path was
2.54 ns against the 7 ns requirement. A clean rebuild produced an identical
binary, synthesis JSON and routed ASC. Inherited tool warnings are recorded
in the laboratory build evidence; successful timing is not analog proof.

Bench observations on 2026-10-25 and 2026-10-26:

| Check | Observed result |
| --- | --- |
| Before the patch | CH0 approximately -10 V after whole-crate cold starts |
| Candidate FPGA reload | CH0 at 0 V without a host voltage-setting kernel |
| Candidate whole-crate cold start | First CH0 check at 0 V; subsequent operator survey reports all 32 outputs at 0 V |
| Two analog startup traces | Operator reports approximately 200 ms nonzero, magnitude below 1 V, accepted for that application; output numbers were not recorded |
| Normal CH0 programming, R1 | Approximately 1 V pulse, approximately 20 us long, returns to zero |
| CIC R16 and R64 | Approximately 1 V, rounded edges; R64 visibly slower than R16; return-to-zero checks confirmed |

These are operator-reported analog observations. Native waveform exports and
calibrated timing/error bounds are not part of this branch. All-channel
settled zero does not establish zero throughout power-up. FPGA preconfiguration
pins, analog-rail sequencing, other hardware revisions and higher CIC rates
have not been physically qualified by these tests. Full command, build,
readback and recovery records remain in the laboratory bench archive.

## Reproducing the recorded build and simulations

`offline_tests` contains the unchanged scripts used for the verified candidate.
They target the recorded Nix environment and place generated results under
`/tmp`; their absolute dependency paths are intentional provenance, not a
portable installation recipe. Run build before simulation, because the latter
checks RAM initialization from that packed build:

```bash
bash offline_tests/build_candidate.sh
bash offline_tests/run_checks.sh
```

Recorded tools: Python 3.12.7, Migen 0.9.2, MiSoC 0.13, Yosys 0.47,
nextpnr 0.7, IceStorm 2020.12.04 and Icarus Verilog 12.0. Migen/MiSoC differ
from the commits listed in upstream requirements.txt; those upstream commits
also elaborated but RTL equivalence was not established. The tested package
paths are explicit in the scripts. Adapting the scripts to another environment
requires new validation; this branch does not claim portable reproducibility.

Installed/tested binary: 135,100 bytes, SHA-256
`1dcbdab60794b80f86b6f1e23d0f2de77674e569622b142d36f69fac268bf47a`.
The binary is retained in the laboratory archive; it is not automatically
rebuilt or installed by these instructions.

## Maintenance and recovery

Before changing an existing board, preserve and verify its appropriate original
flash image. The laboratory installation retained two independently read,
matching full 1 MiB backups before programming and independently verified the
complete installed array afterward. That procedure is specific to the
identified flash, board and programmer; do not assume its size applies to
another board.

Upstream `flash_fastino.py` resets/reloads the FPGA even on its read path.
Treat readback as output-affecting maintenance. Keep experimental loads isolated
through programming/recovery and physically establish the required output state
before reconnecting them. Retain a working programming path and original image.
