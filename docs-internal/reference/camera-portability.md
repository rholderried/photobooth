# Would this work with a different camera?

**Status:** `current` — 2026-08-14. Analysis, **not** measurement: only the
Canon EOS RP has been tested. Verify before trusting for another body.

## The single dependency

The MJPEG preview rests on one fact: **`capture_preview()` returns JPEG.**

That is likely portable. PTP liveview is a motion-JPEG feed on essentially
every camera, because it is how the body drives its own rear LCD. Canon,
Nikon, Sony and Fuji all work this way. Nothing else in
[../architecture/preview-architecture.md](../architecture/preview-architecture.md)
is camera-specific — the server just forwards bytes.

✅ **Guarded since 2026-08-14.** `mjpeg_server.py` validates the first frame
and refuses to serve a non-JPEG camera rather than emitting an undecodable
stream:

- Magic bytes (`ffd8`) are authoritative; libgphoto2's mime string is carried
  through only to make the log message diagnosable.
- On mismatch, `/stream.mjpg` and `/snapshot.jpg` return **503**, while
  `/healthz` keeps answering and reports `format_error` — that is how you
  diagnose it.
- The verdict is **sticky**: a later good frame does not revive the stream,
  because the camera has not changed.
- **Capture is deliberately unaffected.** A camera whose preview we cannot
  serve can still take pictures, and the message says so.

So on an incompatible camera you get this in the journal, instead of a
mysteriously blank preview:

```
Camera preview is not JPEG, so it cannot be served as MJPEG. libgphoto2
reports mime=image/webp; frame starts with 52494646 (expected ffd8...),
524 bytes. Preview is disabled; capture is unaffected.
```

Note the healthy case logs at INFO, and the service runs at ERROR level — so
silence is success. The observable signal is `format_error: null` in
`/healthz`.

Tested by `api/test_mjpeg_format.py` (13 checks). `MjpegServer` takes plain
bytes, so an incompatible camera is simulated by publishing non-JPEG bytes —
no second body needed:

```bash
cd /var/www/html/api && python3 test_mjpeg_format.py
```

## What is Canon-specific

| Thing | Portability |
|---|---|
| `manualfocusdrive` + `Near 1`…`Far 3` | ❌ **Canon EOS only.** Nikon exposes a similar action with different semantics; Sony differs; many cameras expose nothing. Needs per-model mapping. |
| `output=Off` before capture | ❌ Canon config key. Already tolerated via `try/except UnsupportedConfigException`. |
| `.CR2` → `.JPG` rewrite in `capture_image()` | ❌ **Upstream limitation.** Nikon `.NEF` / Sony `.ARW` would break RAW+JPEG capture. |
| Liveview existing at all | ⚠️ Many compacts and older DSLRs have none via gphoto2. |

## Test recipe for a new camera

Run **before** changing any config:

```bash
sudo systemctl stop cameracontrol.service

# 1. Does it expose liveview and focus at all?
gphoto2 --list-config | grep -iE 'focus|viewfinder'

# 2. Does preview return JPEG? (the load-bearing question)
python3 -c "import gphoto2 as gp; c=gp.Camera(); c.init(); \
            f=c.capture_preview(); print(f.get_mime_type()); c.exit()"

# 3. If focus exists, what are its actual values?
gphoto2 --get-config /main/actions/manualfocusdrive

sudo systemctl start cameracontrol.service
```

`image/jpeg` in step 2 means the preview path works unchanged. Step 3's
choices tell you what the focus UI can offer.

Record results in [gphoto2-eos-rp.md](gphoto2-eos-rp.md) style — one file per
body, measured not assumed.

## Why upstream used v4l2loopback

Not a mistake; it buys generality this fork does not need:

1. **`/dev/videoN` is *the* Linux camera interface.** Any application can
   consume it — browser, OBS, Zoom, ffmpeg. MJPEG-over-HTTP only serves
   HTTP clients.
2. **`getUserMedia()` is the standard browser camera API**, and is what makes
   `preview.camTakesPic` possible — the *browser* grabbing the still from the
   video stream rather than the camera. That cannot work without a real
   device node.
3. **Live chroma keying** applies ffmpeg `colorkey` filters to the preview.
   That needs decoded frames, so ffmpeg is in the path regardless; once it
   is, writing to v4l2loopback is a small extra step.

### The round trip we skip

Upstream's pipeline runs:

```
ffmpeg -i -  -vcodec rawvideo -pix_fmt yuv420p  -f v4l2 /dev/video9
```

It takes the camera's **JPEG** stream, decodes it to raw YUV420 for the
loopback device, after which the browser compresses it again to display it.
The frames arrive browser-ready and are converted away.

Serving them directly removes the transcode, the kernel module, and the
browser's camera-permission path in one step.

## What `--no-v4l2` costs

| Feature | Status |
|---|---|
| Live chroma-key preview | ❌ disabled (needs ffmpeg in the path) |
| `preview.camTakesPic` | ❌ disabled (needs `getUserMedia`) |
| Chroma keying on the *captured still* | ✅ unaffected — separate ffmpeg call |

Both disabled features are **off on this booth** (verified 2026-08-14:
`camTakesPic: false`, chromakeying not enabled), so nothing is lost today.

Not a dead end either: live chroma keying could be restored by reintroducing
ffmpeg and piping its output back as JPEG rather than to a device node.
