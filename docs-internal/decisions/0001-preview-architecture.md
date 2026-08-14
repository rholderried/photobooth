# ADR 0001 — Serve live preview as MJPEG from `cameracontrol.py`

**Status:** `accepted` (2026-08-14) — not yet implemented
**Supersedes:** the go2rtc-direct-from-gphoto2 architecture, and the
v4l2loopback approaches explored in
[../research/camera-reliability-live-preview.md](../research/camera-reliability-live-preview.md)

## Context

Three problems turned out to share one root cause.

1. **Only one process can hold the camera's PTP session.** Today `go2rtc`
   holds it by running `gphoto2 --capture-movie --stdout`, and that process
   has no control channel.
2. **Capture therefore tears the session down every time.** The
   `/usr/local/bin/capture` wrapper stops go2rtc, captures, restarts it. Under
   stress this wedges the camera's USB controller (research doc, Bug #2), and
   it orphans a `gphoto2` child on every capture (Bug #1).
3. **The customer focus-config screen needs focus control *during* preview.**
   `manualfocusdrive` requires liveview active, but sending it means holding
   the PTP session — which go2rtc already has. With the current architecture,
   every focus nudge would drop the preview and re-trigger the wedge.

The obvious fix — `api/cameracontrol.py`, which holds **one** persistent
session for both preview and capture — was already proven to give fast, clean
captures with no PTP churn. It was rolled back only because it has no HTTP
stream endpoint, and both routes to get a picture out of it failed:

- **Approach A** — v4l2loopback + browser `getUserMedia()`: the browser never
  enumerated the virtual device (`NotFoundError`), across every combination of
  Chromium/Firefox, Wayland/XWayland, sandbox and constraint settings tried.
  A long-standing, widely-reported browser↔v4l2loopback gap.
- **Approach B** — go2rtc/ffmpeg reading `/dev/video9`: a second reader
  captured exactly one frame and stalled.

## Decision

**Add an MJPEG-over-HTTP endpoint directly to `cameracontrol.py`**, and drop
v4l2loopback from the preview path entirely.

`cameracontrol.py` already receives preview frames via `python-gphoto2` and
already runs a ZMQ request/reply loop on `tcp://localhost:5555`
(`api/cameracontrol.py:456-458`). Serving those frames as
`multipart/x-mixed-replace` is a small addition to a process that already has
the data in hand.

## Consequences

**Resolves four things at once:**

- **Kiosk preview** uses `preview.mode = 'url'` against the new endpoint. A
  page loading a URL is not a camera-permission request, so the entire
  `getUserMedia`/enumeration problem disappears rather than being solved.
- **Customer phone preview** consumes the same endpoint over the LAN — the
  feature that motivated this ADR.
- **Bug #2 (PTP wedge)** is fixed by construction: the persistent session
  removes the per-capture teardown.
- **Bug #1 (orphaned gphoto2)** becomes moot: go2rtc leaves the camera path.

**Costs and risks:**

- Preview and capture now share one process — it becomes a single point of
  failure and needs `Restart=on-failure` (already in the unit).
- MJPEG is bandwidth-hungry vs. go2rtc's codecs. Probably fine on a LAN for
  one or two viewers; needs measuring with the kiosk *and* a phone attached.
- Frame rate through Python may be lower than go2rtc's. Acceptable for
  framing/focus; verify it's tolerable for the countdown UI.
- Concurrent viewers need explicit handling (one capture loop fanning out to
  N subscribers, not one gphoto2 read per client).

## Rejected alternatives

| Option | Why not |
|---|---|
| Keep go2rtc, stop/start it per focus nudge | Preview drops on every button press; re-triggers the Bug #2 wedge. The exact thing we're trying to escape. |
| Retry v4l2loopback (Approach A) | Extensively explored and failed; upstream maintainers have not solved it either (confirmed via their 2026-06 commit history). Do not re-attempt without new information. |
| Second reader on `/dev/video9` (Approach B) | One frame then stall. Would need kernel-module-level investigation for no benefit once MJPEG removes the need. |
| Absolute focus positioning | Impossible on this hardware — see [../reference/gphoto2-eos-rp.md](../reference/gphoto2-eos-rp.md). |

## Focus UI implication

Since focus is relative-only and open-loop, the config screen exposes
**visual nudges** (Near/Far, coarse + fine) plus `eoszoom` punch-in for
checking sharpness — *not* a distance-in-metres slider. Depth of field at f/4
gives a 1.3–3.5 m in-focus zone at typical booth distances, so eyeball
accuracy is sufficient and metric precision would be false precision.

## Validation — spike results (2026-08-14)

Spiked before building any UI, because it was the load-bearing risk.
**The decision holds.** Implemented on branch `feature/cameracontrol-mjpeg`
as `api/mjpeg_server.py` plus a small patch to `api/cameracontrol.py`.

| # | Check | Result |
|---|---|---|
| 1 | Endpoint streams frames | ✅ 157 frames over 13 s, every SOI/EOI matched |
| 2 | Kiosk renders it | ✅ **confirmed** — Chromium rendered live video, `clients: 1` |
| 3 | Phone on the LAN renders it | ⬜ not yet tested |
| 4 | **`manualfocusdrive` while streaming** | ✅ **confirmed** — 4 nudges, stream never dropped |
| 5 | Nudge repeatability | ⚠️ **not symmetric** — see [../reference/gphoto2-eos-rp.md](../reference/gphoto2-eos-rp.md) |

### Check 2 in detail

`preview.url` already points at an MJPEG stream (go2rtc's
`/api/stream.mjpeg`), so switching is a **one-line config change** — the
frontend needs no modification at all:

```php
'url' => 'http://localhost:8081/stream.mjpg',   // was localhost:1984/api/stream.mjpeg?src=photobooth
```

Verified by driving the kiosk over CDP (port 9222): Chromium rendered the
stream, `/healthz` showed `clients: 1`, and the frame counter kept climbing.
Proven *live* rather than a single stuck frame by defocusing the lens between
two screenshots — the rendered image visibly blurred in response.

Note `preview.js` appends a cache-busting `?t=<timestamp>`; the handler
strips query strings, so this already works.

### The finding that made this easy

`capture_preview()` returns **fully-formed JPEG frames** — verified on the
EOS RP: `ffd8…ffd9`, mime `image/jpeg`, 960×640, ~21 fps. MJPEG over HTTP is
exactly that byte stream with multipart boundaries, so the endpoint needs
**no re-encoding, no ffmpeg and no v4l2loopback**. The original assumption —
that getting frames out of `cameracontrol.py` was the hard part — was wrong;
the frames were already in the right format all along.

### Check 4 in detail — the crux

With a client actively consuming `/stream.mjpg`, four focus nudges were driven
over ZMQ (`Near 1`, `Near 2`, `Far 2`, `Far 1`). All four applied
(`Config set manualfocusdrive=…`), the client stayed connected, the frame
counter kept advancing at ~15 fps throughout, and the daemon logged no errors.
The stream file was byte-intact afterwards.

This is what the old architecture could not do at any price.

### Measured characteristics

- **Frame rate:** ~21 fps uncapped from the camera; server throttles to 15 by
  default (`--mjpeg-fps`).
- **Bandwidth:** ~148 KB/frame → **14.4 Mbit/s at 12 fps**, ~25 Mbit/s
  uncapped. Fine over ethernet to the kiosk; heavy for a phone over WiFi.
  Downscaling for phone clients is the obvious future optimisation (would need
  PIL or ffmpeg, deliberately not added for the spike).
- **Resilience:** slow clients drop frames rather than stalling the capture
  loop (one-slot queue, latest-frame-wins).

### Endpoints

| Path | Purpose |
|---|---|
| `/stream.mjpg` | `multipart/x-mixed-replace` live stream |
| `/snapshot.jpg` | single most-recent frame — cheap for low bandwidth or testing |
| `/healthz` | JSON: client count, frames published, average fps |

### Remaining before this ships

Checks 2, 3 and 5, plus: bandwidth behaviour with kiosk *and* phone attached
simultaneously, and a decision on binding (`--mjpeg-bind` defaults to
`0.0.0.0` so phones can reach it — that is an unauthenticated video feed of
the booth on the LAN, which needs the access-control work in
[ADR 0002](0002-customer-config-access-control.md) landing alongside it).
