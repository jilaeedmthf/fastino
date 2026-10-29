#!/usr/bin/env bash
# Shared tool selection only; callers decide which tests/builds to execute.
if [ -n "${FASTINO_TOOLCHAIN_BIN:-}" ]; then
    export PATH="$FASTINO_TOOLCHAIN_BIN:$PATH"
fi
export PYTHONDONTWRITEBYTECODE=1
: "${FASTINO_PYTHON:=python3}"
: "${IVERILOG:=iverilog}"
: "${VVP:=vvp}"

resolve_cells_sim() {
    if [ -z "${ICE40_CELLS_SIM:-}" ]; then
        ICE40_CELLS_SIM=$("$FASTINO_PYTHON" -B - <<'PY'
from pathlib import Path
import shutil
binary = shutil.which('yosys')
if binary is None:
    raise SystemExit('Set ICE40_CELLS_SIM or put yosys on PATH')
path = Path(binary).resolve().parent.parent / 'share/yosys/ice40/cells_sim.v'
if not path.is_file():
    raise SystemExit('Set ICE40_CELLS_SIM to the Yosys iCE40 cells_sim.v')
print(path)
PY
        )
    fi
    test -r "$ICE40_CELLS_SIM"
}

prepare_output() {
    "$FASTINO_PYTHON" -B - "$1" "$2" <<'PY'
from pathlib import Path
import sys
output, source = (Path(p).resolve() for p in sys.argv[1:])
if output == source or source in output.parents:
    raise SystemExit('Generated output must be outside the source checkout')
output.mkdir(parents=True, exist_ok=True)
if any(output.iterdir()):
    raise SystemExit('Choose a new or empty output directory')
print(output)
PY
}
