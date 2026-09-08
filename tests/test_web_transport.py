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
camera = load_module("quest_camera_webrtc", "web/camera_webrtc.py")


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
    def test_camera_pipeline_reuses_native_multicast_without_v4l2(self):
        description = camera.pipeline_description("eth0", 102)
        self.assertIn("230.1.1.1", description)
        self.assertIn("port=1720", description)
        self.assertIn("webrtcbin", description)
        self.assertIn("pt=102", description)
        self.assertIn("payload=102", description)
        self.assertNotIn("/dev/video", description)
        self.assertNotIn("v4l2src", description)

    def test_camera_offer_requires_video_sdp(self):
        valid = ("v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96 102\r\n"
                 "a=rtpmap:96 VP8/90000\r\n"
                 "a=rtpmap:102 H264/90000\r\n"
                 "a=fmtp:102 level-asymmetry-allowed=1;packetization-mode=1;profile-level-id=42e01f\r\n")
        self.assertEqual(camera.validate_offer_sdp(valid), valid)
        self.assertEqual(camera.h264_payload_type(valid), 102)
        with self.assertRaises(ValueError):
            camera.validate_offer_sdp("v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n")
        with self.assertRaises(ValueError):
            camera.h264_payload_type("v=0\r\nm=video 9 UDP/TLS/RTP/SAVPF 96\r\na=rtpmap:96 VP8/90000\r\n")
        with self.assertRaises(ValueError):
            camera.pipeline_description("eth0;bad")

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
                         b"G1Q2 session-1 7 1 1 1 1 0.0000 0.0000 0.0000 0.0000 0 0 0 0 0 0\n")
        value["right"] = json.loads(json.dumps(value["right"]))
        value["right"]["buttons"][1]["pressed"] = False
        self.assertEqual(server.safety_datagram("session-1", value),
                         b"G1Q2 session-1 7 1 0 1 0 0.0000 0.0000 0.0000 0.0000 0 0 0 0 0 0\n")

    def test_safety_datagram_carries_sticks_triggers_and_face_buttons(self):
        value = sample(8, 11.0)
        value["left"] = json.loads(json.dumps(value["left"]))
        value["right"] = json.loads(json.dumps(value["right"]))
        value["left"]["axes"] = [0, 0, 0.25, -0.5]
        value["right"]["axes"] = [0, 0, -0.75, 1]
        value["left"]["buttons"] = [
            {"pressed": True}, {"pressed": True}, {"pressed": False},
            {"pressed": False}, {"pressed": True}, {"pressed": False}]
        value["right"]["buttons"] = [
            {"pressed": False}, {"pressed": True}, {"pressed": False},
            {"pressed": False}, {"pressed": False}, {"pressed": True}]
        self.assertEqual(
            server.safety_datagram("s", value),
            b"G1Q2 s 8 1 1 1 1 0.2500 -0.5000 -0.7500 1.0000 1 0 1 0 0 1\n")

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
        self.assertIn("gripDiagnostic", result)
        self.assertEqual(result["deadmanReleaseTransitions"], 0)

if __name__ == "__main__":
    unittest.main()
