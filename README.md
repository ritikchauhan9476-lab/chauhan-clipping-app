# Chauhan Clipping - Android

The Chauhan Clipping video editor for Android phones: Simple Edit, AI Clipping, Timeline and Auto Short, with the
same FFmpeg edits and export settings as the desktop software.

**Download:** open the [Releases](../../releases) page and download the newest `ChauhanClipping-*.apk`, then open it
on your phone (allow "install unknown apps" once). The first time, allow "All files access" so the app can open your
videos and save clips to `Movies/ChauhanClipping`.

## How it is built
- `web/` - the app (HTML + JavaScript). The engine (`web/js/engine.js`, `dialogue.js`, `autoshort.js`, `colour.js`)
  builds the same FFmpeg commands as the desktop Python code.
- `android/` - a small Kotlin app that shows `web/` and runs FFmpeg on the phone.
- `scripts/build_ffmpeg.sh` - builds FFmpeg (x264 + MediaCodec) for Android with the NDK.
- `.github/workflows/build.yml` - builds FFmpeg and the APK, tests the engine and runs a self test on an emulator.

## Testing on a computer
```
node tests/engine.test.mjs              # engine tests with the computer's ffmpeg
node tests/devserver.mjs 8765 <media>   # the whole app in a desktop browser: http://localhost:8765
```
