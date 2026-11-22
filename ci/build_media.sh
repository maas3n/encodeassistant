#!/usr/bin/env bash
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
platform=$1
archives=$(cd "$2" && pwd)
mkdir -p "$3"
prefix=$(cd "$3" && pwd)
scratch=$(mktemp -d)
trap 'rm -rf "$scratch"' EXIT
jobs=$(getconf _NPROCESSORS_ONLN 2>/dev/null || sysctl -n hw.logicalcpu)
if (( jobs > 6 )); then jobs=6; fi

mkdir -p "$prefix/bin" "$prefix/lib" "$prefix/notices"
exe=
plugin=.so
shared=-shared
ffmpeg_extra=()
ffms_extra=()
avs2yuv_extra=(-pthread -ldl)
tool_prefix=$prefix

case "$platform" in
  windows-*)
    exe=.exe
    plugin=.dll
    avs2yuv_extra=()
    ffmpeg_extra=(--target-os=mingw32)
    tool_prefix=$(cygpath -m "$prefix")
    ;;
  macos-*)
    plugin=.dylib
    shared=-dynamiclib
    avs2yuv_extra=(-pthread)
    ffmpeg_extra=(--install-name-dir=@rpath --extra-ldflags=-Wl,-rpath,@loader_path/../lib)
    ffms_extra=(-Wl,-rpath,@loader_path)
    ;;
esac

