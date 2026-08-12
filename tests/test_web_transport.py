import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, relative_path):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


server = load_module("quest_web_server", "web/server.py")
analyzer = load_module("quest_log_analyzer", "web/analyze_logs.py")


def sample(sequence, client_time, tracked=True):
    pose = {"position": [0, 0, 0], "orientation": [0, 0, 0, 1]}
    controller = {"grip": pose, "ray": pose, "buttons": [], "axes": []}
    return {
        "sequence": sequence,
        "clientTime": client_time,
        "head": pose if tracked else None,
        "left": controller if tracked else None,
        "right": controller if tracked else None,
    }


class PayloadTests(unittest.TestCase):
    def test_valid_payload(self):
        session, samples = server.validate_payload({
            "protocolVersion": 1,
            "sessionId": "session-1",
            "samples": [sample(0, 10.0)],
        })
        self.assertEqual(session, "session-1")
        self.assertEqual(len(samples), 1)

    def test_rejects_wrong_protocol_and_bad_sequence(self):
        with self.assertRaises(ValueError):
            server.validate_payload({"protocolVersion": 2, "sessionId": "s", "samples": [sample(0, 0)]})
        bad = sample(0, 0)
        bad["sequence"] = True
        with self.assertRaises(ValueError):
            server.validate_payload({"protocolVersion": 1, "sessionId": "s", "samples": [bad]})

    def test_safety_datagram_requires_tracking_and_both_second_buttons(self):
        value = sample(7, 10.0)
        for side in ("left", "right"):
            value[side]["buttons"] = [{"pressed": False}, {"pressed": True}]
        self.assertEqual(server.safety_datagram("session-1", value),
                         b"G1Q1 session-1 7 1 1 1 1\n")
        value["right"] = json.loads(json.dumps(value["right"]))
        value["right"]["buttons"][1]["pressed"] = False
        self.assertEqual(server.safety_datagram("session-1", value),
                         b"G1Q1 session-1 7 1 0 1 0\n")

    def test_reads_only_fresh_complete_supervisor_status(self):
        value = {
            "state": "ARMED", "reason": "ok", "wouldPublish": True,
            "localEnable": True, "tracking": True, "deadman": True,
            "leftGrip": True, "rightGrip": True,
            "questAgeMs": 20, "lowstateAgeMs": 0,
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "status.json"
            path.write_text(json.dumps(value), encoding="utf-8")
            result = server.read_supervisor_status(path, now=path.stat().st_mtime + 0.1)
            self.assertTrue(result["fresh"])
            self.assertEqual(result["state"], "ARMED")
            stale = server.read_supervisor_status(path, now=path.stat().st_mtime + 1.0)
            self.assertFalse(stale["fresh"])


class SessionTests(unittest.TestCase):
    def test_counts_gaps_duplicates_order_and_tracking(self):
        stats = server.SessionStats("s", 1.0, 1.0)
        stats.observe([
            sample(0, 0), sample(1, 11), sample(3, 33), sample(3, 33), sample(2, 44, False)
        ], 1.1, {"lastRttMs": 12.5})
        result = stats.snapshot(1.1)
        self.assertEqual(result["estimatedLost"], 1)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(result["outOfOrder"], 1)
        self.assertEqual(result["invalidTracking"], {"head": 1, "left": 1, "right": 1})
        self.assertEqual(result["recentRttMs"], 12.5)
        self.assertEqual(result["safetyState"], "DISARMED")

    def test_enforces_one_live_session_and_allows_takeover_after_timeout(self):
        registry = server.SessionRegistry()
        registry.accept("first", [sample(0, 0)], {}, now=1.0)
        with self.assertRaises(RuntimeError):
            registry.accept("second", [sample(0, 0)], {}, now=1.1)
        result = registry.accept(
            "second", [sample(0, 0)], {}, now=1.0 + server.STREAM_TIMEOUT_SECONDS + 0.01)
        self.assertEqual(result["sessionId"], "second")
        self.assertEqual(result["safetyState"], "DISARMED")

    def test_stale_stream_is_disconnected_and_disarmed(self):
        registry = server.SessionRegistry()
        registry.accept("first", [sample(0, 0)], {}, now=1.0)
        result = registry.status(now=1.0 + server.STREAM_TIMEOUT_SECONDS + 0.01)
        self.assertEqual(result["linkState"], "DISCONNECTED")
        self.assertEqual(result["safetyState"], "DISARMED")


class AnalyzerTests(unittest.TestCase):
    def test_reports_transport_and_input_activity(self):
        first = sample(0, 0)
        second = sample(2, 11)
        for value in (first, second):
            value["left"]["buttons"] = [{"pressed": True, "touched": True, "value": 1}]
            value["left"]["axes"] = [0.5]
            value["right"]["buttons"] = [{"pressed": True, "touched": False, "value": 1}]
            value["right"]["axes"] = [-0.5]
        record = {
            "sessionId": "analyzer-test",
            "remote": "10.42.0.10",
            "clientMetrics": {"lastRttMs": 12, "clockOffsetMs": 3},
            "samples": [first, second],
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.ndjson"
            path.write_text(json.dumps(record) + "\n", encoding="utf-8")
            result = analyzer.analyze(path)
        self.assertEqual(result["estimatedLost"], 1)
        self.assertEqual(result["rttMeanMs"], 12)
        self.assertEqual(result["clockOffsetMeanMs"], 3)
        self.assertEqual(result["inputActivity"]["left"]["axisActiveSamples"], 2)
        self.assertEqual(result["intervalMaxMs"], 11)
        self.assertEqual(result["stallsOver25Ms"], 0)

if __name__ == "__main__":
    unittest.main()
