# Capture pipeline

**Status:** `stub` — not yet written (2026-08-14)

Intended contents: the full path from a touchscreen tap to a JPEG on disk.

## Known waypoints

- `api/capture.php` — the capture endpoint, CSRF-protected since the
  2026-08-09 merge (verified end-to-end against a real camera capture)
- `src/PhotoboothCapture.php`
- `commands.take_picture` config key — currently `capture %s`, i.e. the bash
  wrapper `/usr/local/bin/capture`
- Output lands in `data/images/`, thumbnails in `data/thumbs/`

## Related

- Backend mechanics and the PTP session constraint:
  [camera-backends.md](camera-backends.md)
- Two root-caused, currently-unapplied reliability bugs:
  [../research/camera-reliability-live-preview.md](../research/camera-reliability-live-preview.md)

## To document

- Frontend trigger path (`assets/js/core.js`) → API call → response handling
- CSRF token flow for `api/capture.php`
- Countdown and flash timing, and where they're configured
- Post-capture processing: filters, collage, print queue
