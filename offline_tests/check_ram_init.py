"""Confirm the simulated RAM initialization equals the actual routed image."""
import hashlib
import json
from pathlib import Path
import sys

path = Path(sys.argv[1])
data = path.read_bytes()
blocks = 0
remaining = 0
rows = []
for line in data.decode().splitlines():
    if line.startswith(".ram_data "):
        if remaining:
            raise ValueError("Truncated RAM block")
        remaining = 16
        blocks += 1
    elif remaining:
        if len(line) != 64 or any(char != "0" for char in line):
            raise ValueError("RAM initialization differs from all-zero simulation variant")
        rows.append(line)
        remaining -= 1
if remaining or blocks != 32 or len(rows) != 512:
    raise ValueError("Expected32 complete RAM initialization blocks")
print(json.dumps({"asc": str(path), "asc_sha256": hashlib.sha256(data).hexdigest(),
                  "ram_blocks": blocks, "initialized_bits": len(rows)*256,
                  "value": "all zero", "serial_register_initialization": "unchanged random/unknown"}, indent=2))