for project in avisynthplus avs2yuv ffms2 x264 ffmpeg yadifmod2 mediainfo; do
  mkdir "$scratch/$project"
  archive="$archives/$project.tar.gz"
  if [[ "$project" == ffmpeg ]]; then archive="$archives/ffmpeg.tar.xz"; fi
  tar -xf "$archive" -C "$scratch/$project" --strip-components=1
  mkdir "$prefix/notices/$project"
  while IFS= read -r -d '' notice; do
    relative=${notice#"$scratch/$project/"}
    mkdir -p "$prefix/notices/$project/$(dirname "$relative")"
    cp "$notice" "$prefix/notices/$project/$relative"
  done < <(find "$scratch/$project" -maxdepth 4 -type f \( -iname 'license*' -o -iname 'copying*' -o -iname 'copyright*' -o -iname 'gpl.txt' \) -print0)
done

echo '::group::AviSynth+ and Avs2YUV'
cmake -G Ninja -S "$scratch/avisynthplus" -B "$scratch/avisynth-build" \
  -DCMAKE_BUILD_TYPE=Release -DENABLE_PLUGINS=OFF \
  -DCMAKE_INSTALL_LIBDIR=lib -DCMAKE_INSTALL_PREFIX="$tool_prefix"
cmake --build "$scratch/avisynth-build" --parallel "$jobs"
cmake --install "$scratch/avisynth-build"
cc -std=gnu99 -O2 -I"$scratch/avs2yuv" -I"$prefix/include/avisynth" "$scratch/avs2yuv/avs2yuv.c" \
  -o "$prefix/bin/avs2yuv$exe" "${avs2yuv_extra[@]}"
echo '::endgroup::'

echo '::group::FFmpeg libraries and ffprobe'
(
  cd "$scratch/ffmpeg"
  ./configure --prefix="$tool_prefix" --enable-shared --disable-static \
    --enable-pic --disable-autodetect --disable-ffmpeg --disable-ffplay --disable-doc \
    --disable-avdevice --disable-avfilter --disable-network --disable-encoders \
    --disable-muxers --disable-filters --disable-devices "${ffmpeg_extra[@]}"
  make -j"$jobs"
  make install
)
echo '::endgroup::'

echo '::group::FFMS2'
plugin_dir="$prefix/lib"
if [[ "$platform" == windows-* ]]; then plugin_dir="$prefix/bin"; fi
export PKG_CONFIG_PATH="$prefix/lib/pkgconfig"
read -r -a ffmpeg_flags <<< "$(pkg-config --cflags --libs libavformat libavcodec libavutil libswscale libswresample)"
c++ -std=c++11 -O2 "$shared" -fPIC -fvisibility=hidden \
  -D_FILE_OFFSET_BITS=64 -DFFMS_EXPORTS -D__STDC_CONSTANT_MACROS \
  -I"$scratch/ffms2/include" -I"$prefix/include/avisynth" \
  "$scratch/ffms2"/src/core/*.cpp "$scratch/ffms2"/src/avisynth/*.cpp \
  "${ffmpeg_flags[@]}" -lz "${ffms_extra[@]}" -o "$plugin_dir/ffms2$plugin"
echo '::endgroup::'

echo '::group::Yadifmod2'
patch -d "$scratch/yadifmod2" -p1 < "$script_dir/patches/yadifmod2-scalar.patch"
if [[ "$platform" == macos-arm64 ]]; then
  c++ -std=c++11 -O2 -dynamiclib -DYADIF_SCALAR_ONLY -I"$prefix/include/avisynth" \
    "$scratch/yadifmod2/src/proc_filter.cpp" "$scratch/yadifmod2/src/yadifmod2.cpp" \
    -o "$plugin_dir/yadifmod2$plugin"
else
  cmake -G Ninja -S "$scratch/yadifmod2" -B "$scratch/yadif-build" \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$tool_prefix" -DCMAKE_DISABLE_FIND_PACKAGE_Git=TRUE
  cmake --build "$scratch/yadif-build" --parallel "$jobs"
  yadif=$(find "$scratch/yadif-build" -name "*yadifmod2*$plugin" -type f -print -quit)
  cp "$yadif" "$plugin_dir/yadifmod2$plugin"
fi
echo '::endgroup::'

echo '::group::x264'
(
  cd "$scratch/x264"
  ./configure --prefix="$tool_prefix" --disable-opencl --disable-lavf --disable-ffms \
    --disable-swscale --disable-gpac --disable-lsmash
  make -j"$jobs"
  cp "x264$exe" "$prefix/bin/x264$exe"
)
echo '::endgroup::'

echo '::group::MediaInfo'
case "$platform" in
  windows-*)
    unzip -q "$archives/mediainfo-win.zip" -d "$scratch/mediainfo-win"
    cp "$scratch/mediainfo-win/MediaInfo.exe" "$prefix/bin/mediainfo.exe"
    cp "$scratch/mediainfo-win/"{LICENSE,License.html} "$prefix/notices/mediainfo/"
    for dll in libgcc_s_seh-1.dll libstdc++-6.dll libwinpthread-1.dll zlib1.dll; do
      cp "/ucrt64/bin/$dll" "$prefix/bin/"
      pacman -Qo "/ucrt64/bin/$dll" >> "$prefix/notices/msys2-packages.txt"
    done
    for package in gcc gcc-libs libwinpthread zlib; do
      notices="/ucrt64/share/licenses/${MINGW_PACKAGE_PREFIX:-mingw-w64-ucrt-x86_64}-$package"
      if [[ -d "$notices" ]]; then cp -R "$notices" "$prefix/notices/"; fi
    done
    ;;
  macos-*)
    mkdir "$scratch/mount"
    hdiutil attach -nobrowse -readonly -mountpoint "$scratch/mount" "$archives/mediainfo-mac.dmg"
    package=$(find "$scratch/mount" -name '*.pkg' -print -quit)
    if [[ -n "$package" ]]; then
      pkgutil --expand-full "$package" "$scratch/pkg"
      mediainfo=$(find "$scratch/pkg" -name mediainfo -type f -print -quit)
    else
      mediainfo=$(find "$scratch/mount" -name mediainfo -type f -print -quit)
    fi
    cp "$mediainfo" "$prefix/bin/mediainfo"
    hdiutil detach "$scratch/mount"
    chmod +x "$prefix/bin/mediainfo"
    ;;
  linux-*)
    (
      cd "$scratch/mediainfo"
      (cd ZenLib/Project/GNU/Library && ./configure --enable-static --disable-shared && make -j"$jobs")
      (cd MediaInfoLib/Project/GNU/Library && ./configure --enable-static --disable-shared --without-libcurl && make -j"$jobs")
      (cd MediaInfo/Project/GNU/CLI && ./configure --enable-staticlibs && make -j"$jobs")
      cp MediaInfo/Project/GNU/CLI/mediainfo "$prefix/bin/mediainfo"
    )
    ;;
esac
echo '::endgroup::'
