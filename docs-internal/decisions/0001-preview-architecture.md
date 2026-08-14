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

## Validation plan

Spike the MJPEG endpoint **before** building any UI. It is the load-bearing
risk: if frames don't stream cleanly to both kiosk and phone, this feature
needs a different shape entirely.

1. Add the endpoint; confirm a frame stream with `curl`.
2. Confirm the kiosk renders it via `preview.mode = 'url'`.
3. Confirm a phone on the LAN renders it.
4. Confirm `manualfocusdrive` over ZMQ works *while* streaming — the crux.
5. Only then measure the nudge-repeatability question from the reference doc.
