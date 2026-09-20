# Logitech USB camera on the Pi 4B

The primary sensor after the 2026-09-19 pivot.
Owned by `vision/`, which will not read a frame from it without a verified attestation from `shutter/` that the shield is clear.

Read `vision/CLAUDE.md` for the contract. This guide is the how.

## Check it enumerates

```sh
lsusb                       # a Logitech line should appear
v4l2-ctl --list-devices      # /dev/video0, usually with a second node beside it
v4l2-ctl -d /dev/video0 --list-formats-ext
```

`--list-formats-ext` is the one that matters. It tells you whether the camera offers **MJPG** as well as YUYV.

**Use MJPG.** A YUYV stream at 720p is roughly 27MB/sec over USB 2.0 and the Pi will drop frames or fail to open the stream at all, usually with an unhelpful "no space left on device" from V4L2, which means USB bandwidth rather than disk.

## Fix the exposure. This is not optional

Auto-exposure hunts, and a hunting camera produces frames that are bright, then dark, then bright, one second apart.
Gemini describes each of them faithfully, so the narration contradicts itself on a live 911 call.

Set it once, at the position and lighting the demo will use:

```sh
v4l2-ctl -d /dev/video0 -c auto_exposure=1            # 1 = manual on most UVC cams
v4l2-ctl -d /dev/video0 -c exposure_time_absolute=300  # tune at the shoot
v4l2-ctl -d /dev/video0 -c white_balance_automatic=0
v4l2-ctl -d /dev/video0 -c white_balance_temperature=4600
v4l2-ctl -d /dev/video0 --list-ctrls                   # confirm they stuck
```

Control names differ across UVC firmware. If a name is rejected, `--list-ctrls` shows what this camera actually calls it.

**These do not persist across replug or reboot.** Put them in the `vision` startup path, not in someone's shell history.

## Settings for the two paths

`vision` runs two consumers off one camera. They want different things, and the camera can only be opened once.

| Path | Wants | Setting |
|---|---|---|
| Gemini Live narration | ~1 fps, modest resolution, small payload | Sample from the shared stream, resize to 768px on the long edge, JPEG q80 |
| Segment recording | Continuous, as good as the Pi can sustain | 1280x720 MJPG at 15fps, remuxed to H.264 in 10s segments |

Open the device **once**, in `vision`, and fan out in software.
Two processes opening `/dev/video0` is the classic "device busy" failure and it will happen the first time someone runs the recorder and the narrator separately.

A working ffmpeg segment command, for reference and for the fallback path:

```sh
ffmpeg -f v4l2 -input_format mjpeg -video_size 1280x720 -framerate 15 -i /dev/video0 \
  -c:v h264_v4l2m2m -b:v 2M \
  -f segment -segment_time 10 -reset_timestamps 1 \
  incident/<id>/seg-%04d.mp4
```

`h264_v4l2m2m` is the Pi's hardware encoder. If it is unavailable, `-c:v copy` into `.mkv` keeps the MJPG frames without re-encoding and costs disk rather than CPU. Do not fall back to `libx264` on a Pi 4B; it will not keep up and it will starve the CSI capture running on the same machine.

## Power and USB budget

The Pi is now running the WiFi chip in monitor mode, a USB ethernet adapter, and a USB camera, with a servo on the GPIO header.

- Use the **3A USB-C supply**. Not a laptop port, not a router port
- The camera and the ethernet adapter share USB bandwidth. If frames drop, move the camera to a USB 3.0 port (the blue ones) and leave ethernet on USB 2.0
- **The servo must be on its own supply.** See `servo-sg92r.md`. A servo brownout presents as the camera dying, which will send you debugging the wrong thing

Check for undervoltage after any hardware change:

```sh
vcgencmd get_throttled     # 0x0 is what you want; anything else means power
dmesg | grep -i "under-voltage"
```

## Placement, and the conflict with CSI geometry

These two constraints pull in different directions and the conflict is easy to miss.

- **CSI geometry** wants the router and the Pi on **opposite sides** of the sensed space, with people walking between them
- **The camera** wants to face the **entry point**, with the person's face reasonably lit and reasonably close

They are reconcilable because **the camera does not have to be near the Pi**. It is a USB cable.

Run the camera on a 3m USB extension to wherever it needs to be, and leave the Pi where CSI wants it.
Check the extension actually carries data before the shoot; cheap ones are charge-only and fail with no device enumerating at all.

## Verify the whole path

```sh
# One frame, is there an image at all
ffmpeg -f v4l2 -i /dev/video0 -frames:v 1 /tmp/test.jpg && ls -l /tmp/test.jpg

# Is the shield actually blocking it
# with the shutter closed:
ffmpeg -f v4l2 -i /dev/video0 -frames:v 1 -vf "signalstats,metadata=print:key=lavfi.signalstats.YAVG" -f null - 2>&1 | tail -3
# YAVG should be near zero. If it is not, the shield is not covering the lens
```

**Run that second check every time the mount is touched.** A shield that does not fully cover is the one failure in this project that looks like success and invalidates the central claim.

## The ways this fails quietly

| Symptom | Cause |
|---|---|
| Narration contradicts itself between frames | Auto-exposure. Fix the controls |
| Gemini confidently describes a dark room | The luminance guard in `vision` is not running. It must refuse below threshold, not describe |
| Stream opens then dies after a few seconds | USB bandwidth. Switch to MJPG, or move to a USB 3.0 port |
| Camera vanishes when the shutter moves | Servo brownout. Power, not USB |
| Recording has gaps | Pi CPU saturated, usually by `libx264`. Use the hardware encoder |
| Everything works on the bench, nothing works at the house | Extension cable is charge-only, or the camera renumerated to `/dev/video2`. Match by USB path, not by index |
