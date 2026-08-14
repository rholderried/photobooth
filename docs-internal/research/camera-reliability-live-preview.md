---
title: Camera reliability + live preview research
date: 2026-08-08
tags: [photobooth, capture-bug, go2rtc, cameracontrol, v4l2loopback, resolved]
status: RESOLVED 2026-08-14 — superseded by ADR 0001
related-branch: feature/cameracontrol-mjpeg
---

# Photobooth: Camera reliability + live preview research

> ## ✅ Resolved 2026-08-14 — read this first
>
> **All three open items in this document are closed.** Both bugs are fixed
> *by construction* rather than patched: `cameracontrol.py` now holds one
> persistent PTP session for preview and capture, so there is no per-capture
> teardown left to orphan a process or wedge the USB controller.
>
> | Item | Outcome |
> |---|---|
> | Bug #1 — orphaned `gphoto2` per capture | Fixed — go2rtc left the camera path; **0 orphans** measured |
> | Bug #2 — PTP wedge under repeat captures | Fixed — no teardown; **0 timeouts** over repeated captures |
> | Live preview | Solved — MJPEG served straight from `cameracontrol.py` |
>
> The v4l2loopback investigation below was **abandoned, not completed**. It
> turned out to be unnecessary: `capture_preview()` already returns complete
> JPEG frames, so no virtual video device is involved at all.
> **Do not resume Approach A or B.**
>
> - Decision: [../decisions/0001-preview-architecture.md](../decisions/0001-preview-architecture.md)
> - Deployment: [../operations/deploy-mjpeg-preview.md](../operations/deploy-mjpeg-preview.md)
> - Camera facts: [../reference/gphoto2-eos-rp.md](../reference/gphoto2-eos-rp.md)
>
> Everything below is preserved as the record of how the diagnosis was
> reached. Its "current system state" and "suggested next steps" sections are
> **historical and no longer accurate.**

**Current deployed state (production branch):** rolled back to the original working
setup — `go2rtc` streaming directly from `gphoto2`, `preview.mode = 'url'`,
`commands.take_picture = 'capture %s'` (the bash wrapper at `/usr/local/bin/capture`).
Verified working end-to-end (capture + live preview both confirmed working).

Both bugs below are root-caused with known fixes, but **currently unapplied** —
rolled back today so the booth stays in a known-good state while live preview
research continues separately.

---

## Bug #1: go2rtc leaves an orphaned gphoto2 process on every capture

**Status:** root cause found, fix verified working, currently reverted (by choice).

### Symptom
`/usr/local/bin/capture` does `systemctl stop go2rtc.service` →
`gphoto2 --capture-image-and-download` → `systemctl start go2rtc.service`, on
*every single capture*. The `go2rtc.service` unit has `KillMode=process`, which
only signals the main `go2rtc` process, not its `gphoto2 --capture-movie --stdout`
child. Confirmed via `journalctl -u go2rtc`, on literally every capture:

```
systemd[1]: go2rtc.service: Unit process <pid> (gphoto2) remains running after unit stopped.
systemd[1]: go2rtc.service: Found left-over process <pid> (gphoto2) in control group while starting unit. Ignoring.
```

### Theorized connection to Bug #2
The leftover process normally dies quickly on its own (closed stdout pipe →
SIGPIPE) before the *next* real capture needs the camera. In near-total darkness,
the camera's autoexposure loop inside that orphaned process plausibly takes
longer to notice/exit, widening the race window where it's still holding the
USB/PTP connection exactly when the next real capture needs it.

### Fix (verified, then reverted for testing)
Change `KillMode=process` → `KillMode=control-group` in
`/etc/systemd/system/go2rtc.service`. Makes systemd kill the entire cgroup
(including orphaned children) on stop. Confirmed via `journalctl` this eliminates
the leak across multiple capture cycles — clean stops, no leftover processes.

**To reapply:**
```bash
sudo sed -i 's/^KillMode=process$/KillMode=control-group/' /etc/systemd/system/go2rtc.service
sudo systemctl daemon-reload
sudo systemctl restart go2rtc.service
```

---

## Bug #2: Camera USB/PTP wedge under sustained lens-cap/darkness stress

**Status:** root cause understood, reliability fix verified working, rolled back
today (depends on solving live preview first — see below).

### Symptom
After repeated captures with the lens cap on (simulating total darkness), the
camera stopped responding entirely — `gphoto2` output showed repeated
`PTP Timeout` / `"Timeout reading from or writing to the port"` errors, and even
the live preview stopped receiving frames. Only a physical power-cycle of the
camera recovered it.

