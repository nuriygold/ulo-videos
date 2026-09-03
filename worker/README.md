# Cloud render worker

The worker is deliberately provider-neutral. The queue message contains only:

```json
{"renderJobId":"rj_123"}
```

The worker retrieves the immutable `spec_snapshot`, resolves asset IDs to
short-lived object-storage URLs, downloads the source video, runs the
deterministic FFmpeg pass in `runner.py`, verifies that `output.mp4` exists,
uploads it, and reports the output asset ID. Blender, Piper, and Rhubarb are
additional stages that must feed their outputs into the final FFmpeg assembly
before their job states are marked complete.
