"""Host checks for diagnostic decoding and exact read-only request behavior."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import status_probe as probe


class StatusProbeTests(unittest.TestCase):
    def test_diagnostic_states(self):
        for flags in range(4):
            result = probe.decode_diagnostic_word((0xA51 << 2) | flags)
            self.assertEqual(result["serializer_ready"], bool(flags & 1))
            self.assertEqual(result["reset_history"], bool(flags & 2))
            self.assertFalse(result["return_link_freshness_verified"])

    def test_bad_signature_and_range_rejected(self):
        for value in (-1, 1 << 14, 0, 0x3FFF, "10565"):
            with self.assertRaises(ValueError):
                probe.decode_diagnostic_word(value)

    def run_capture(self, responses):
        requested = []
        clock = [0]
        state = SimpleNamespace(
            target=0x1200, rtio_channel=0x12, response_timeout_mu=1_000_000,
            values=[0] * 16, request_times=[0] * 16, response_times=[0] * 16)
        state.core = SimpleNamespace(break_realtime=lambda: clock.__setitem__(0, clock[0] + 125000))
        def output(target, value):
            requested.append((target, value))
        def input_data(deadline, channel):
            self.assertEqual(channel, 0x12)
            self.assertEqual(deadline, clock[0] + 1_000_000)
            return responses(clock[0], len(requested) - 1)
        with patch.object(probe, "now_mu", lambda: clock[0]), \
             patch.object(probe, "rtio_output", output), \
             patch.object(probe, "rtio_input_timestamped_data", input_data):
            result = probe.FastinoStatusProbe._capture_kernel.artiq_embedded.function(state)
        self.assertEqual(result[:3], (state.values, state.request_times, state.response_times))
        return state, requested, result[3]

    def test_only_read_addresses_and_return_timestamps(self):
        state, requests, discarded = self.run_capture(lambda now, i: (now + 8, i))
        self.assertEqual(requests, [(0x1280 | i, 0) for i in range(16)])
        self.assertEqual(state.values, list(range(16)))
        self.assertEqual(discarded, 0)
        self.assertTrue(all(b - a == 8 for a, b in zip(state.request_times, state.response_times)))

    def test_old_fifo_events_are_not_mislabelled(self):
        calls = [0]
        def response(now, i):
            calls[0] += 1
            return (now - 8, 123) if calls[0] == 1 else (now + 8, i)
        state, _, discarded = self.run_capture(response)
        self.assertEqual(discarded, 1)
        self.assertEqual(state.values, list(range(16)))

    def test_missing_input_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "timeout"):
            self.run_capture(lambda now, i: (-1, 0))

    def test_bad_input_is_rejected(self):
        for data in (-1, 16384):
            with self.assertRaisesRegex(ValueError, "Invalid"):
                self.run_capture(lambda now, i: (now + 8, data))

    def test_stale_fifo_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "Too many stale"):
            self.run_capture(lambda now, i: (now - 8, 0))


if __name__ == "__main__":
    unittest.main()
