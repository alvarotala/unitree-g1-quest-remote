"""Passive Unitree RTP/H.264 to WebRTC gateway.

The native video hub remains the only process that opens /dev/video4.  This
module joins its multicast output and gives one browser peer a WebRTC view.
"""

import threading
import time
import re


CAMERA_GROUP = "230.1.1.1"
CAMERA_PORT = 1720
CAMERA_PAYLOAD_TYPE = 96


def pipeline_description(interface, webrtc_payload_type=96):
    if not interface or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-" for character in interface):
        raise ValueError("invalid camera interface")
    if (isinstance(webrtc_payload_type, bool) or
            not isinstance(webrtc_payload_type, int) or
            not 0 <= webrtc_payload_type <= 127):
        raise ValueError("invalid WebRTC payload type")
    return (
        f'udpsrc multicast-group={CAMERA_GROUP} multicast-iface={interface} '
        f'auto-multicast=true port={CAMERA_PORT} '
        f'caps="application/x-rtp,media=video,encoding-name=H264,'
        f'payload={CAMERA_PAYLOAD_TYPE},clock-rate=90000" '
        '! rtpjitterbuffer latency=20 drop-on-latency=true '
        '! rtph264depay '
        '! h264parse '
        f'! rtph264pay name=pay pt={webrtc_payload_type} config-interval=-1 mtu=1200 '
        '! application/x-rtp,media=video,encoding-name=H264,'
        f'payload={webrtc_payload_type},clock-rate=90000,packetization-mode=(string)1 '
        '! webrtcbin name=webrtc bundle-policy=max-bundle'
    )


def validate_offer_sdp(value):
    if not isinstance(value, str) or not value.startswith("v=0"):
        raise ValueError("invalid WebRTC offer SDP")
    if len(value) > 128 * 1024:
        raise ValueError("WebRTC offer SDP is too large")
    if "m=video" not in value:
        raise ValueError("WebRTC offer has no video media section")
    return value


def h264_payload_type(offer_sdp):
    """Return the Quest payload number for packetized H.264."""
    validate_offer_sdp(offer_sdp)
    h264_types = []
    packetized_types = set()
    for line in offer_sdp.splitlines():
        mapping = re.match(r"a=rtpmap:(\d+)\s+H264/90000(?:\s|$)", line, re.IGNORECASE)
        if mapping:
            h264_types.append(int(mapping.group(1)))
        fmtp = re.match(r"a=fmtp:(\d+)\s+(.+)$", line, re.IGNORECASE)
        if fmtp and re.search(r"(?:^|;)\s*packetization-mode=1(?:;|$)", fmtp.group(2)):
            packetized_types.add(int(fmtp.group(1)))
    for payload_type in h264_types:
        if payload_type in packetized_types:
            return payload_type
    if h264_types:
        return h264_types[0]
    raise ValueError("Quest WebRTC offer does not include H.264")


class CameraUnavailable(RuntimeError):
    pass


class _Peer:
    def __init__(self, backend, interface, payload_type):
        self.backend = backend
        self.Gst = backend.Gst
        self.GstSdp = backend.GstSdp
        self.GstWebRTC = backend.GstWebRTC
        self.payload_type = payload_type
        self.pipeline = self.Gst.parse_launch(pipeline_description(interface, payload_type))
        self.webrtc = self.pipeline.get_by_name("webrtc")
        if self.webrtc is None:
            raise CameraUnavailable("webrtcbin was not created")
        self.answer_ready = threading.Event()
        self.answer_sdp = None
        self.error = None
        self.ice_candidates = 0
        self.started_at = time.monotonic()
        self._finish_lock = threading.Lock()

        self.webrtc.connect("notify::ice-gathering-state", self._on_ice_state)
        self.webrtc.connect("on-ice-candidate", self._on_ice_candidate)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        self.bus = bus

        result = self.pipeline.set_state(self.Gst.State.PLAYING)
        if result == self.Gst.StateChangeReturn.FAILURE:
            raise CameraUnavailable("camera WebRTC pipeline failed to start")

    def _fail(self, message):
        with self._finish_lock:
            if self.answer_ready.is_set():
                return
            self.error = str(message)
            self.answer_ready.set()

    def _finish_answer(self):
        with self._finish_lock:
            if self.answer_ready.is_set():
                return
            description = self.webrtc.get_property("local-description")
            if description is None or description.sdp is None:
                return
            self.answer_sdp = description.sdp.as_text()
            self.answer_ready.set()

    def _on_bus_message(self, _bus, message):
        if message.type == self.Gst.MessageType.ERROR:
            error, debug = message.parse_error()
            detail = f"{error.message}"
            if debug:
                detail += f" ({debug})"
            self._fail(detail)

    def _on_ice_candidate(self, _webrtc, _mline_index, _candidate):
        self.ice_candidates += 1

    def _on_ice_state(self, webrtc, _property):
        state = webrtc.get_property("ice-gathering-state")
        if state == self.GstWebRTC.WebRTCICEGatheringState.COMPLETE:
            self._finish_answer()

    def _on_answer_created(self, promise, _unused, _unused_again):
        try:
            reply = promise.get_reply()
            answer = reply.get_value("answer") if reply is not None else None
            if answer is None:
                self._fail("webrtcbin did not create an answer")
                return
            local_promise = self.Gst.Promise.new()
            self.webrtc.emit("set-local-description", answer, local_promise)
        except Exception as exc:  # PyGI callback boundary
            self._fail(exc)

    def _on_remote_description_set(self, _promise, _unused, _unused_again):
        try:
            promise = self.Gst.Promise.new_with_change_func(
                self._on_answer_created, None, None)
            self.webrtc.emit("create-answer", None, promise)
        except Exception as exc:  # PyGI callback boundary
            self._fail(exc)

    def accept_offer(self, offer_sdp, timeout=12.0):
        result, message = self.GstSdp.SDPMessage.new_from_text(offer_sdp)
        if result != self.GstSdp.SDPResult.OK:
            raise ValueError("GStreamer rejected the WebRTC offer SDP")
        offer = self.GstWebRTC.WebRTCSessionDescription.new(
            self.GstWebRTC.WebRTCSDPType.OFFER, message)
        promise = self.Gst.Promise.new_with_change_func(
            self._on_remote_description_set, None, None)
        self.webrtc.emit("set-remote-description", offer, promise)

        deadline = time.monotonic() + timeout
        while not self.answer_ready.wait(0.1) and time.monotonic() < deadline:
            state = self.webrtc.get_property("ice-gathering-state")
            if state == self.GstWebRTC.WebRTCICEGatheringState.COMPLETE:
                self._finish_answer()
        if not self.answer_ready.is_set():
            raise CameraUnavailable("timeout while gathering WebRTC ICE candidates")
        if self.error:
            raise CameraUnavailable(self.error)
        if not self.answer_sdp:
            raise CameraUnavailable("WebRTC answer is empty")
        return self.answer_sdp

    def status(self):
        property_name = ("connection-state" if self.webrtc.find_property("connection-state")
                         else "ice-connection-state")
        connection = self.webrtc.get_property(property_name)
        return {
            "enabled": True,
            "active": True,
            "connectionState": connection.value_nick if connection is not None else "unknown",
            "iceCandidates": self.ice_candidates,
            "payloadType": self.payload_type,
            "ageSeconds": round(time.monotonic() - self.started_at, 1),
        }

    def stop(self):
        self.pipeline.set_state(self.Gst.State.NULL)
        self.bus.remove_signal_watch()


