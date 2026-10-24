# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - Per-board traceability tests
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The trace of a board, the samples a data lake takes, the sink (against a real local HTTP server) and the bridge."""

import json
import math
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, job_to_dict
from hydra_umc_bridge_openpnp import BoardIdentity, BoardTraceRecorder, DatalakeSink, OpenPnpMqttBridge, datalake_samples
from hydra_umc_bridge_openpnp.handoff import SimulatedBoardHandoff
from hydra_umc_bridge_openpnp.mqtt_transport import TOPIC_PREFIX
from hydra_umc_bridge_openpnp.traceability import BATCH_SAMPLES, EVENT_TOPIC, MAX_OPEN_TRACES

IDENTITY = BoardIdentity("PCB-001", "RECIPE-A", "B", "LOT-7")
OK = SimulatedBoardHandoff(True, "robot-loads-board-into-pnp-fixture", "cell and external machine are ready", "f" * 64)
REFUSED = SimulatedBoardHandoff(False, "robot-loads-board-into-pnp-fixture", "external machine is RUNNING, not IDLE", None)


class Clock:
    def __init__(self, start=1_800_000_000.0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += seconds


def full_cycle(recorder, clock, identity=IDENTITY, last=JobPhase.COMPLETE):
    events = []
    for phase in (JobPhase.PREPARE, JobPhase.LOAD, JobPhase.PROCESS, JobPhase.UNLOAD, last):
        clock.advance(10)
        events += recorder.on_handoff(phase, OK, identity)
    return events


class RecorderTests(unittest.TestCase):
    def test_a_completed_board_gives_one_event_with_its_steps_and_cycle_time(self):
        clock = Clock()
        recorder = BoardTraceRecorder(clock=clock)
        events = full_cycle(recorder, clock)
        self.assertEqual(len(events), 1)
        event = events[0]
        self.assertEqual((event.topic, event.retain, event.qos), (EVENT_TOPIC, False, 1))
        trace = json.loads(event.payload)
        self.assertEqual(trace["outcome"], "completed")
        self.assertTrue(trace["good"])
        self.assertEqual([step["phase"] for step in trace["steps"]], ["PREPARE", "LOAD", "PROCESS", "UNLOAD", "COMPLETE"])
        self.assertEqual(trace["cycle_time_s"], 40.0)
        self.assertEqual(trace["fingerprint"], IDENTITY.fingerprint())
        self.assertEqual(recorder.open_boards, 0)

    def test_the_identifiers_never_leave_by_default(self):
        recorder = BoardTraceRecorder(clock=Clock())
        events = full_cycle(recorder, Clock())
        text = events[0].payload
        for identifier in ("PCB-001", "RECIPE-A", "LOT-7"):
            self.assertNotIn(identifier, text)
        self.assertNotIn("identity", json.loads(text))

    def test_the_identifiers_can_be_included_when_a_plant_allows_it(self):
        clock = Clock()
        events = full_cycle(BoardTraceRecorder(include_identifiers=True, clock=clock), clock)
        self.assertEqual(json.loads(events[0].payload)["identity"], {"board_id": "PCB-001", "recipe_id": "RECIPE-A", "revision": "B", "lot_id": "LOT-7"})

    def test_an_abort_closes_the_trace_as_aborted_and_not_good(self):
        clock = Clock()
        recorder = BoardTraceRecorder(clock=clock)
        recorder.on_handoff(JobPhase.PREPARE, OK, IDENTITY)
        clock.advance(5)
        events = recorder.on_handoff(JobPhase.ABORT, OK, IDENTITY)
        trace = json.loads(events[0].payload)
        self.assertEqual((trace["outcome"], trace["good"]), ("aborted", False))

    def test_a_refused_step_is_in_the_trace_and_makes_the_board_not_good(self):
        clock = Clock()
        recorder = BoardTraceRecorder(clock=clock)
        recorder.on_handoff(JobPhase.PREPARE, OK, IDENTITY)
        recorder.on_handoff(JobPhase.LOAD, REFUSED, IDENTITY)
        events = recorder.on_handoff(JobPhase.COMPLETE, OK, IDENTITY)
        trace = json.loads(events[0].payload)
        self.assertEqual(trace["outcome"], "completed")
        self.assertFalse(trace["good"])
        self.assertEqual([step["allowed"] for step in trace["steps"]], [True, False, True])

    def test_a_refused_complete_does_not_close_the_trace(self):
        recorder = BoardTraceRecorder(clock=Clock())
        self.assertEqual(recorder.on_handoff(JobPhase.COMPLETE, REFUSED, IDENTITY), [])
        self.assertEqual(recorder.open_boards, 1)

    def test_a_failed_board_is_closed_by_hand(self):
        recorder = BoardTraceRecorder(clock=Clock())
        recorder.on_handoff(JobPhase.PREPARE, OK, IDENTITY)
        events = recorder.finish(IDENTITY.fingerprint(), "failed")
        self.assertEqual(json.loads(events[0].payload)["outcome"], "failed")
        self.assertEqual(recorder.finish(IDENTITY.fingerprint(), "failed"), [])  # already closed
        with self.assertRaises(ValueError):
            recorder.finish("x", "perfect")

    def test_an_identity_that_is_not_stable_is_not_traced(self):
        recorder = BoardTraceRecorder(clock=Clock())
        self.assertEqual(recorder.on_handoff(JobPhase.PREPARE, OK, BoardIdentity("bad id!", "r", "v", "l")), [])
        self.assertEqual(recorder.open_boards, 0)

    def test_two_boards_are_two_traces(self):
        clock = Clock()
        recorder = BoardTraceRecorder(clock=clock)
        other = BoardIdentity("PCB-002", "RECIPE-A", "B", "LOT-7")
        recorder.on_handoff(JobPhase.PREPARE, OK, IDENTITY)
        recorder.on_handoff(JobPhase.PREPARE, OK, other)
        self.assertEqual(recorder.open_boards, 2)
        events = recorder.on_handoff(JobPhase.COMPLETE, OK, other)
        self.assertEqual(json.loads(events[0].payload)["fingerprint"], other.fingerprint())
        self.assertEqual(recorder.open_boards, 1)

    def test_the_boards_in_progress_are_bounded(self):
        recorder = BoardTraceRecorder(clock=Clock())
        for index in range(MAX_OPEN_TRACES + 20):
            recorder.on_handoff(JobPhase.PREPARE, OK, BoardIdentity(f"PCB-{index}", "R", "A", "L"))
        self.assertEqual(recorder.open_boards, MAX_OPEN_TRACES)

    def test_the_machine_source_must_be_a_stable_identifier(self):
        for bad in ("", "has space", "x" * 100, "../x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    BoardTraceRecorder(bad)


class SampleTests(unittest.TestCase):
    def trace(self, good=True):
        clock = Clock()
        recorder = BoardTraceRecorder(clock=clock)
        events = full_cycle(recorder, clock, last=JobPhase.COMPLETE if good else JobPhase.ABORT)
        return events

    def test_the_samples_follow_the_datalake_and_the_oee_convention(self):
        clock = Clock()
        sink_batches = []
        recorder = BoardTraceRecorder("pnp-1", sink=DatalakeSink("http://x", post=lambda url, body, headers: sink_batches.append(json.loads(body)) or 202), clock=clock)
        full_cycle(recorder, clock)
        (batch,) = sink_batches
        samples = batch["samples"]
        steps = [s for s in samples if s["kind"] == "board_handoff"]
        self.assertEqual(len(steps), 5)
        self.assertTrue(all(s["sourceId"] == f"board-{IDENTITY.fingerprint()[:32]}" for s in steps))
        self.assertEqual([s["fields"]["phase"] for s in steps], [0.0, 1.0, 2.0, 3.0, 4.0])
        (production,) = [s for s in samples if s["kind"] == "production_event"]
        self.assertEqual(production["sourceId"], "pnp-1")
        self.assertEqual(production["fields"], {"good": 1.0, "cycleTimeS": 40.0})

    def test_every_sample_is_what_the_datalake_accepts(self):
        clock = Clock()
        recorder = BoardTraceRecorder(clock=clock)
        events = full_cycle(recorder, clock)
        trace_dict = json.loads(events[0].payload)
        for name in ("started_at_ms", "finished_at_ms"):
            self.assertGreater(trace_dict[name], 100_000_000_000)  # milliseconds, not seconds
        from hydra_umc_bridge_openpnp.traceability import BoardTrace, TraceStep

        trace = BoardTrace(
            trace_dict["fingerprint"], trace_dict["outcome"],
            tuple(TraceStep(s["phase"], s["allowed"], s["handoff"], s["reason"], s["at_ms"], s["observed"]) for s in trace_dict["steps"]),
            trace_dict["started_at_ms"], trace_dict["finished_at_ms"],
        )
        for sample in datalake_samples(trace, "openpnp"):
            self.assertTrue(sample["sourceId"] and sample["kind"])
            self.assertIsInstance(sample["timestamp"], int)
            for value in sample["fields"].values():
                self.assertTrue(isinstance(value, float) and math.isfinite(value))

    def test_a_bad_board_is_not_good_in_the_production_event(self):
        clock = Clock()
        batches = []
        recorder = BoardTraceRecorder(sink=DatalakeSink("http://x", post=lambda u, b, h: batches.append(json.loads(b)) or 202), clock=clock)
        full_cycle(recorder, clock, last=JobPhase.ABORT)
        production = [s for s in batches[0]["samples"] if s["kind"] == "production_event"][0]
        self.assertEqual(production["fields"]["good"], 0.0)


class FakeDatalake(BaseHTTPRequestHandler):
    received: list = []
    status = 202
    token_seen: list = []

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", "0"))
        body = json.loads(self.rfile.read(length))
        type(self).token_seen.append(self.headers.get("Authorization"))
        if type(self).status < 300:
            type(self).received.append((self.path, body))
        self.send_response(type(self).status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):
        pass


class SinkTests(unittest.TestCase):
    def setUp(self):
        FakeDatalake.received, FakeDatalake.token_seen, FakeDatalake.status = [], [], 202
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeDatalake)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def test_the_default_transport_posts_a_batch_with_the_bearer_token(self):
        sink = DatalakeSink(self.url, token="a-token-of-some-length")
        self.assertTrue(sink.send([{"sourceId": "s", "kind": "k", "timestamp": 1_800_000_000_000, "fields": {"value": 1.0}}]))
        self.assertEqual(FakeDatalake.received[0][0], "/ingest/batch")
        self.assertEqual(FakeDatalake.received[0][1]["samples"][0]["sourceId"], "s")
        self.assertEqual(FakeDatalake.token_seen, ["Bearer a-token-of-some-length"])

    def test_without_a_token_no_authorization_is_sent(self):
        DatalakeSink(self.url).send([{"sourceId": "s"}])
        self.assertEqual(FakeDatalake.token_seen, [None])

    def test_an_error_status_is_not_accepted(self):
        FakeDatalake.status = 507
        self.assertFalse(DatalakeSink(self.url).send([{"sourceId": "s"}]))

    def test_a_data_lake_that_is_down_is_not_an_exception(self):
        self.server.shutdown()
        self.server.server_close()
        self.assertFalse(DatalakeSink(self.url, timeout_s=0.5).send([{"sourceId": "s"}]))

    def test_the_url_must_be_http(self):
        for bad in ("file:///etc/passwd", "ftp://x", "x"):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    DatalakeSink(bad)

    def test_an_empty_batch_is_nothing_to_do(self):
        self.assertTrue(DatalakeSink(self.url).send([]))
        self.assertEqual(FakeDatalake.received, [])

    def test_a_data_lake_that_was_down_gets_everything_on_the_next_trace(self):
        clock = Clock()
        recorder = BoardTraceRecorder(sink=DatalakeSink(self.url), clock=clock)
        FakeDatalake.status = 503
        full_cycle(recorder, clock)
        self.assertEqual(recorder.pending_samples, 6)
        self.assertEqual(FakeDatalake.received, [])
        FakeDatalake.status = 202
        self.assertTrue(recorder.flush())
        self.assertEqual(recorder.pending_samples, 0)
        self.assertEqual(len(FakeDatalake.received[0][1]["samples"]), 6)

    def test_what_waits_for_a_data_lake_is_bounded_and_sent_in_batches(self):
        clock = Clock()
        recorder = BoardTraceRecorder(sink=DatalakeSink(self.url), clock=clock)
        FakeDatalake.status = 503
        for index in range(900):
            identity = BoardIdentity(f"PCB-{index}", "R", "A", "L")
            recorder.on_handoff(JobPhase.PREPARE, OK, identity)
            recorder.on_handoff(JobPhase.COMPLETE, OK, identity)
        self.assertLessEqual(recorder.pending_samples, 5000)
        FakeDatalake.status = 202
        self.assertTrue(recorder.flush())
        self.assertTrue(all(len(body["samples"]) <= BATCH_SAMPLES for _, body in FakeDatalake.received))


def handoff_message(phase, key, board="PCB-001"):
    request = {
        "job": job_to_dict(BridgeJob("j-1", key, "orchestrator", phase, MachineState.IDLE, {"board_id": board})),
        "identity": {"board_id": board, "recipe_id": "RECIPE-A", "revision": "B", "lot_id": "LOT-7"},
    }
    return json.dumps(request).encode()


class BridgeTests(unittest.TestCase):
    def test_a_cycle_over_mqtt_ends_with_the_board_event(self):
        clock = Clock()
        recorder = BoardTraceRecorder(clock=clock)
        bridge = OpenPnpMqttBridge(lambda: CellState.READY, trace_recorder=recorder)
        published = []
        for index, phase in enumerate((JobPhase.PREPARE, JobPhase.LOAD, JobPhase.PROCESS, JobPhase.UNLOAD, JobPhase.COMPLETE)):
            clock.advance(3)
            published += bridge.handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_message(phase, f"h-{index}"))
        results = [p for p in published if p.topic.endswith("cmd/handoff/result")]
        events = [p for p in published if p.topic == EVENT_TOPIC]
        self.assertEqual(len(results), 5)
        self.assertEqual(len(events), 1)
        self.assertEqual(json.loads(events[0].payload)["outcome"], "completed")

    def test_the_answer_to_the_handoff_is_the_same_with_or_without_a_recorder(self):
        with_recorder = OpenPnpMqttBridge(lambda: CellState.READY, trace_recorder=BoardTraceRecorder(clock=Clock()))
        without = OpenPnpMqttBridge(lambda: CellState.READY)
        message = handoff_message(JobPhase.LOAD, "h-1")
        self.assertEqual(with_recorder.handle_message(f"{TOPIC_PREFIX}cmd/handoff", message)[0].payload, without.handle_message(f"{TOPIC_PREFIX}cmd/handoff", message)[0].payload)

    def test_a_recorder_that_fails_never_changes_the_answer(self):
        class Broken:
            def on_handoff(self, *args):
                raise RuntimeError("disk full")

        bridge = OpenPnpMqttBridge(lambda: CellState.READY, trace_recorder=Broken())  # type: ignore[arg-type]
        published = bridge.handle_message(f"{TOPIC_PREFIX}cmd/handoff", handoff_message(JobPhase.LOAD, "h-1"))
        self.assertEqual(len(published), 1)
        self.assertTrue(json.loads(published[0].payload)["allowed"])

    def test_a_repeated_key_is_answered_once_and_traced_once(self):
        from hydra_umc_sdk.job_intake import IdempotencyStore

        recorder = BoardTraceRecorder(clock=Clock())
        bridge = OpenPnpMqttBridge(lambda: CellState.READY, IdempotencyStore(), trace_recorder=recorder)
        message = handoff_message(JobPhase.PREPARE, "h-1")
        bridge.handle_message(f"{TOPIC_PREFIX}cmd/handoff", message)
        again = bridge.handle_message(f"{TOPIC_PREFIX}cmd/handoff", message)
        self.assertEqual(len(again), 1)
        self.assertEqual(recorder.open_boards, 1)
        self.assertEqual(len(recorder._open[IDENTITY.fingerprint()].steps), 1)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
