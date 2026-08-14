# Untracked system state — everything outside git

**Status:** `current` — audited 2026-08-14
**Purpose:** the booth depends on system configuration that is **not** in this
repo. None of it survives a fresh Pi image. This is the complete inventory.

> **How to use this file:** after a reimage, work top to bottom. Anything
> marked ⚠️ is load-bearing — the booth does not function without it.

## Quick inventory

| # | Item | Location | Status |
|---|---|---|---|
| 1 | Apache vhost hardening | `/etc/apache2/sites-available/000-default.conf` | ⚠️ security |
| 2 | `www-data` sudo rule | `/etc/sudoers.d/` | ⚠️ capture breaks without it |
| 3 | Capture wrapper | `/usr/local/bin/capture` | ⚠️ |
| 4 | go2rtc binary + config + unit | `/usr/local/bin/go2rtc`, `/etc/go2rtc.yaml`, `/etc/systemd/system/go2rtc.service` | ⚠️ preview |
| 5 | cameracontrol unit | `/etc/systemd/system/cameracontrol.service` | disabled |
| 6 | Kiosk autostart | `~/.config/labwc/autostart` | ⚠️ |
| 7 | Compositor touch config | `~/.config/labwc/rc.xml` | ⚠️ touch scroll |
| 8 | Group memberships | `www-data` in `video`,`plugdev`,`lp`,`lpadmin` | ⚠️ camera access |
| 9 | DocumentRoot setgid | `/var/www/html` mode `drwxrwsr-x` | ⚠️ write access |
| 10 | v4l2loopback DKMS | per-kernel builds | not currently used |
| 11 | Disabled services | `nginx` (disabled), `hostapd` (**masked**) | see §11 |
| 12 | PHP 8.4 + `display_errors=Off` | `/etc/php/8.4/apache2/php.ini` | ⚠️ see §12 |

---

## 1. Apache vhost hardening

Full detail and rationale: [web-exposure-hardening.md](web-exposure-hardening.md).
Without it, `.git/`, `CLAUDE.md`, `config/`, `var/log/` and this entire
`docs-internal/` tree are downloadable by anyone on the WiFi.

## 2. `www-data` sudo rule ⚠️

```
www-data ALL=(ALL) NOPASSWD: /usr/bin/systemctl start go2rtc.service, /usr/bin/systemctl stop go2rtc.service
```

Required by `/usr/local/bin/capture` (§3), which is run by the web server.
**Without this rule every capture fails**, because the wrapper cannot stop
go2rtc to free the camera.

`roman` additionally has `NOPASSWD: ALL`.

> Note: this rule becomes unnecessary under
> [ADR 0001](../decisions/0001-preview-architecture.md) — a persistent
> `cameracontrol.py` never stops go2rtc. Removing it then is a small
> privilege reduction worth taking.

## 3. `/usr/local/bin/capture` ⚠️

`root:root 0755`. The `commands.take_picture` config key points at it
(`capture %s`).

```bash
#!/bin/bash
if [[ $# -eq 1 ]]; then
    args="--set-config output=Off --capture-image-and-download --filename=$1"
elif [[ $# -gt 1 ]]; then
    args="$@"
fi
if systemctl cat go2rtc.service >/dev/null; then HAS_GO2RTC=1; fi
[[ -n "$HAS_GO2RTC" ]] && sudo systemctl stop go2rtc.service
gphoto2 $args
[[ -n "$HAS_GO2RTC" ]] && sudo systemctl start go2rtc.service
```

(Help text elided; run `capture --help`.) This stop/capture/start dance is the
source of both bugs in
[../research/camera-reliability-live-preview.md](../research/camera-reliability-live-preview.md).
`--set-config output=Off` disables the camera's own display output before
capture.

## 4. go2rtc ⚠️

Binary `/usr/local/bin/go2rtc`; unit enabled, runs as `www-data`:

```ini
ExecStart=/usr/local/bin/go2rtc -config /etc/go2rtc.yaml
KillMode=process        # ← Bug #1: leaves orphaned gphoto2 children
```

`/etc/go2rtc.yaml`:

```yaml
---
streams:
  photobooth: exec:gphoto2 --capture-movie --stdout#killsignal=2
log:
  exec: trace
```

**`KillMode=process` is the unfixed Bug #1.** The fix
(`KillMode=control-group`) is verified but deliberately unapplied. go2rtc
spawns its `gphoto2` child **on demand** when a client connects, so an idle
go2rtc still leaves the camera free.

## 5. `cameracontrol.service`

