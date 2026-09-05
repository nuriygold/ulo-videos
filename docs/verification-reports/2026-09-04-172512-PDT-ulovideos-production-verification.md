# ulo-videos production verification report

Date/time: 2026-09-04 17:25:12 PDT
Repo path: `/Users/claw/ulo-videos/.claude/worktrees/character-import-review-fixtures`
Production URL: `https://ulo-videos.vercel.app`

## Summary

`ulo-videos` is deployed to Vercel production and is ready for fallback-flow testing under the agreed constraints:

- Production remains on `vercel_fallback`.
- Production is not routed to the synchronous external worker.
- `/api/setup-status` is reachable.
- Fallback capabilities are correctly reported.
- PR #2 is merged and its amd64 worker fixture check passed.
- The PR #3 voice/lip-sync reference-label fix is merged and deployed to production.

Character upload remains unavailable in production because fallback capability reporting is intentionally `character: false` and `characterFormats: []`.

## GitHub / PR verification

### PR #2

- PR: `https://github.com/nuriygold/ulo-videos/pull/2`
- Title: `Add character import formats and worker fixtures`
- State: closed
- Merged: true
- Merged at: 2026-09-04T22:00:22Z
- Head branch: `character-import-formats`
- Head SHA: `3de898a760ab9cbe5099cd75390824edabd0c997`

### PR #2 checks

- Check: `amd64 Blender worker fixtures`
- Status: completed
- Conclusion: success
- Job URL: `https://github.com/nuriygold/ulo-videos/actions/runs/33921199995/job/101179680365`
- Started: 2026-09-04T21:27:45Z
- Completed: 2026-09-04T21:31:36Z

## Latest intended main commit

Remote `main` at verification time:

```text
4ef77adb37fcae6926ee2358dc65e153c0c8f1f4 refs/heads/main
```

This includes the PR #3 fix:

```text
Keep voice and lip-sync references editable
```

## Vercel production deployment verification

Latest Vercel production deployment for project `ulo-videos`:

- Deployment ID: `dpl_ApYQcsY5ENJ22LTAySMiqemHQ5tT`
- Project: `ulo-videos`
- Project ID: `prj_AvE46r5lcTq7Zez0LIVG9H4AUn5n`
- Target: production
- State: READY
- Ready substate: PROMOTED
- URL: `https://ulo-videos-jxhxe90hi-nuriys-projects.vercel.app`
- Production alias: `https://ulo-videos.vercel.app`
- Commit SHA: `4ef77adb37fcae6926ee2358dc65e153c0c8f1f4`
- Commit message: `Keep voice and lip-sync references editable`
- Inspector: `https://vercel.com/nuriys-projects/ulo-videos/ApYQcsY5ENJ22LTAySMiqemHQ5tT`

## `/api/setup-status` verification

Production request:

```text
GET https://ulo-videos.vercel.app/api/setup-status
```

Observed response:

```json
{
  "ready": true,
  "services": {
    "blob": true,
    "supabase": true,
    "queue": true,
    "worker": true
  },
  "renderer": {
    "mode": "vercel_fallback",
    "reachable": true,
    "capabilities": {
      "freezeResume": true,
      "logo": true,
      "captions": true,
      "character": false,
      "sourceAudio": false,
      "speech": false,
      "lipSync": false,
      "characterFormats": []
    }
  }
}
```

## Capability interpretation

Ready for testing:

- Source video upload
- Interruption timestamp
- Freeze/resume fallback rendering path
- Logo metadata/upload flow
- Captions metadata/rendering path
- Voice reference field as metadata
- Lip-sync reference field as metadata

Not available in current production fallback:

- Character upload/rendering
- Source audio preservation
- Speech synthesis
- Lip-sync application
- Character formats `.blend`, `.gltf`, `.glb`, `.fbx`

This is expected while production remains on `vercel_fallback` with `characterFormats: []`.

## Local pre-merge verification for PR #3

Before merging and deploying the voice/lip-sync reference-label fix, the following commands were run successfully:

```text
npm test -- tests/web-instructions.test.ts tests/web-workspace-client.test.ts tests/web-job-service.test.ts
npx tsc --noEmit
npm run build
git diff --check
```

Results:

- Targeted test run: 60 passing, 0 failing.
- TypeScript typecheck: passed.
- Next.js production build: passed.
- Diff whitespace check: passed.

PR #3:

- URL: `https://github.com/nuriygold/ulo-videos/pull/3`
- Commit before squash merge: `9b9731676b1c5b51342e73f99d2cb56954ae89f5`
- Squash merge commit on `main`: `4ef77adb37fcae6926ee2358dc65e153c0c8f1f4`

## Production render queue observation

User-observed render submission failure after deployment:

```text
render queue rejected the job (502): {"error": "ght (c) 2000-2024 the FFmpeg developers\n built with gcc 8 (Debian 8.3.0-6)\n configuration: --enable-gpl --enable-version3 --enable-static --disable-debug --disable-ffplay --disable-indev=sndio --disable-outdev=sndio --cc=gcc --enable-fontconfig --enable-frei0r --enable-gnutls --enable-gmp --enable-libgme --enable-gray --enable-libaom --enable-libfribidi --enable-libass --enable-libvmaf --enable-libfreetype --enable-libmp3lame --enable-libopencore-amrnb --enable-libopencore-amrwb --enable-libopenjpeg --enable-librubberband --enable-libsoxr --enable-libspeex --enable-libsrt --enable-libvorbis --enable-libopus --enable-libtheora --enable-libvidstab --enable-libvo-amrwbenc --enable-libvpx --enable-libwebp --enable-libx264 --enable-libx265 --enable-libxml2 --enable-libdav1d --enable-libxvid --enable-libzvbi --enable-libzimg\n libavutil 59. 8.100 / 59. 8.100\n libavcodec 61. 3.100 / 61. 3.100\n libavformat 61. 1.100 / 61. 1.100\n libavdevice 61. 1.100"
```

Interpretation:

- The production queue endpoint is reachable, but the fallback POST render path can still fail with HTTP 502.
- The error body begins with FFmpeg banner output instead of a structured render result.
- This does not change `/api/setup-status`; production still reports fallback readiness and fallback capabilities.
- This is a fallback render-completion blocker, not evidence that production is routed to the external worker.

## Final readiness statement

By the explicit readiness criteria:

- Latest intended `main` code is deployed to Vercel production: yes.
- Production remains on `vercel_fallback`: yes.
- `/api/setup-status` is reachable: yes.
- Fallback capabilities are reported: yes.

Therefore, production is ready for UI/fallback-capability testing at `https://ulo-videos.vercel.app`.

Known limitation: end-to-end MP4 render completion through the Vercel fallback remains blocked by the render queue 502/FFmpeg-banner error above.
