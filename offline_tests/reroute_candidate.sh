#!/usr/bin/env bash
# Reuse one synthesis; retain each bounded routing attempt in its own directory.
set -euo pipefail
test_root=$(cd "$(dirname "$0")" && pwd)
candidate_root=$(cd "$test_root/.." && pwd)
source "$test_root/tool_env.sh"
if [ "$#" -ne 3 ] || ! [[ "$3" =~ ^([1-9]|10)$ ]]; then
    printf 'Usage: bash offline_tests/reroute_candidate.sh EXISTING_BUILD OUTPUT_DIRECTORY SEED_1_TO_10\n' >&2
    exit 2
fi
input_root=$(cd "$1" && pwd)
route_output=$(prepare_output "$2" "$candidate_root")
route_seed=$3
mkdir "$route_output/build"
cp "$input_root/build/fastino.json" "$input_root/build/fastino.pcf" \
    "$input_root/build/fastino_pre_pack.py" "$route_output/build/"
cp "$input_root/base_commit.txt" "$input_root/candidate.patch" \
    "$input_root/source-sha256.txt" "$route_output/"
sha256sum "$input_root/build/fastino.json" "$input_root/build/fastino.pcf" \
    "$input_root/build/fastino_pre_pack.py" > "$route_output/routing-input-sha256.txt"
nextpnr-ice40 --version > "$route_output/route-tool-versions.txt" 2>&1
icepack -h >> "$route_output/route-tool-versions.txt" 2>&1 || true
printf '%s\n' "$route_seed" > "$route_output/route-seed.txt"
cd "$route_output/build"
printf 'Seed %s\n' "$route_seed" > ../build.log
nextpnr-ice40 --hx8k --package ct256 --pcf fastino.pcf --json fastino.json \
    --asc fastino.txt --pre-pack fastino_pre_pack.py --seed "$route_seed" >> ../build.log 2>&1
"$FASTINO_PYTHON" -B "$test_root/check_timing.py" ../build.log > ../timing-check.json
icepack fastino.txt fastino.bin >> ../build.log 2>&1
cd "$route_output"
sha256sum build/fastino.bin build/fastino.json build/fastino.txt > image-sha256.txt
printf 'Routed candidate directory: %s\n' "$route_output"
