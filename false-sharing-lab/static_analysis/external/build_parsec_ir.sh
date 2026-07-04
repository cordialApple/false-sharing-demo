#!/bin/sh
# FETCH PARSEC 3.0 (cirosantilli MIRROR). COMPILE 3 PROGRAM TO IR.
# EACH PROGRAM = MANY TU. llvm-link MERGE TO ONE MODULE PER PROGRAM.
# RUN INSIDE WSL/LINUX WITH clang-18 + llvm-link-18. OUTPUT external/parsec_ir/.
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
OUT="$SCRIPT_DIR/parsec_ir"
PARSEC="${PARSEC_DIR:-$HOME/parsec-benchmark}"

# CLONE ONCE. REPO HUGE EVEN SHALLOW. BLOBLESS + SPARSE, ONLY 3 src DIRS.
if [ ! -d "$PARSEC" ]; then
    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/cirosantilli/parsec-benchmark.git "$PARSEC"
    git -C "$PARSEC" sparse-checkout set \
        pkgs/kernels/streamcluster/src \
        pkgs/apps/fluidanimate/src \
        pkgs/kernels/canneal/src
fi

mkdir -p "$OUT"
TMP="$OUT/tu"
mkdir -p "$TMP"

# OLD CODE. WARNING FLOOD USELESS. SILENCE ALL.
CXXFLAGS="-O0 -g -pthread -std=c++11 -S -emit-llvm -Wno-everything -DENABLE_THREADS"

# STREAMCLUSTER: IN-TREE PTHREAD BARRIER. NO TBB_VERSION.
SC="$PARSEC/pkgs/kernels/streamcluster/src"
clang++-18 $CXXFLAGS "$SC/streamcluster.cpp"   -o "$TMP/sc_streamcluster.ll"
clang++-18 $CXXFLAGS "$SC/parsec_barrier.cpp"  -o "$TMP/sc_parsec_barrier.ll"
llvm-link-18 -S "$TMP/sc_streamcluster.ll" "$TMP/sc_parsec_barrier.ll" \
    -o "$OUT/streamcluster.ll"

# FLUIDANIMATE: PTHREADS VERSION ONLY. SKIP serial/tbb/fluidview.
FA="$PARSEC/pkgs/apps/fluidanimate/src"
clang++-18 $CXXFLAGS "$FA/pthreads.cpp"        -o "$TMP/fa_pthreads.ll"
clang++-18 $CXXFLAGS "$FA/cellpool.cpp"        -o "$TMP/fa_cellpool.ll"
clang++-18 $CXXFLAGS "$FA/parsec_barrier.cpp"  -o "$TMP/fa_parsec_barrier.ll"
llvm-link-18 -S "$TMP/fa_pthreads.ll" "$TMP/fa_cellpool.ll" \
    "$TMP/fa_parsec_barrier.ll" -o "$OUT/fluidanimate.ll"

# CANNEAL: IN-TREE atomic/ ASM HEADERS. X86_64 PATH FINE.
CN="$PARSEC/pkgs/kernels/canneal/src"
for f in main netlist netlist_elem rng annealer_thread; do
    clang++-18 $CXXFLAGS "$CN/$f.cpp" -o "$TMP/cn_$f.ll"
done
llvm-link-18 -S "$TMP/cn_main.ll" "$TMP/cn_netlist.ll" \
    "$TMP/cn_netlist_elem.ll" "$TMP/cn_rng.ll" "$TMP/cn_annealer_thread.ll" \
    -o "$OUT/canneal.ll"

# ANALYZER WANT MERGED MODULE ONLY. DROP PER-TU SCRAPS.
rm -rf "$TMP"

echo "done: $(ls "$OUT"/*.ll | wc -l) merged IR files in $OUT"
