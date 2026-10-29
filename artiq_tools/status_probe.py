"""Diagnostic ARTIQ 8 cache reads; not a freshness-qualified fault interlock.

The installed Fastino.read() is unimplemented. This probe issues only RTIO
read requests and reports the 16 cached words with request/response timestamps.
It never calls init/reset, acknowledges faults, or writes DAC/configuration data.
An RTIO response proves Kasli answered, not that its EEM cache is fresh.
"""

import json
import time

from artiq.experiment import (BooleanValue, EnumerationValue, EnvExperiment,
                              NumberValue, StringValue, kernel, now_mu)
from artiq.coredevice.rtio import rtio_input_timestamped_data, rtio_output
from numpy import int64


DIAGNOSTIC_SIGNATURE = 0xA51
STATUS_WORDS = 16


def decode_diagnostic_word(value):
    """Decode one already-qualified, whole-word diagnostic response.

    A matching signature is necessary, but is not a transport qualification.
    No automatic bit rotation, cache-address search, or freshness inference.
    """
    if not isinstance(value, int) or not 0 <= value < (1 << 14):
        raise ValueError("Expected an unsigned 14-bit cache word")
    if value >> 2 != DIAGNOSTIC_SIGNATURE:
        raise ValueError("Diagnostic signature mismatch; transport is unqualified")
    return {"serializer_ready": bool(value & 1),
            "reset_history": bool(value & 2),
            "signature": DIAGNOSTIC_SIGNATURE,
            "return_link_freshness_verified": False}


class FastinoStatusProbe(EnvExperiment):
    """Fastino raw status cache probe (read requests only)."""

    def build(self):
        names = sorted(name for name, entry in self.get_device_db().items()
                       if isinstance(entry, dict)
                       and entry.get("module") == "artiq.coredevice.fastino"
                       and entry.get("class") == "Fastino")
        if not names:
            raise ValueError("Device database contains no native Fastino device")
        self.setattr_argument("fastino_name", EnumerationValue(names, default=names[0]))
        self.setattr_device("core")
        self.fastino = self.get_device(self.fastino_name)
        self.setattr_argument("armed", BooleanValue(False))
        self.setattr_argument("exclusive_reader_confirmed", BooleanValue(False))
        self.setattr_argument("capture_count", NumberValue(1, min=1, max=1000,
                                                          step=1, ndecimals=0))
        self.setattr_argument("interval_ms", NumberValue(10, min=1, max=1000))
        self.setattr_argument("response_timeout_ms", NumberValue(1, min=0.1, max=10))
        self.setattr_argument("qualified_cache_index", NumberValue(-1, min=-1,
                                                                  max=15, step=1,
                                                                  ndecimals=0))
        self.setattr_argument("mapping_evidence", StringValue(""))

    def prepare(self):
        if not self.armed:
            raise ValueError("Probe is disarmed; review its exact execution first")
        if not self.exclusive_reader_confirmed:
            raise ValueError("Require exclusive RTIO input/read-request ownership")
        if self.core.ref_period != 1e-9:
            raise ValueError("This ARTIQ 8 probe requires the recorded 1 ns RTIO unit")
        if self.fastino.core is not self.core:
            raise ValueError("Fastino and experiment must use the same core")
        self.count = int(self.capture_count)
        self.cache_index = int(self.qualified_cache_index)
        if self.count != self.capture_count or not 1 <= self.count <= 1000:
            raise ValueError("capture_count must be an integer in 1..1000")
        if self.cache_index != self.qualified_cache_index or not -1 <= self.cache_index <= 15:
            raise ValueError("qualified_cache_index must be -1 or an integer in 0..15")
        if self.cache_index >= 0 and not self.mapping_evidence.strip():
            raise ValueError("Decoded mode requires current whole-word mapping evidence")
        if not 0.1 <= self.response_timeout_ms <= 10:
            raise ValueError("response timeout outside 0.1..10 ms")
        if not 1 <= self.interval_ms <= 1000:
            raise ValueError("poll timing outside declared limits")
        self.response_timeout_mu = int64(round(self.response_timeout_ms * 1_000_000))
        self.target = self.fastino.channel
        self.rtio_channel = self.target >> 8
        self.values = [0] * STATUS_WORDS
        self.request_times = [int64(0)] * STATUS_WORDS
        self.response_times = [int64(0)] * STATUS_WORDS

    @kernel
    def _capture_kernel(self):
        discarded = 0
        for index in range(16):
            self.core.break_realtime()
            requested = now_mu()
            deadline = requested + self.response_timeout_mu
            self.request_times[index] = requested
            rtio_output(self.target | 0x80 | index, 0)
            found = False
            for attempt in range(17):
                timestamp, value = rtio_input_timestamped_data(deadline, self.rtio_channel)
                if timestamp < 0:
                    raise ValueError("Fastino cache read response timeout")
                if timestamp < requested:
                    discarded += 1
                else:
                    if timestamp > deadline or value < 0 or value >= 16384:
                        raise ValueError("Invalid Fastino cache read response")
                    self.values[index] = value
                    self.response_times[index] = timestamp
                    found = True
                    break
            if not found:
                raise ValueError("Too many stale RTIO responses; require exclusive access")
        # Explicit return transport is required; do not rely on implicit
        # writeback of these mutated arrays to the host object.
        return self.values, self.request_times, self.response_times, discarded

    def run(self):
        for sample in range(self.count):
            values, request_times, response_times, discarded = self._capture_kernel()
            record = {"sample": sample, "device": self.fastino_name,
                      "raw_cache_words": [int(v) for v in values],
                      "request_mu": [int(v) for v in request_times],
                      "response_mu": [int(v) for v in response_times],
                      "discarded_old_rtio_responses": int(discarded),
                      "cache_is_atomic_snapshot": False,
                      "return_link_freshness_verified": False}
            if self.cache_index >= 0:
                decoded = decode_diagnostic_word(int(values[self.cache_index]))
                record["diagnostic"] = decoded
                record["qualified_cache_index"] = self.cache_index
                record["mapping_evidence"] = self.mapping_evidence
            print(json.dumps(record, sort_keys=True), flush=True)
            if sample + 1 < self.count:
                time.sleep(self.interval_ms / 1000)
