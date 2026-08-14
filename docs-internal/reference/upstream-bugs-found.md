# Upstream bugs found in this fork's code

**Status:** `current` — 2026-08-14

Bugs that belong to upstream `PhotoboothProject/photobooth`, not to our
changes. Recorded so we don't re-diagnose them, and as candidates for
upstream PRs.

---

## 1. `api/cameracontrol.py` is unimportable — stray statement at module level

**Found:** 2026-08-14 · **Fixed in:** `feature/cameracontrol-mjpeg`

The file ends with a bare name expression after the entry-point guard:

```python
if __name__ == "__main__":
    sys.exit(main())
create_ffmpeg_webcam_service      # ← no such name exists
```

Harmless when run as a script — `sys.exit()` raises `SystemExit`, so the line
is never reached. But it executes at module level on **import**:

```
$ python3 -c "import cameracontrol"
NameError: name 'create_ffmpeg_webcam_service' is not defined
```

So the module cannot be imported, unit-tested, or reused. Looks like an
editing accident (a leftover from a removed helper).

**Fix:** delete the line.

---

## 2. Config sent over ZMQ is stored but never applied

**Found:** 2026-08-14 · **Not fixed** — we work around it

In `CameraControl.handle_message()`:

```python
if args.config is not None and args.config != self.args.config:
    self.args.config = args.config
    self.connect_to_camera()          # ← only reconnects
    video_settings_were_updated = True
    log.info("Applied updated config")   # ← misleading
```

`connect_to_camera()` just does `gp.Camera()` + `init()`. The method that
actually pushes settings to the camera is `apply_configuration()`, which is
only ever called from `__init__`.

So `--set-config foo=bar` against an **already-running** service updates
`self.args.config` and reconnects, but never calls `set_config()` — the
setting silently does not take effect, while the log claims it did. It works
only when it happens to be passed on the first (service-starting) invocation.

**Consequence for us:** this is why our focus support does not route through
`--set-config manualfocusdrive=…`. We added an explicit `--focus` argument
handled directly in `handle_message()`, which calls `set_config()` itself.

**Likely fix upstream:** call `self.apply_configuration()` after
`connect_to_camera()` in that branch. Not attempted here — it changes
behaviour for chroma/video paths we don't currently exercise, and we don't
want an unverified change to shared code in the middle of a feature.