class _Backend:
    def __init__(self):
        try:
            import gi
            gi.require_version("Gst", "1.0")
            gi.require_version("GstSdp", "1.0")
            gi.require_version("GstWebRTC", "1.0")
            from gi.repository import GLib, Gst, GstSdp, GstWebRTC
        except (ImportError, ValueError) as exc:
            raise CameraUnavailable(f"GStreamer WebRTC bindings unavailable: {exc}") from exc
        self.GLib = GLib
        self.Gst = Gst
        self.GstSdp = GstSdp
        self.GstWebRTC = GstWebRTC
        Gst.init(None)
        for element in ("udpsrc", "rtpjitterbuffer", "rtph264depay", "h264parse",
                        "rtph264pay", "webrtcbin", "nicesrc", "nicesink"):
            if Gst.ElementFactory.find(element) is None:
                raise CameraUnavailable(f"missing GStreamer element: {element}")
        self.loop = GLib.MainLoop()
        self.thread = threading.Thread(target=self.loop.run, name="camera-glib", daemon=True)
        self.thread.start()

    def stop(self):
        self.loop.quit()
        self.thread.join(timeout=2.0)


class CameraGateway:
    def __init__(self, interface="eth0", enabled=True):
        self.interface = interface
        self.enabled = enabled
        self.lock = threading.Lock()
        self.peer = None
        self.backend = None
        self.last_error = None
        if enabled:
            try:
                self.backend = _Backend()
            except CameraUnavailable as exc:
                self.last_error = str(exc)

    def answer(self, offer_sdp):
        validate_offer_sdp(offer_sdp)
        payload_type = h264_payload_type(offer_sdp)
        if not self.enabled:
            raise CameraUnavailable("camera gateway disabled")
        if self.backend is None:
            raise CameraUnavailable(self.last_error or "camera gateway unavailable")
        with self.lock:
            try:
                if self.peer is not None:
                    self.peer.stop()
                print(f"Camera WebRTC: negotiated Quest H.264 payload type {payload_type}")
                self.peer = _Peer(self.backend, self.interface, payload_type)
                return self.peer.accept_offer(offer_sdp)
            except Exception as exc:
                self.last_error = str(exc)
                if self.peer is not None:
                    self.peer.stop()
                self.peer = None
                if isinstance(exc, (CameraUnavailable, ValueError)):
                    raise
                raise CameraUnavailable(str(exc)) from exc

    def stop_peer(self):
        with self.lock:
            if self.peer is not None:
                self.peer.stop()
                self.peer = None

    def status(self):
        if not self.enabled:
            return {"enabled": False, "active": False, "reason": "disabled"}
        if self.backend is None:
            return {"enabled": True, "active": False,
                    "reason": self.last_error or "unavailable"}
        with self.lock:
            if self.peer is None:
                return {"enabled": True, "active": False, "reason": "waiting for Quest"}
            value = self.peer.status()
            if self.last_error:
                value["lastError"] = self.last_error
            return value

    def close(self):
        self.stop_peer()
        if self.backend is not None:
            self.backend.stop()
