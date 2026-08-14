# Deploying the MJPEG preview pipeline

**Status:** `current` — validated end-to-end 2026-08-14, **not yet deployed**
**Code:** already merged to `production` (`api/mjpeg_server.py` + patched
`api/cameracontrol.py`). Backwards-compatible — the new flags default off, so
merging changed nothing on its own.

Implements [ADR 0001](../decisions/0001-preview-architecture.md). This switches
the camera pipeline from "go2rtc streams, and every capture tears the PTP
session down" to "one process owns the camera for both preview and capture".

## What this fixes

- **Bug #1** (orphaned `gphoto2` on every capture) — go2rtc leaves the camera
  path entirely, so there is nothing to orphan.
- **Bug #2** (USB/PTP wedge under repeated captures) — there is no per-capture
  teardown left to wedge.
- Unlocks focus control during preview, which the customer config screen needs.

## ⚠️ These four steps are all-or-nothing

Doing the config half without the service half leaves a **booth that breaks on
reboot**: `go2rtc` is still enabled and would auto-start and grab the camera,
while `preview.url` points at a port with nothing listening. Apply all four,
or none.

### 1. Install the service unit

```bash
sudo tee /etc/systemd/system/cameracontrol.service > /dev/null <<'EOF'
[Unit]
Description=cameracontrol.py persistent camera service (MJPEG preview + capture)
Documentation=file:///var/www/html/docs-internal/decisions/0001-preview-architecture.md
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/html/api
# --no-v4l2: MJPEG replaces the v4l2loopback path entirely, so neither ffmpeg
# nor the virtual device is needed. See ADR 0001.
ExecStart=/usr/bin/python3 /var/www/html/api/cameracontrol.py --mjpeg-port 8081 --no-v4l2
Restart=on-failure
RestartSec=5
# One process owns the camera's PTP session; leave nothing behind.
KillMode=control-group

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
```

### 2. Take go2rtc out of the camera path

```bash
sudo systemctl stop go2rtc.service
sudo systemctl disable go2rtc.service     # must be disabled, not just stopped
```

`disable` is the load-bearing part — otherwise it returns on the next boot and
fights for the camera.

### 3. Start cameracontrol

```bash
sudo systemctl enable --now cameracontrol.service
sleep 8
curl -s http://localhost:8081/healthz      # expect has_frame: true
```

### 4. Point the config at it

In `config/my.config.inc.php`:

```php
'preview' => [
    'url' => 'http://localhost:8081/stream.mjpg',   // was localhost:1984/api/stream.mjpeg?src=photobooth
],
'commands' => [
    'take_picture' => 'python3 cameracontrol.py --no-v4l2 --capture-image-and-download %s',
                                                     // was 'capture %s'
],
```

`preview.mode` stays `'url'`. No frontend change is needed — `preview.url`
already pointed at an MJPEG stream.

> **Why the bare `python3 cameracontrol.py`?** PHP runs the capture command
> with its working directory set to `api/`
> (`src/PhotoboothCapture.php:115-128`), so the relative path resolves. The
> `--no-v4l2` flag is **required**: without it the CLI tries to autodetect or
> `modprobe` a v4l2loopback device before sending its ZMQ message, and fails
> as `www-data`.

Then reload the kiosk (`Ctrl+R`, or reboot).

## Verification

```bash
# preview serving
curl -s http://localhost:8081/healthz
# reachable from a phone on the LAN (use the Pi's address, not localhost)
curl -s -o /dev/null -w '%{http_code}\n' http://192.168.8.2:8081/snapshot.jpg
# after a few captures: no orphans, camera still enumerated
pgrep -c gphoto2        # expect 0
lsusb | grep -c Canon   # expect 1
```

Measured on 2026-08-14 with this exact setup:

| Check | Result |
|---|---|
| Captures via the real UI | 6/6 succeeded, full-res 4521×2944 JPEGs |
| Preview during/after capture | uninterrupted, steady ~11.8 fps |
| `gphoto2` orphan processes | **0** throughout (was: one per capture) |
| PTP timeouts / errors in log | **0** |
| Concurrent clients | 2 clients, 119 frames each, no degradation |

## Rollback

```bash
sudo systemctl disable --now cameracontrol.service
sudo systemctl enable --now go2rtc.service
```

…and revert the two config values in step 4. Verify with
`curl 'http://localhost:1984/api/frame.jpeg?src=photobooth'` returning a JPEG.

## Known gaps before an event

- **Bandwidth:** ~148 KB/frame → ~17 Mbit/s per client, 33.5 Mbit/s with two.
  Fine over ethernet; heavy for phones over WiFi. Downscaling phone clients is
  the obvious optimisation (needs PIL or ffmpeg; deliberately not in the spike).
- **`--mjpeg-bind` defaults to `0.0.0.0`.** That is an unauthenticated live
  video feed of the booth to anyone on the LAN. Land the access control in
  [ADR 0002](../decisions/0002-customer-config-access-control.md) alongside
  this, or bind to `127.0.0.1` until then.
- **Not tested:** collage/video capture paths, and rendering in an actual phone
  browser (the LAN network path is verified, the phone rendering is not).
- Add `cameracontrol.service` to
  [untracked-system-state.md](untracked-system-state.md) once deployed — the
  unit is not in git.
