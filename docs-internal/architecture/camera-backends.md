# Camera backends and the one-session rule

**Status:** `partial` — the constraint is documented; the code paths are not.

## The rule that constrains everything

**Only one process may hold the camera's USB/PTP session at a time.** Every
architectural difficulty in this project traces back to this.

Consequences:
- A preview stream and a capture cannot come from two different processes.
- Sending a config command (e.g. `manualfocusdrive`) requires holding the
  session — so it cannot be done while another process is streaming.
- `manualfocusdrive` additionally requires **liveview to be active**, which
  means focus control and preview are inseparable.

## Two backends exist

### 1. `gphoto2` CLI (currently deployed)

`go2rtc` runs `gphoto2 --capture-movie --stdout` for preview; captures go
through `/usr/local/bin/capture`, which stops go2rtc, runs
`gphoto2 --capture-image-and-download`, and restarts it.

- Config: `preview.mode = 'url'`, `commands.take_picture = 'capture %s'`
- Tears down and rebuilds the PTP session **on every capture**
- Two known bugs result — see
  [../research/camera-reliability-live-preview.md](../research/camera-reliability-live-preview.md)
- `go2rtc` spawns its `gphoto2` child **on demand**, so an idle go2rtc leaves
  the camera free. Verify with `pgrep -a gphoto2` before manual gphoto2 work.

### 2. `api/cameracontrol.py` (upstream, not currently deployed)

Persistent daemon using `python-gphoto2`, holding **one** continuous session
for both preview and capture. ZMQ request/reply on `tcp://localhost:5555`
(`api/cameracontrol.py:456-458`). ~750 lines.

- Gave fast (~1 s), clean captures with zero PTP churn when tested
- Rolled back because it has no HTTP stream endpoint, and both v4l2loopback
  routes to get frames into a browser failed
- [ADR 0001](../decisions/0001-preview-architecture.md) decides to add an
  MJPEG endpoint to it and adopt it

## Camera capabilities

Measured facts for the EOS RP live in
[../reference/gphoto2-eos-rp.md](../reference/gphoto2-eos-rp.md) — including
the finding that focus control is relative and open-loop, with no absolute
positioning.

## To document

- Which backend the fork's PHP actually invokes, and where the config keys
  are read (`commands.*`)
- `cameracontrol.py`'s ZMQ message schema
- `cameracontrol-legacy.py` — what it is and whether it's dead code