Present but **disabled** (won't start at boot). Unit contents are recorded in
the research doc. This is the service
[ADR 0001](../decisions/0001-preview-architecture.md) plans to adopt.

## 6. Kiosk autostart ⚠️

`~/.config/labwc/autostart` — user dotfile, owned by `roman`:

```
chromium --kiosk --remote-debugging-port=9222 --disable-features=Translate \
  --noerrdialogs --disable-infobars --no-first-run --ozone-platform=wayland \
  --touch-events=enabled --start-maximized http://localhost
```

Notes:
- **Chromium, not Firefox.** A commented-out Firefox line remains below it.
- `--remote-debugging-port=9222` binds loopback only; forward it over SSH and
  open `http://localhost:9222/json/list` for DevTools.
- **The kiosk requests `http://localhost`** — i.e. from `127.0.0.1`. This is
  what makes the `protect.localhost_*` access split work; see
  [../architecture/auth-and-access.md](../architecture/auth-and-access.md).

## 7. Compositor touch config ⚠️

`~/.config/labwc/rc.xml`:

```xml
<openbox_config xmlns="http://openbox.org/3.4/rc">
<touch deviceName="ILITEK ILITEK-TP" mapToOutput="HDMI-A-2" mouseEmulation="no"/>
</openbox_config>
```

`mouseEmulation="no"` is **half of the gallery touch-scroll fix** — with
`"yes"`, labwc converts all touch into synthetic mouse events before Chromium
ever sees `wl_touch`, and no CSS can compensate. The other half is the
`touch-action` CSS, which *is* in git. Backup: `rc.xml.bak-20260809-124515`.

Reload without restarting the session:

```bash
kill -HUP $(pgrep -x labwc)
```

Touchscreen device nodes shift across reboots — re-check with
`libinput list-devices` rather than trusting a hardcoded `/dev/input/eventN`.

## 8. Group memberships ⚠️

```
www-data : www-data lp video plugdev lpadmin
roman    : ... sudo www-data video plugdev input render lpadmin gpio i2c spi ...
```

`video`/`plugdev` are what let the web server talk to the camera. `lp`/
`lpadmin` cover printing. Reapply with `sudo gpasswd -a www-data video`, then
restart Apache (no reboot needed for systemd-started services).

## 9. DocumentRoot ownership ⚠️

```
drwxrwsr-x  www-data:www-data  /var/www/html
```

Setgid bit (`s`) on all directories, so files created by either `roman` or the
web server stay group-writable. `roman` is in the `www-data` group. Losing this
means editing the live site as `roman` starts failing with permission errors.

## 10. v4l2loopback DKMS

Built for four kernels including the running `6.6.74+rpt-rpi-2712`. Currently
**unloaded and unused**. DKMS builds do not automatically follow a kernel
upgrade to a new variant — this previously broke silently. Rebuild with:

```bash
sudo dkms install v4l2loopback/0.12.7 -k $(uname -r)
```

[ADR 0001](../decisions/0001-preview-architecture.md) removes the dependency
on this entirely.

## 11. Deliberately disabled services

- **`nginx`** — `disabled`, inactive. Conflicted with Apache for port 80 at
  boot. Do not re-enable without moving Apache off port 80 first.
- **`hostapd`** — `masked`, inactive, **and correctly so**. A leftover config
  exists at `/etc/hostapd/hostapd.conf` (SSID `retro_pbx`, WPA2, wlan0), but
  the Pi does **not** provide the access point: the booth contains its own
  router which does that, with the Pi wired to it over `eth0`. `dnsmasq` is
  disabled for the same reason. `wlan0` is DOWN and unused.

  ✅ **Do not "fix" this.** Unmasking hostapd would create a second, competing
  AP. Topology: [network-topology.md](network-topology.md).

## 12. PHP ⚠️

PHP **8.4.23** with mod_php (Apache module, not FPM). Upgraded from 8.3 to
satisfy upstream's `composer.json` after the 2026-08-09 merge.

```
display_errors    = Off      ← must stay Off
session.save_path = /var/lib/php/sessions    (outside DocumentRoot — correct)
upload_max_filesize = 2M
```

**`display_errors=Off` is load-bearing.** PHP writes notices into the response
*body*; with it on, a deprecation notice inside a JSON endpoint corrupts the
payload and breaks `JSON.parse` client-side. That was the root cause of the
collage-assembly bug. `lib/boot.php` also enforces this in code — verify both
if that file is ever touched.

`mod_access_compat` is loaded, so Apache 2.2-style directives would work if
`.htaccess` were ever enabled — but see
[web-exposure-hardening.md](web-exposure-hardening.md) for why they are not.

---

## Not covered here

The printer pipeline (Pi → CUPS → SSH → Windows → DNP DS-RX1), colour
management, and router setup. Separate, mostly-solved subsystems — documented
elsewhere or not yet.
