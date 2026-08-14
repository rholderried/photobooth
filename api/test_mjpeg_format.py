#!/usr/bin/env python3
"""
Tests for MjpegServer's preview-format guard.

Runs without a camera: MjpegServer takes plain bytes, so a non-JPEG camera is
simulated by publishing non-JPEG bytes. That is the whole point -- this path
is otherwise only reachable by physically swapping to an incompatible body.

    python3 test_mjpeg_format.py
"""
import json
import sys
import time
import urllib.error
import urllib.request

from mjpeg_server import MjpegServer

JPEG = b"\xff\xd8\xff\xdb" + b"\x00" * 512 + b"\xff\xd9"
NOT_JPEG = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 512

failures = []


def check(label, condition, detail=""):
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {label}" + (f" -- {detail}" if detail and not condition else ""))
    if not condition:
        failures.append(label)


def get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_jpeg_accepted(port=8091):
    print("JPEG preview is accepted:")
    s = MjpegServer(host="127.0.0.1", port=port, max_fps=0)
    s.start()
    try:
        s.publish(JPEG, "image/jpeg")
        health = json.loads(get(port, "/healthz")[1])
        check("no format_error recorded", health["format_error"] is None, str(health))
        check("frame was published", health["has_frame"] is True)
        code, body = get(port, "/snapshot.jpg")
        check("snapshot returns 200", code == 200, f"got {code}")
        check("snapshot body is the frame", body == JPEG)
    finally:
        s.stop()


def test_non_jpeg_rejected(port=8092):
    print("Non-JPEG preview is rejected loudly:")
    s = MjpegServer(host="127.0.0.1", port=port, max_fps=0)
    s.start()
    try:
        s.publish(NOT_JPEG, "image/webp")
        health = json.loads(get(port, "/healthz")[1])
        check("format_error is recorded", health["format_error"] is not None)
        check(
            "error names the reported mime",
            "image/webp" in (health["format_error"] or ""),
            str(health["format_error"]),
        )
        check("no frame was published", health["has_frame"] is False)

        code, _ = get(port, "/stream.mjpg")
        check("stream returns 503 not garbage", code == 503, f"got {code}")
        code, _ = get(port, "/snapshot.jpg")
        check("snapshot returns 503", code == 503, f"got {code}")
        code, _ = get(port, "/healthz")
        check("healthz still answers (for diagnosis)", code == 200, f"got {code}")

        # A later good frame must not silently revive a broken stream: the
        # camera has not changed, so neither should our verdict.
        s.publish(JPEG, "image/jpeg")
        health = json.loads(get(port, "/healthz")[1])
        check("verdict is sticky", health["format_error"] is not None)
    finally:
        s.stop()


def test_check_runs_once(port=8093):
    print("Validation does not re-run per frame:")
    s = MjpegServer(host="127.0.0.1", port=port, max_fps=0)
    s.start()
    try:
        for _ in range(50):
            s.publish(JPEG, "image/jpeg")
        health = json.loads(get(port, "/healthz")[1])
        check("all 50 frames published", health["frames_published"] == 50, str(health))
        check("still no format_error", health["format_error"] is None)
    finally:
        s.stop()


if __name__ == "__main__":
    test_jpeg_accepted()
    test_non_jpeg_rejected()
    test_check_runs_once()
    print()
    if failures:
        print(f"{len(failures)} FAILED: {', '.join(failures)}")
        sys.exit(1)
    print("all checks passed")
