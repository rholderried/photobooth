# Live preview architecture

**Status:** `partial` — replacement implemented and proven on a branch, not
yet deployed. Updated 2026-08-14.

## Current state (deployed)

`go2rtc` streams directly from `gphoto2`, `preview.mode = 'url'`. Works, but
couples preview to the per-capture PTP teardown — see
[camera-backends.md](camera-backends.md).

## Replacement (branch `feature/cameracontrol-mjpeg`, working)

`api/mjpeg_server.py` serves the camera's preview frames as MJPEG over HTTP
straight from `cameracontrol.py`, which holds the single PTP session.

```
camera ──PTP──> cameracontrol.py ──┬──> MJPEG /stream.mjpg ──> kiosk + phones
   (one session, always open)      └──> ffmpeg → v4l2 (optional, --no-v4l2)
                     ▲
                     └── ZMQ :5555 ── focus nudges, capture, config
```

Run it with:

```bash
python3 cameracontrol.py --mjpeg-port 8081 --no-v4l2
```

Proven working: 157 intact frames over 13 s, and focus driven over ZMQ
*while streaming* without dropping the client. Full results and remaining
gaps: [../decisions/0001-preview-architecture.md](../decisions/0001-preview-architecture.md).

The key enabler is that `capture_preview()` already returns complete JPEGs
([../reference/gphoto2-eos-rp.md](../reference/gphoto2-eos-rp.md)), so no
transcoding is involved.

## Preview modes

`preview.mode` is the key config switch. Known values:

| Mode | Mechanism |
|---|---|
| `url` | Browser loads an HTTP stream URL (go2rtc today) |
| `device_cam` | Browser `getUserMedia()` against a local video device |

`device_cam` is what the v4l2loopback work targeted. It **does not work on
this Pi** — the browser never enumerates the virtual device. Fully documented
in [../research/camera-reliability-live-preview.md](../research/camera-reliability-live-preview.md).

> **Do not re-attempt v4l2loopback + `getUserMedia` without new information.**
> Exhaustively explored across browsers, Wayland/XWayland, sandbox settings
> and constraint shapes. Upstream maintainers have not solved it either.

## Decided direction

[ADR 0001](../decisions/0001-preview-architecture.md): serve MJPEG over HTTP
directly from `cameracontrol.py`, keep `preview.mode = 'url'`, and drop
v4l2loopback from the preview path entirely. This also makes preview reachable
from a customer's phone, which `device_cam` never could.

## Relevant frontend code

- `assets/js/preview.js` — preview setup (note: the `getUserMedia`
  constraints fix, changing hard requirements to `ideal` hints, is committed
  on branch `feature/device-cam-preview` and worth keeping)
- `assets/js/test-preview.js`

## To document

- Full enumeration of `preview.mode` values from the config schema
- How `preview.js` chooses and initialises a mode
- Where the countdown/flash timing interacts with preview
