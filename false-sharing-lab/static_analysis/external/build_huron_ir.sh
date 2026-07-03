#!/bin/sh
# GROK FETCH HURON SUITE. COMPILE 7 C PROGRAM TO IR. SAME FLAGS AS CORPUS.
# RUN INSIDE WSL/LINUX WITH clang-18. OUTPUT LAND IN external/huron_ir/.
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
OUT="$SCRIPT_DIR/huron_ir"
HURON="${HURON_DIR:-$HOME/huron}"

# CLONE ONCE. SHALLOW. HURON REPO BIG, GROK ONLY WANT test_suites.
if [ ! -d "$HURON" ]; then
    git clone --depth 1 https://github.com/efeslab/huron.git "$HURON"
fi

mkdir -p "$OUT"
cd "$HURON/test_suites"

CFLAGS="-O0 -g -pthread -S -emit-llvm"

clang-18 $CFLAGS false/false.c                                 -o "$OUT/false.ll"
clang-18 $CFLAGS histogram/hist-pthread.c                      -o "$OUT/histogram.ll"
clang-18 $CFLAGS linear_regression/linear_regression_pthread.c -o "$OUT/linear_regression.ll"
clang-18 $CFLAGS locked/toy.c                                  -o "$OUT/locked_toy.ll"
clang-18 $CFLAGS lockless/toy.c                                -o "$OUT/lockless_toy.ll"
clang-18 $CFLAGS lu_ncb/lu.c                                   -o "$OUT/lu_ncb.ll"
# STRING_MATCH OLD CODE. CALL gettimeofday WITH NO INCLUDE. GROK FORCE HEADER.
clang-18 $CFLAGS -include sys/time.h -Wno-implicit-function-declaration \
    string_match/string_match_pthreads.c                      -o "$OUT/string_match.ll"

echo "done: $(ls "$OUT" | wc -l) IR files in $OUT"
