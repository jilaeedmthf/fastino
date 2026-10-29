"""Run host checks and compile the diagnostic kernel without device access.

Invoke with the pinned Python 3.11.10 interpreter and --artiq-root pointing at
the ARTIQ 8.0+6f600dd Nix package. The source tree and installed package are read
only. --output names a new directory for ELF and evidence.
"""

import argparse
import ast
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import unittest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--artiq-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.version_info[:3] != (3, 11, 10) or not sys.dont_write_bytecode:
        raise RuntimeError("Use the pinned Python 3.11.10 with -B")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    paths = []
    wrapped = args.artiq_root / "bin/.artiq_compile-wrapped"
    for node in ast.walk(ast.parse(wrapped.read_text())):
        if isinstance(node, ast.List):
            try:
                value = ast.literal_eval(node)
            except (ValueError, TypeError):
                continue
            if value and all(isinstance(v, str) and v.startswith("/nix/store/")
                             and v.endswith("/site-packages") for v in value):
                paths.extend(value)
    expected_path = str(args.artiq_root / "lib/python3.11/site-packages")
    if expected_path not in paths:
        raise RuntimeError("Unexpected pinned ARTIQ wrapper")
    sys.path[:0] = paths
    bins = re.findall(r"^PATH='(/nix/store/[^']+/bin)'\$PATH$",
                      (args.artiq_root / "bin/artiq_compile").read_text(), re.MULTILINE)
    if not bins:
        raise RuntimeError("Missing compiler tool PATH")
    os.environ["PATH"] = os.pathsep.join(list(reversed(bins)) + [os.environ.get("PATH", "")])
    os.environ["TMPDIR"] = str(output)
    tempfile.tempdir = str(output)
    for key in tuple(os.environ):
        if key.startswith("ARTIQ_DUMP_"):
            del os.environ[key]
    network_attempts = []
    def audit(event, arguments):
        if event.startswith("socket."):
            network_attempts.append(event)
            raise AssertionError("Network forbidden during offline compilation")
    sys.addaudithook(audit)

    import artiq
    from artiq.coredevice.core import Core
    from artiq.coredevice.fastino import Fastino
    from artiq.language.core import rpc
    from artiq.language.environment import ProcessArgumentManager
    if artiq.__version__ != "8.0+6f600dd":
        raise RuntimeError("Unexpected ARTIQ version")
    def forbidden(*args, **kwargs):
        raise AssertionError("Core execution forbidden")
    Core.run = forbidden
    Core._run_compiled = forbidden

    source_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(source_dir))
    import status_probe
    import test_status_probe
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_status_probe)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():
        raise AssertionError("Host checks failed")

    db = {"core": {"type": "local", "module": "artiq.coredevice.core", "class": "Core",
                   "arguments": {"host": None, "ref_period": 1e-9, "ref_multiplier": 8,
                                 "target": "cortexa9"}},
          "fixture_dac": {"type": "local", "module": "artiq.coredevice.fastino", "class": "Fastino",
                          "arguments": {"channel": 3, "log2_width": 3}}}
    class Devices:
        def __init__(self):
            self.devices = {}
        def get_device_db(self):
            return db
        def get(self, name):
            if name not in self.devices:
                cls = Core if name == "core" else Fastino
                self.devices[name] = cls(self, **db[name]["arguments"])
            return self.devices[name]
    class NoDatasets:
        def __getattr__(self, name):
            raise AssertionError("Dataset access forbidden: " + name)
    @rpc(flags={"async"})
    def result_callback(value):
        raise AssertionError("Result callback must not execute offline")

    devices = Devices()
    manager = ProcessArgumentManager({"armed": True, "exclusive_reader_confirmed": True})
    experiment = status_probe.FastinoStatusProbe((devices, NoDatasets(), manager, {}))
    manager.check_unprocessed_arguments()
    experiment.prepare()
    assert experiment.core.comm.__class__.__name__ == "CommKernelDummy"
    embedding, elf, _, _, subkernels = experiment.core.compile(
        type(experiment)._capture_kernel, [experiment], {}, set_result=result_callback)
    assert not subkernels
    (output / "status_capture.elf").write_bytes(elf)
    report = {"python": sys.version, "artiq": artiq.__version__,
              "host_tests": result.testsRun, "host_passed": True,
              "elf_bytes": len(elf), "elf_sha256": hashlib.sha256(elf).hexdigest(),
              "source_sha256": hashlib.sha256((source_dir / "status_probe.py").read_bytes()).hexdigest(),
              "compiled_kernel": "FastinoStatusProbe._capture_kernel",
              "explicit_return": "values:int32[16], requests:int64[16], responses:int64[16], discarded:int32",
              "has_rpc": embedding.has_rpc(), "synthetic_ddb": True,
              "device_names_derived_from_ddb": True, "network_attempts": network_attempts,
              "core_execution": False, "datasets_accessed": False,
              "physical_readback_qualified": False}
    (output / "compile-results.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
