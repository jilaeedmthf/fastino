#!/usr/bin/env bash
set -euo pipefail
test_root=$(cd "$(dirname "$0")" && pwd)
candidate_root=$(cd "$test_root/.." && pwd)
source "$test_root/tool_env.sh"
if [ "$#" -gt 1 ]; then
    printf 'Usage: bash offline_tests/build_candidate.sh [OUTPUT_DIRECTORY]\n' >&2
    exit 2
fi
candidate_output=${1:-$(mktemp -d "${TMPDIR:-/tmp}/fastino-startup-build-XXXXXX")}
candidate_output=$(prepare_output "$candidate_output" "$candidate_root")
git -C "$candidate_root" rev-parse HEAD > "$candidate_output/base_commit.txt"
git -C "$candidate_root" diff -- '*.py' > "$candidate_output/candidate.patch"
sha256sum "$candidate_root"/*.py "$test_root"/*.py "$test_root"/*.sh > "$candidate_output/source-sha256.txt"
yosys -V > "$candidate_output/tool-versions.txt"
nextpnr-ice40 --version >> "$candidate_output/tool-versions.txt" 2>&1
icepack -h >> "$candidate_output/tool-versions.txt" 2>&1 || true
"$FASTINO_PYTHON" -B -c 'import sys,migen,misoc; print(sys.version); print(migen.__file__); print(misoc.__file__)' >> "$candidate_output/tool-versions.txt"
cd "$candidate_output"
"$FASTINO_PYTHON" -B "$candidate_root/fastino_phy.py" > build.log 2>&1
"$FASTINO_PYTHON" -B "$test_root/check_timing.py" build.log > timing-check.json
sha256sum build/fastino.bin build/fastino.json build/fastino.txt > image-sha256.txt
printf 'Candidate build directory: %s\n' "$candidate_output"
