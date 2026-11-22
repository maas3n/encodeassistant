#!/usr/bin/env bash
set -euo pipefail

prefix=$(cd "$1" && pwd)
bin="$prefix/bin"
shopt -s nullglob nocasematch
declare -A inspected

while true; do
  copied=false
  for binary in "$bin"/*.dll "$bin"/*.exe; do
    if [[ ${inspected[$binary]:-} ]]; then continue; fi
    inspected[$binary]=true
    imports=$(objdump -p "$binary" | awk '/DLL Name:/ {print $3}')
    for dll in $imports; do
      if [[ -f "$bin/$dll" ]]; then continue; fi
      if [[ -f "$prefix/lib/$dll" ]]; then
        cp "$prefix/lib/$dll" "$bin/"
      elif [[ -f "/ucrt64/bin/$dll" ]]; then
        cp "/ucrt64/bin/$dll" "$bin/"
        package=$(pacman -Qoq "/ucrt64/bin/$dll")
        pacman -Q "$package" >> "$prefix/notices/msys2-packages.txt"
        if [[ -d "/ucrt64/share/licenses/$package" ]]; then
          cp -R "/ucrt64/share/licenses/$package" "$prefix/notices/"
        fi
      elif [[ -f "/c/Windows/System32/$dll" || "$dll" == api-ms-* || "$dll" == ext-ms-* ]]; then
        continue
      else
        printf 'Unresolved import %s in %s\n' "$dll" "$(basename "$binary")" >&2
        exit 1
      fi
      printf 'Included %s for %s\n' "$dll" "$(basename "$binary")"
      copied=true
    done
  done
  if [[ "$copied" == false ]]; then break; fi
done
ls -1 "$bin"
