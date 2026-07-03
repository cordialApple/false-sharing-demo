#!/bin/sh
# BUILD PLUGIN UNDER WSL. cmake CONFIGURE THEN cmake BUILD.
# RUN: wsl -e sh -c "cd /mnt/c/.../tier2_pass && sh build.sh"
set -e

DIR=$(cd "$(dirname "$0")" && pwd)
cd "$DIR"

# FIND LLVM CMAKE DIR. TRY llvm-config-18 FIRST. FALLBACK KNOWN PATH.
if command -v llvm-config-18 >/dev/null 2>&1; then
  CMAKE_DIR=$(llvm-config-18 --cmakedir)
elif command -v llvm-config >/dev/null 2>&1; then
  CMAKE_DIR=$(llvm-config --cmakedir)
else
  CMAKE_DIR=/usr/lib/llvm-18/lib/cmake/llvm
fi
echo "USE LLVM CMAKE DIR: $CMAKE_DIR"

cmake -B build -DCMAKE_BUILD_TYPE=Release -DLLVM_DIR="$CMAKE_DIR" .
cmake --build build -j"$(nproc)"

echo ""
echo "BUILD DONE. PLUGIN AT: $DIR/build/FalseSharingPass.so"
