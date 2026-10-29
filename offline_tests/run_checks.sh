#!/usr/bin/env bash
set -euo pipefail
test_root=$(cd "$(dirname "$0")" && pwd)
candidate_root=$(cd "$test_root/.." && pwd)
source "$test_root/tool_env.sh"
test_output= ram_image= assume_zero=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --output) test_output=$2; shift 2 ;;
        --ram-image) ram_image=$2; shift 2 ;;
        --assume-zero-ram) assume_zero=1; shift ;;
        *) printf 'Usage: run_checks.sh [--output DIR] [--ram-image ASC | --assume-zero-ram]\n' >&2; exit 2 ;;
    esac
done
if [ -n "$ram_image" ] && [ "$assume_zero" = 1 ]; then
    printf 'Choose image-verified or explicitly assumed RAM initialization, not both\n' >&2; exit 2
fi
test_output=${test_output:-$(mktemp -d "${TMPDIR:-/tmp}/fastino-startup-tests-XXXXXX")}
test_output=$(prepare_output "$test_output" "$candidate_root")
resolve_cells_sim
"$FASTINO_PYTHON" -B "$test_root/test_timing.py"
"$FASTINO_PYTHON" -B "$test_root/generate_rtl.py" "$test_output"
sha256sum "$candidate_root/"*.py "$test_root/"*.py "$test_root/"*.sv "$test_root/"*.sh "$ICE40_CELLS_SIM" > "$test_output/source-sha256.txt"
"$IVERILOG" -V > "$test_output/iverilog-version.txt" 2>&1
ram_args=()
if [ -n "$ram_image" ]; then
    "$FASTINO_PYTHON" -B "$test_root/check_ram_init.py" "$ram_image" > "$test_output/ram-initialization.json"
    ram_args=(+fpga_ram_init_zero)
elif [ "$assume_zero" = 1 ]; then
    printf '{"value":"zero","basis":"explicit functional-model assumption; no packed image checked"}\n' > "$test_output/ram-initialization.json"
    ram_args=(+fpga_ram_init_zero)
fi
"$IVERILOG" -g2012 -s tb -o "$test_output/pins.vvp" "$test_output/candidate.v" "$test_output/baseline.v" "$test_output/integrated.v" "$ICE40_CELLS_SIM" "$test_root/ad5542a_model.sv" "$test_root/tb.sv"
for seed in 1 7 83; do
    "$VVP" "$test_output/pins.vvp" +seed="$seed" "${ram_args[@]}" | tee "$test_output/seed-$seed.log"
done
"$VVP" "$test_output/pins.vvp" +unknown_serial "${ram_args[@]}" | tee "$test_output/unknown-serial.log"
"$VVP" "$test_output/pins.vvp" +unknown_serial | tee "$test_output/unknown-ram-cold-idle.log"
if "$VVP" "$test_output/pins.vvp" +cs_updates_under_clear "${ram_args[@]}" > "$test_output/alternate-clear-model.log" 2>&1; then
    printf 'Competing CLR/CS model unexpectedly passed; reassess assumption test\n' >&2; exit 1
fi
grep -q 'partial/nonzero escaped CLR' "$test_output/alternate-clear-model.log"
printf 'PASS alternate CLR/CS interpretation exposes the unresolved model dependency\n'
if [ "${#ram_args[@]}" -gt 0 ]; then
    "$IVERILOG" -g2012 -DLEGACY_INTERPOLATOR -s tb -o "$test_output/legacy.vvp" "$test_output/candidate.v" "$test_output/baseline.v" "$test_output/legacy_integrated.v" "$ICE40_CELLS_SIM" "$test_root/ad5542a_model.sv" "$test_root/tb.sv"
    if "$VVP" "$test_output/legacy.vvp" +fpga_ram_init_zero > "$test_output/legacy-expected-failure.log" 2>&1; then
        printf 'Legacy enable-mask regression unexpectedly passed\n' >&2; exit 1
    fi
    grep -q 'stale interpolator mask after reset' "$test_output/legacy-expected-failure.log"
    printf 'PASS legacy reset-less enable mask fails the regression as expected\n'
    "$FASTINO_PYTHON" -B "$test_root/generate_phy_rtl.py" "$test_output"
    "$FASTINO_PYTHON" -B "$test_root/check_phy.py" "$test_output" "$ICE40_CELLS_SIM" "$IVERILOG" "$VVP" | tee "$test_output/phy-tests.log"
else
    printf 'PARTIAL: active-RAM and actual-PHY tests require --ram-image or --assume-zero-ram\n'
fi
printf 'Evidence directory: %s\n' "$test_output"
