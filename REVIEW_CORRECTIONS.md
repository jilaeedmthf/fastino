# Startup-zero review corrections

This work starts from `baa5bf7a687bbaaee2451b08fef85c87f78b55e6` and addresses
the independent review of that startup-zero patch. The revised image was
installed on 2026-10-28 and passed the all-channel cold-start and CH0
R1/R16/R64 checks on 2026-10-29. The separate earlier observations in
`STARTUP_ZERO.md` belong to the preceding image; the new results are below.

The reset policy is unchanged: startup and SPI-domain reset clear all 32 DACs
and transmit complete midscale words before releasing clear. A later PLL loss
can therefore zero outputs. Reporting that event does not prevent it. The
physical rate of tracking-related PLL losses and uninterrupted operation over
hours remain bench questions.

## Status contract

Existing fields retain their offsets. The three-bit gateware field is a fork
status ABI identifier, not a claim to be an upstream version release.

| Global status bits | Meaning |
| --- | --- |
| 17–19 | Fork status ABI version 1 |
| 20 | Sticky history of startup/SPI reset, including deliberate reset |
| 61 | Synchronized serializer-startup completion indication |
| 70–83, word 5 | Bit 0: startup complete; bit 1: reset history; bits 2–13: signature `0xA51` |

Word 5 is sampled as a unit by Fastino's return serializer. This does not
establish which Kasli cache index contains it, whether a received word combines
different frames, or whether cached data is fresh.

Reset history is captured through an asynchronous-set flip-flop from the
existing SPI reset chain and system reset. It is then synchronized for the
status path. This allows capture while clocks are stopped. Short-pulse claims
are limited to events accepted by the physical reset circuitry; digital
simulation does not prove capture of arbitrarily short analog glitches.

A fresh rising edge of `clr_err` acknowledges history only after both the raw
and synchronized serializer-completion states are true. An early request is
rejected, not queued. Leaving `clr_err` high cannot erase a subsequent reset.
Reset assertion takes precedence. CRC and alignment counters retain the
previous level-clear behavior. Consequently, an acknowledgement sequence must
deliberately preserve other configuration bits and supply a new low-to-high
transition; it is not an automatic part of a diagnostic read.

Every SPI or system/word reset asynchronously invalidates acknowledgement
arming. After reset release, an actually received frame with `clr_err=0` must
arm a later high transition. The reset value of the local configuration register
does not count. This prevents both a high bit retained in Kasli's header and
a pending acknowledgement paused with the observation clock from erasing a
new reset event. These failures were reproduced in intermediate candidates;
the final regressions pass, and mutations that remove the protection restore
the failures.

The completion bit says only that the serializer's startup transfer and clear
guard finished. It does not promise analog settling, settled CIC state, release
of manual DAC clear, correct desired output values or absence of a later fault.

## Host visibility and remaining transport work

The pinned ARTIQ 8 `Fastino.read()` is unimplemented. Its Kasli serializer also
leaves return sampling alignment as a TODO and continuously refreshes a bank
of cached words. A successful RTIO read proves Kasli answered; without qualified
return mapping and latency, it does not establish the source or age of the
decoded state. There is no response transaction identifier. A stuck MISO input
may overwrite the cache with invalid constant bits; an indefinitely unchanged
old cache after a simple disconnection has not been demonstrated. Waiting one
whole cache-refresh period is not a substitute for transport qualification.

`artiq_tools/status_probe.py` is a bounded diagnostic reader. It does not
initialize the board, write DAC data, acknowledge faults or recover outputs.
Default operation retains raw cache words and RTIO request/response timestamps.
Optional decoding requires an explicitly qualified whole-word cache index and
an evidence note. A matching signature alone is not mapping qualification or
a freshness check. Exclusive access to the RTIO input channel is required.
There is no automatic ready-success or fault-interlock API in this package.

Complete host fault detection remains open until return-word mapping and
freshness are qualified. A future protocol could echo a challenge in the same
sample as the flags, but token reuse, writer ownership, restart behavior and
stale replies require an explicit contract. This revision does not introduce
such a protocol or modify Kasli firmware.

## DAC-model qualification