### Root cause
The existing architecture forces a full PTP session teardown/rebuild on *every
single capture* (via the go2rtc stop/start dance above). Under sustained stress
(repeated forced interruptions + the camera's own autoexposure hunting with no
light source), this eventually leaves the camera's USB controller in a genuinely
wedged state — a hardware/firmware-level limitation, not a simple software race.

### Fix verified working
The Photobooth Project ships its own `api/cameracontrol.py` — a persistent daemon
(using `python-gphoto2` + ZMQ IPC on `tcp://localhost:5555`) that holds **one
continuous camera connection** for both preview and capture, instead of tearing
it down each time. Set up as a systemd service, this gave fast (~1s), clean
captures with zero PTP churn — verified via direct service calls and full
`capture.php` round trips.

Setup used (for reference, if resuming):
```ini
# /etc/systemd/system/cameracontrol.service
[Unit]
Description=cameracontrol.py persistent camera service (device_cam preview)
After=network.target

[Service]
Type=simple
User=www-data
WorkingDirectory=/var/www/html/api
ExecStartPre=+/usr/sbin/modprobe v4l2loopback video_nr=9 card_label="Gphoto2 Webcam" exclusive_caps=1
ExecStart=/usr/bin/python3 /var/www/html/api/cameracontrol.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```
Config: `preview.mode = 'device_cam'`, `commands.preview = 'python3 cameracontrol.py --bsm'`,
`commands.take_picture = 'python3 cameracontrol.py --capture-image-and-download %s'`.
`www-data` needs to be in the `video` group (`sudo gpasswd -a www-data video`,
then restart Apache to pick it up — no reboot needed for systemd-started services).

### Why it's not deployed right now
This architecture requires a live preview mechanism other than go2rtc's direct
camera stream, since only one process can hold the camera's PTP session at a
time. That led into the live-preview investigation below, which consumed the
rest of the session without resolving. Rolled back entirely today rather than
ship the reliability fix with no working preview.

---

## Live preview investigation — UNRESOLVED, this is what to pick up next

**Goal:** get a live camera view in the kiosk browser while `cameracontrol.py`
holds the persistent connection (which has no built-in HTTP stream endpoint like
go2rtc does).

### Approach A — `device_cam` mode: browser `getUserMedia()` against a v4l2loopback virtual camera

`cameracontrol.py` creates a virtual webcam device (`/dev/video9` via
`v4l2loopback`) and the kiosk browser accesses it like a local USB webcam via
`getUserMedia()`.

**Prerequisite gotcha:** `v4l2loopback-dkms` was installed at the package level
but had **no built module for the running kernel**
(`6.6.74+rpt-rpi-2712` — only built for `6.6.74+rpt-rpi-v8` and older, likely
left over from before this Pi was fully switched to the 2712 kernel variant).
Fixed via:
```bash
sudo dkms install v4l2loopback/0.12.7 -k 6.6.74+rpt-rpi-2712
```
Worth checking again if resuming — this can recur after kernel updates.

**Result: failed consistently, every variation tried:**

- Chromium: disabled PipeWire capture (`--disable-features=WebRtcPipeWireCapturer`,
  since Wayland Chromium often routes camera through PipeWire's desktop-portal
  API rather than direct V4L2) — no change.
- Firefox: disabled content sandboxing (`MOZ_DISABLE_CONTENT_SANDBOX=1`) — no change.
- Constraints changed from hard requirements to `ideal` hints for
  `width`/`height`/`facingMode` in `assets/js/preview.js` (a real, worthwhile fix
  regardless — `facingMode` is a mobile front/back-camera concept our virtual
  device can't satisfy at all as a hard constraint) — no change in the preview
  outcome, but **this fix is committed on the `feature/device-cam-preview`
  branch** and worth keeping whenever this is revisited.
- XWayland instead of native Wayland (dropped `--ozone-platform=wayland`) — no change.
- Temporarily hid the Pi 5's other 18 V4L2 pipeline devices (`video19`–`video35`,
  ISP/decoder nodes, not real cameras) in case they were interfering with
  enumeration — no change.
- Verified permissions correct for both `www-data` (the service) and `roman`
  (the actual browser/kiosk user, easy to overlook since the service and the
  browser run as different users) — both fine.
- Verified the device itself works perfectly via standard V4L2
  (`v4l2-ctl --device=/dev/video9 --stream-mmap --stream-count=1 --stream-to=...`
  captured a valid 921,600-byte frame, exactly matching expected 960×640 YU12) —
  device is healthy.
