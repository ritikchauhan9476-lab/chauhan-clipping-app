#!/usr/bin/env bash
# Builds the ffmpeg and ffprobe programs for Android with the NDK: libx264 (the same encoder as the desktop
# software), MediaCodec (the phone's hardware encoder) and every built-in filter the app uses.
# Usage: scripts/build_ffmpeg.sh arm64-v8a|x86_64     Output: build-ffmpeg/out/<abi>/libffmpeg.so, libffprobe.so
set -euo pipefail
ABI="${1:?abi}"
API="${API:-26}"
FFMPEG_TAG="${FFMPEG_TAG:-n7.1}"
NDK="${ANDROID_NDK_HOME:-${ANDROID_NDK_LATEST_HOME:-}}"
[ -d "$NDK" ] || { echo "Android NDK not found (set ANDROID_NDK_HOME)"; exit 1; }
TC="$NDK/toolchains/llvm/prebuilt/linux-x86_64"
ROOT="$(pwd)/build-ffmpeg"
SRC="$ROOT/src"; PREFIX="$ROOT/prefix/$ABI"; OUT="$ROOT/out/$ABI"
mkdir -p "$SRC" "$PREFIX" "$OUT"
JOBS="$(nproc)"

case "$ABI" in
  arm64-v8a) TRIPLE=aarch64-linux-android; ARCH=aarch64; CPU=armv8-a; X264_EXTRA=""; FF_EXTRA="--cpu=$CPU --enable-neon --enable-asm" ;;
  x86_64)    TRIPLE=x86_64-linux-android;  ARCH=x86_64;  X264_EXTRA="--disable-asm"; FF_EXTRA="--disable-asm" ;;
  *) echo "unknown abi $ABI"; exit 1 ;;
esac
CC="$TC/bin/${TRIPLE}${API}-clang"
CXX="$TC/bin/${TRIPLE}${API}-clang++"
export AR="$TC/bin/llvm-ar" RANLIB="$TC/bin/llvm-ranlib" STRIP="$TC/bin/llvm-strip" NM="$TC/bin/llvm-nm"

echo "== sources"
cd "$SRC"
if [ ! -d x264 ]; then
  git clone --depth 1 --branch stable https://code.videolan.org/videolan/x264.git x264 \
    || git clone --depth 1 --branch stable https://github.com/mirror/x264.git x264
fi
if [ ! -d ffmpeg ]; then
  git clone --depth 1 --branch "$FFMPEG_TAG" https://github.com/FFmpeg/FFmpeg.git ffmpeg
fi

echo "== x264 ($ABI)"
rm -rf "$SRC/x264-$ABI" && cp -r "$SRC/x264" "$SRC/x264-$ABI" && cd "$SRC/x264-$ABI"
CC="$CC" ./configure --prefix="$PREFIX" --host="$TRIPLE" --cross-prefix="$TC/bin/llvm-" --sysroot="$TC/sysroot" \
  --enable-static --enable-pic --disable-cli --disable-opencl $X264_EXTRA
make -j"$JOBS"
make install

echo "== ffmpeg ($ABI)"
rm -rf "$SRC/ffmpeg-$ABI" && cp -r "$SRC/ffmpeg" "$SRC/ffmpeg-$ABI" && cd "$SRC/ffmpeg-$ABI"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig"
export PKG_CONFIG_LIBDIR="$PREFIX/lib/pkgconfig"
COMMON=(--prefix="$PREFIX" --target-os=android --arch="$ARCH" --enable-cross-compile
  --cc="$CC" --cxx="$CXX" --ar="$AR" --ranlib="$RANLIB" --nm="$NM" --strip="$STRIP" --sysroot="$TC/sysroot"
  --pkg-config=pkg-config --pkg-config-flags=--static
  --extra-cflags="-O3 -fPIC -I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib"
  --enable-gpl --enable-version3 --enable-static --disable-shared --enable-pic
  --disable-doc --disable-ffplay --enable-ffmpeg --enable-ffprobe --disable-debug
  --disable-indev=android_camera --disable-vulkan
  --enable-libx264 $FF_EXTRA)
if ! ./configure "${COMMON[@]}" --enable-jni --enable-mediacodec; then
  echo "!! configure with MediaCodec failed - building without the hardware encoder (the app falls back to x264)"
  tail -50 ffbuild/config.log || true
  ./configure "${COMMON[@]}"
fi
grep -E "^(CONFIG_MEDIACODEC|CONFIG_H264_MEDIACODEC_ENCODER|CONFIG_LIBX264)" ffbuild/config.mak || true
make -j"$JOBS"
"$STRIP" ffmpeg ffprobe
cp ffmpeg "$OUT/libffmpeg.so"
cp ffprobe "$OUT/libffprobe.so"
ls -la "$OUT"
