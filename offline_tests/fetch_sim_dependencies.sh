#!/usr/bin/env bash
# Explicit network step for the simulation job; it does not install packages.
set -euo pipefail
test_root=$(cd "$(dirname "$0")" && pwd)
candidate_root=$(cd "$test_root/.." && pwd)
source "$test_root/tool_env.sh"
source "$test_root/simulation_revisions.env"
if [ "$#" -ne 1 ]; then
    printf 'Usage: bash offline_tests/fetch_sim_dependencies.sh NEW_OUTPUT_DIRECTORY\n' >&2
    exit 2
fi
dependency_output=$(prepare_output "$1" "$candidate_root")
cp "$test_root/simulation_revisions.env" "$dependency_output/"
curl --fail --silent --show-error --location \
    "https://codeload.github.com/m-labs/migen/tar.gz/$MIGEN_REVISION" -o "$dependency_output/migen.tar.gz"
curl --fail --silent --show-error --location \
    "https://codeload.github.com/m-labs/misoc/tar.gz/$MISOC_REVISION" -o "$dependency_output/misoc.tar.gz"
curl --fail --silent --show-error --location \
    "https://raw.githubusercontent.com/YosysHQ/yosys/$YOSYS_REVISION/techlibs/ice40/cells_sim.v" -o "$dependency_output/cells_sim.v"
mkdir "$dependency_output/migen" "$dependency_output/misoc"
tar -xzf "$dependency_output/migen.tar.gz" --strip-components=1 -C "$dependency_output/migen"
tar -xzf "$dependency_output/misoc.tar.gz" --strip-components=1 -C "$dependency_output/misoc"
cd "$dependency_output"
sha256sum migen.tar.gz misoc.tar.gz cells_sim.v > downloads-sha256.txt
printf 'Simulation sources: %s\n' "$dependency_output"