- **Full Pi reboot** — this fixed the identical symptom for multiple people in
  the upstream `v4l2loopback` GitHub issue tracker (see sources). Did not fix it
  for us.

**Consistent failure signature throughout:**
`navigator.mediaDevices.enumerateDevices()` returns zero `videoinput` entries;
`getUserMedia({video:true})` fails with `NotFoundError: Requested device not found`.
Confirmed via `fuser`/`lsof /dev/video9` that the browser never even attempts to
open the device — the failure is at the enumeration stage, before any
device-open attempt.

Web research confirms this is a long-standing, inconsistently-reproducible
compatibility gap between Chromium/Firefox and `v4l2loopback` devices, reported
by many people over several years, with no single reliable fix. See especially
[v4l2loopback issue #274](https://github.com/umlaeute/v4l2loopback/issues/274),
which includes someone with the *identical* gphoto2 → v4l2loopback →
Chromium/Electron setup, and wildly inconsistent results reported between users
and browser versions.

### Approach B — point go2rtc at `/dev/video9` instead of using getUserMedia

Rationale: sidesteps the entire browser camera-permission/enumeration problem,
since loading an HTTP video URL isn't a "camera access" request at all. Keep
`preview.mode = 'url'`, just repoint go2rtc's stream source:
```yaml
streams:
  photobooth: exec:ffmpeg -f v4l2 -i /dev/video9 -f mjpeg -#killsignal=2
```

**Result: failed for a different, new reason.** A second `ffmpeg` process
reading `/dev/video9` (whether via go2rtc's `exec:` producer or run standalone)
reliably captured **exactly one frame** (16,407 bytes, byte-identical across
repeated tests) and then stalled indefinitely — near-zero CPU usage, no further
frames — while `cameracontrol.py`'s own writer `ffmpeg` process continued
running normally the whole time. Tried explicit `-input_format`/`-video_size`/
`-framerate` to bypass ffmpeg's auto-negotiation — identical result.

**Working theory (untested):** possible incompatibility between v4l2loopback's
"Read/Write" I/O mode (used by the writer, via ffmpeg's `-f v4l2` output muxer)
and a second reader joining later using streaming/mmap I/O. Not confirmed —
would need either kernel-module-level investigation, or a test reader using
matching `read()`-based I/O instead of ffmpeg's default mmap capture.

### Suggested next steps

1. Test Approach B's stall theory directly — write a minimal Python script doing
   a plain blocking `read()` loop on `/dev/video9` (bypassing ffmpeg's
   mmap-based capture) to see if that unblocks continuous frames.
2. Check the Photobooth Project's own Discord/GitHub for how other users
   actually got `cameracontrol.py` + `device_cam` mode working in practice —
   their own docs describe it as a working setup, so there's likely a
   version-specific or config detail not yet identified.
3. Consider whether an older/specific browser version (matching what worked for
   others in the v4l2loopback GitHub thread) could be pinned just for the kiosk.
4. Independent of preview: reapply the Bug #1 `KillMode=control-group` fix — it's
   unrelated to the preview problem and safe to do any time.

### Sources
- [Chromium cannot detect v4l2loopback device using exclusive_caps=1 · Issue #274 · v4l2loopback/v4l2loopback](https://github.com/umlaeute/v4l2loopback/issues/274)
- [Video not starting with Firefox, camera not showing on cameras list on Chrome · Issue #5 · lucasw/image_to_v4l2loopback](https://github.com/lucasw/image_to_v4l2loopback/issues/5)
- [V4l2loopback device not opening in chrome or firefox - Jetson Nano - NVIDIA Developer Forums](https://forums.developer.nvidia.com/t/v4l2loopback-device-not-opening-in-chrome-or-firefox/167864)

---

## Current system state reference

- Branch: `production` (fully reverted). `feature/device-cam-preview` branch
  preserved with the `getUserMedia` constraints fix commit, for resuming
  Approach A.
- `go2rtc`: streaming directly from `gphoto2` (original architecture),
  `KillMode=process` (Bug #1 unfixed).
- `cameracontrol.service`: stopped and disabled (won't start on boot).
- `v4l2loopback`: unloaded.
- Firefox kiosk profile: still exists at `~/.mozilla/firefox/photobooth-kiosk`
  (unused, autostart line commented out) — harmless to leave or delete.
- Chromium `--remote-debugging-port=9222`: kept (unrelated, generally useful
  addition from earlier in this session — forward the port and open
  `http://localhost:9222/json/list` to find the live inspector URL).
- `www-data` in `video` group: kept (harmless, no longer strictly needed).
