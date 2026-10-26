#!/usr/bin/env bash
set -euo pipefail
export PATH=/tmp/fastino-fpga-tools/bin:$PATH
export PYTHONPATH=/nix/store/4ssk8p1fsck5p1wd302sgls2zzyz6wrs-python3.12-migen/lib/python3.12/site-packages:/nix/store/aw9q0km75lcv1la9c6biw8xzvkxjba03-python3.12-misoc/lib/python3.12/site-packages
export PYTHONDONTWRITEBYTECODE=1
candidate_root=$(cd "$(dirname "$0")/.." && pwd)
candidate_output=$(mktemp -d /tmp/fastino-startup-build-XXXXXX)
printf '%s\n' "$candidate_output" > "$candidate_root/offline_tests/latest_build.txt"
git -C "$candidate_root" rev-parse HEAD > "$candidate_output/base_commit.txt"
git -C "$candidate_root" diff -- multispi.py fastino_phy.py interpolator.py > "$candidate_output/candidate.patch"
sha256sum "$candidate_root"/*.py > "$candidate_output/source-sha256.txt"
yosys -V > "$candidate_output/tool-versions.txt"
nextpnr-ice40 --version >> "$candidate_output/tool-versions.txt" 2>&1
icepack -h >> "$candidate_output/tool-versions.txt" 2>&1 || true
cd "$candidate_output"
/nix/store/80v02bzfz0g507q8b1g9ylmygc572hzd-python3-3.12.7/bin/python3.12 -B "$candidate_root/fastino_phy.py" > build.log 2>&1
/nix/store/80v02bzfz0g507q8b1g9ylmygc572hzd-python3-3.12.7/bin/python3.12 -B "$candidate_root/offline_tests/check_timing.py" build.log > timing-check.json
sha256sum build/fastino.bin build/fastino.json build/fastino.txt > image-sha256.txt
printf 'Candidate build directory: %s\n' "$candidate_output"
