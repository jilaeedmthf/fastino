#!/usr/bin/env bash
set -euo pipefail
export PATH=/tmp/fastino-fpga-tools/bin:$PATH
export PYTHONPATH=/nix/store/4ssk8p1fsck5p1wd302sgls2zzyz6wrs-python3.12-migen/lib/python3.12/site-packages:/nix/store/aw9q0km75lcv1la9c6biw8xzvkxjba03-python3.12-misoc/lib/python3.12/site-packages
export PYTHONDONTWRITEBYTECODE=1
test_root=$(cd "$(dirname "$0")" && pwd)
test_output=$(mktemp -d /tmp/fastino-startup-tests-XXXXXX)
printf '%s\n' "$test_output" > "$test_root/latest_output.txt"
/nix/store/80v02bzfz0g507q8b1g9ylmygc572hzd-python3-3.12.7/bin/python3.12 -B "$test_root/generate_rtl.py" "$test_output"
ram_image=$(cat "$test_root/latest_build.txt")/build/fastino.txt
/nix/store/80v02bzfz0g507q8b1g9ylmygc572hzd-python3-3.12.7/bin/python3.12 -B "$test_root/check_ram_init.py" "$ram_image" > "$test_output/ram-initialization.json"
sha256sum "$test_root/../"*.py "$test_root/"*.py "$test_root/"*.sv "$test_root/"*.sh /tmp/fastino-fpga-tools/share/yosys/ice40/cells_sim.v > "$test_output/source-sha256.txt"
iverilog -V > "$test_output/iverilog-version.txt" 2>&1
iverilog -g2012 -s tb -o "$test_output/pins.vvp" "$test_output/candidate.v" "$test_output/baseline.v" "$test_output/integrated.v" /tmp/fastino-fpga-tools/share/yosys/ice40/cells_sim.v "$test_root/ad5542a_model.sv" "$test_root/tb.sv"
for seed in 1 7 83; do
    if [ "$seed" = 1 ]; then
        vvp "$test_output/pins.vvp" +seed="$seed" +fpga_ram_init_zero +vcd="$test_output/startup-simulation.vcd" | tee "$test_output/seed-$seed.log"
    else
        vvp "$test_output/pins.vvp" +seed="$seed" +fpga_ram_init_zero | tee "$test_output/seed-$seed.log"
    fi
done
vvp "$test_output/pins.vvp" +unknown_serial +fpga_ram_init_zero | tee "$test_output/unknown-serial.log"
vvp "$test_output/pins.vvp" +unknown_serial | tee "$test_output/unknown-ram-cold-idle.log"
iverilog -g2012 -DLEGACY_INTERPOLATOR -s tb -o "$test_output/legacy.vvp" "$test_output/candidate.v" "$test_output/baseline.v" "$test_output/legacy_integrated.v" /tmp/fastino-fpga-tools/share/yosys/ice40/cells_sim.v "$test_root/ad5542a_model.sv" "$test_root/tb.sv"
if vvp "$test_output/legacy.vvp" +fpga_ram_init_zero > "$test_output/legacy-expected-failure.log" 2>&1; then
    printf 'Legacy enable-mask regression unexpectedly passed\n' >&2
    exit 1
fi
grep -q 'stale interpolator mask after reset' "$test_output/legacy-expected-failure.log"
printf 'PASS legacy reset-less enable mask fails the regression as expected\n'
printf 'Evidence directory: %s\n' "$test_output"