The [AD5542A Rev. C datasheet](https://www.analog.com/media/en/technical-documentation/data-sheets/AD5512A_5542A.pdf)
describes falling-edge clear and suppression of LDAC pulses while clear is
low on page 8; page 15 describes CS-rising updates with LDAC held low.
It does not explicitly resolve all simultaneous CS/CLR cases or clear-release
priority. The model's treatment of these combinations is an assumption to
qualify, not an independently established silicon guarantee.

No speculative CS/SDI gating correction is included. Aborting a transfer by
raising CS can itself latch a partial word. Settled-zero measurements do not
exclude a brief warm-reset excursion. An isolated, triggered pin/output
measurement or manufacturer clarification remains necessary for that claim.

Lattice's [iCE40 LP/HX datasheet, page 13](https://www.latticesemi.com/view_document?document_id=49312)
states that dynamic feedback phase adjustment may lose lock. That supports
the mechanism considered in the review; it is not a measured event rate for
this board.

## Reproduction

Select Python with Migen and MiSoC installed using `FASTINO_PYTHON` (default
`python3`). Put Yosys, nextpnr-ice40, icepack and Icarus on `PATH`, or prefix
their directory with `FASTINO_TOOLCHAIN_BIN`. `IVERILOG`, `VVP` and
`ICE40_CELLS_SIM` can be set explicitly. When omitted, the primitive model is
located relative to the resolved Yosys executable. Generated output directories
must be empty/new and outside this checkout. These scripts never program a board.

```bash
bash offline_tests/build_candidate.sh /tmp/fastino-review-build
bash offline_tests/run_checks.sh \
  --output /tmp/fastino-review-checks \
  --ram-image /tmp/fastino-review-build/build/fastino.txt
```

The build retains the inherited search through seeds 1–10 and stops on a timing
pass. Inspect its reported allowance, including the serial half-cycle path.
To retain an additional bounded routing attempt without repeating synthesis:

```bash
bash offline_tests/reroute_candidate.sh \
  /tmp/fastino-review-build /tmp/fastino-review-route-seed2 2
```

That command preserves its inputs and seed and checks the unchanged clock
constraints. Use the selected route's `build/fastino.txt` for image-matched
simulation. A route that merely passes is not necessarily an appropriate
replacement for the known working image.

For digital simulations without a routed image, the explicit
`--assume-zero-ram` option exercises the full functional suite under that stated
assumption. Without either RAM option, the runner prints `PARTIAL` and omits
active-RAM and actual-PHY tests. It never silently borrows another build's image.

The simulation dependency revisions are recorded in
`offline_tests/simulation_revisions.env`. `fetch_sim_dependencies.sh` downloads
those exact Migen/MiSoC sources and the Yosys primitive model into a supplied
new directory; set `PYTHONPATH` to its `migen` and `misoc` directories and
`ICE40_CELLS_SIM` to its `cells_sim.v`. The GitHub Actions workflow uses this
recipe with Python 3.12.7 and records the installed Icarus version. The OS
packages are not a fully pinned environment. It runs digital simulation with
an explicit zero-RAM assumption, not FPGA routing or physical qualification.

`artiq_tools/compile_status.py` runs seven host tests and compiles the reader
with the installed Python 3.11.10 / ARTIQ `8.0+6f600dd` package. Supply that
package directory with `--artiq-root` and a new `--output` directory. The
compiler fixture blocks network and core execution and uses a synthetic device
database. `check_return_path.py` runs with Migen/MiSoC; supply the pinned
installed `fastlink.py` with `--fastlink-source` and a new JSON `--output` file.
It verifies the source hash before replaying the actual Kasli serializer class.

## Validation results, 2026-10-28

The functional suite passes with seeded/unknown serial state, separate
unknown-RAM cold-idle cases, 18 ordinary-transfer reset phases and 19 integrated
interpolator warm-reset phases. Continuous modeled DAC checks are active during
clear. Actual-top tests cover running/stopped clocks, a short injected LOCK
pulse, acknowledgement races, deliberate SPI reset, word reset, retained/pending
acknowledgements and manual DAC clear. Negative controls detect broken clear,
missing history and the legacy interpolator enable mask. Independent review
also removes SPI history capture and each new acknowledgement protection to
verify the corresponding failures. The alternative CLR/CS model intentionally
fails; this exposes the silicon assumption rather than resolving it.

Actual-top simulation uses controlled PLL outputs and injected decoded frames.
It tests production clear/reset/status wiring but cannot establish physical
PLL acquisition, the complete EEM link or DAC analog behavior. The local CI
recipe passes with freshly downloaded pinned HDL/model sources. Hosted GitHub
Actions was not part of the offline validation completed on 2026-10-28.

Seven host tests and actual ARTIQ 8 compilation pass, including explicit return
of raw arrays/timestamps. The return-path replay passes eight imposed-delay
cases and independently calculated sample values. Its spliced/displaced words
demonstrate why mapping must be qualified; they are not a measured physical
latency for this board.

The final native-async-arm image passes routing at seed 1 with all 32 packed
4-kbit RAM initialization blocks checked zero. Constraints were unchanged.
The earlier candidates, including a passing route with only about 0.033 ns
serial allowance, were superseded and are not the final image.

| Path | Constraint | Final routed result | Approximate setup allowance |
| --- | --- | --- | --- |
| System, rising to rising | 28 ns | 83.25 MHz | 15.988 ns |
| SPI, rising to rising | 21 ns | 68.01 MHz | 6.296 ns |
| Serial limiting path, rising to rising | 4 ns | 286.12 MHz | 0.505 ns |
| sys to SPI | Less than 7 ns | 2.34 ns | 4.66 ns |

The serial limiting edge class changed from the preceding image's
falling-to-rising path. **0.505 ns is a full-cycle figure**, not a newly measured
half-cycle margin or a directly comparable improvement over the historical
0.404 ns half-cycle figure. The log does not separately report the minimum
half-cycle allowance. Values derive from rounded Fmax and edge classifications;
they are not external-pin timing or new hold-time signoff. Inherited Yosys
`translate_off` and IceStorm ICEGATE configuration warnings are retained in
the build evidence.

Final `fastino_phy.py` SHA-256:
`ef13e404dab63e3280354db0571bab7205a1526b14e7b934f6beacf60c45fef8`.
Installed `fastino.bin`, 135,100 bytes, SHA-256:
`0be9ff024e0f6061165b07247d71d3e99fd31cb512e66f8adcdd90643f90f9b4`.
The previous installed-image hash and its physical observations remain in
`STARTUP_ZERO.md`; they are separate from the following results.

## Installation and bench results, 2026-10-28 and 2026-10-29

The revised image was installed on the same Fastino PCB v1.2, EEM2, using
ARTIQ 8.0+6f600dd with eight-channel grouped writes. Before programming, two
independent full 1 MiB reads matched the known working startup-zero image.
After programming, a separate full-array read verified the new image and
preservation of every byte beyond it. FPGA reload completed with CDONE high.
No EEPROM or Kasli firmware change was made. Original pre-modification and
previous working-image backups remain in the laboratory archive.

| Check on the revised image | Operator observation |
| --- | --- |
| CH0 after FPGA reload | 0 V, before the requested cold-start check |
| All 32 channels after cold start | All channels settled at 0 V |
| CH0 R1 | Approximately 1 V, approximately 20 us pulse, return to 0 V |
| CH0 R16 | Approximately 1 V, rounded rising/falling edges, return to 0 V |
| CH0 R64 | Approximately 1 V, rounded edges visibly slower than R16, return to 0 V |

Each command block scheduled 100 nominal 0-to-1-to-0 V pulses over 100.352 ms.
Command holds were 20.384 us, 50.176 us and 200.704 us for R1/R16/R64.
All three runs exited successfully, completed explicit all-channel zero
restoration and unity CIC, and left noncontinuous/held mode with TTL4 low.
The controller log contained no runtime errors. Native ARTIQ results, exact
arguments, source identity, logs and operator replies remain in the local
bench archive; they are not bundled into the public source repository.

The oscilloscope was manually operated. Suggested timebases were 5, 10 and
50 us/div, with DC/high-impedance inputs, CH0 displayed at 500 mV/div and a
single rising-edge trigger at 0.5 V. Actual settings and raw waveforms were
not supplied for these runs. The observed approximately 20 us R1 pulse and
qualitative filtered shapes do not establish calibrated timing distributions
or 100 independently captured waveforms. No revised-image startup transient
waveform was supplied; the earlier approximately 200 ms, below-1 V recording
belongs to the preceding image.

These checks confirm settled cold-start zero on all channels and basic CH0
command/CIC behavior. Physical status-return mapping/freshness, warm-reset
CLR/CS priority and transient behavior, PLL loss frequency and hours-long
soak remain unqualified. No command-controlled 392 ns frame alignment was
implemented or tested in this package. The series stopped at R64.

The laboratory correction archive retains the full source, tracked-file diff,
dependency identities, generated RTL, simulations, negative controls, compiler
ELF, selected build, superseded attempts and independent review. The published
source preserves the reviewed executable files; later documentation records
installation and bench observations. The selected image has not been independently
rebuilt bit-for-bit; routed-image inspection and source-matched simulation are
the build-reproducibility evidence obtained for this revision.

Further hardware verification, hours-long soak or deployment to another board
requires its own concrete review. Preserve both the original board image and the
known working startup-zero image. Flash readback resets/reloads Fastino and
must be treated as output-affecting maintenance.
