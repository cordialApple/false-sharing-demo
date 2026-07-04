#!/bin/sh
# FETCH PARSEC 3.0 (cirosantilli MIRROR). COMPILE 3 PROGRAM TO IR.
# EACH PROGRAM = MANY TU. llvm-link MERGE TO ONE MODULE PER PROGRAM.
# RUN INSIDE WSL/LINUX WITH clang-18 + llvm-link-18. OUTPUT external/parsec_ir/.
set -e

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
OUT="$SCRIPT_DIR/parsec_ir"
PARSEC="${PARSEC_DIR:-$HOME/parsec-benchmark}"
# PIN MIRROR COMMIT. REPRODUCIBLE IR NO MATTER WHAT UPSTREAM DO.
PARSEC_SHA=d4d9afdd27bbe39ca0ce88132b2d9f359b7868af

# CLONE ONCE. REPO HUGE EVEN SHALLOW. BLOBLESS + SPARSE, ONLY 3 src DIRS.
if [ ! -d "$PARSEC" ]; then
    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/cirosantilli/parsec-benchmark.git "$PARSEC"
fi
# SPARSE SET + PIN OUTSIDE THE GUARD. INTERRUPTED FIRST RUN OR NEW src DIR
# MUST HEAL ON RERUN, NOT WEDGE FOREVER.
git -C "$PARSEC" sparse-checkout set \
    pkgs/kernels/streamcluster/src \
    pkgs/apps/fluidanimate/src \
    pkgs/kernels/canneal/src
if [ "$(git -C "$PARSEC" rev-parse HEAD)" != "$PARSEC_SHA" ]; then
    git -C "$PARSEC" fetch --depth 1 origin "$PARSEC_SHA"
    git -C "$PARSEC" checkout "$PARSEC_SHA"
fi

mkdir -p "$OUT"
# PER-TU SCRAPS OUTSIDE $OUT. MID-RUN FAILURE MUST NOT LEAVE tu/*.ll
# WHERE scan.py RGLOB PICK THEM UP AS BOGUS PROGRAMS.
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

. "$SCRIPT_DIR/ir_flags.sh"
# OLD CODE. WARNING FLOOD USELESS. SILENCE ALL.
CXXFLAGS="$IR_BASEFLAGS -std=c++11 -Wno-everything -DENABLE_THREADS"

# SOURCES IMMUTABLE AT PINNED SHA, SO EXISTING MERGED .ll = DONE.
# DELETE THE .ll TO FORCE REBUILD.

# STREAMCLUSTER: IN-TREE PTHREAD BARRIER. NO TBB_VERSION.
if [ -f "$OUT/streamcluster.ll" ]; then
    echo "skip: streamcluster.ll exists"
else
    SC="$PARSEC/pkgs/kernels/streamcluster/src"
    clang++-18 $CXXFLAGS "$SC/streamcluster.cpp"   -o "$TMP/sc_streamcluster.ll"
    clang++-18 $CXXFLAGS "$SC/parsec_barrier.cpp"  -o "$TMP/sc_parsec_barrier.ll"
    llvm-link-18 -S "$TMP/sc_streamcluster.ll" "$TMP/sc_parsec_barrier.ll" \
        -o "$OUT/streamcluster.ll"
fi

# FLUIDANIMATE: PTHREADS VERSION ONLY. SKIP serial/tbb/fluidview.
if [ -f "$OUT/fluidanimate.ll" ]; then
    echo "skip: fluidanimate.ll exists"
else
    FA="$PARSEC/pkgs/apps/fluidanimate/src"
    clang++-18 $CXXFLAGS "$FA/pthreads.cpp"        -o "$TMP/fa_pthreads.ll"
    clang++-18 $CXXFLAGS "$FA/cellpool.cpp"        -o "$TMP/fa_cellpool.ll"
    clang++-18 $CXXFLAGS "$FA/parsec_barrier.cpp"  -o "$TMP/fa_parsec_barrier.ll"
    llvm-link-18 -S "$TMP/fa_pthreads.ll" "$TMP/fa_cellpool.ll" \
        "$TMP/fa_parsec_barrier.ll" -o "$OUT/fluidanimate.ll"
fi

# CANNEAL: IN-TREE atomic/ ASM HEADERS. X86_64 PATH FINE.
if [ -f "$OUT/canneal.ll" ]; then
    echo "skip: canneal.ll exists"
else
    CN="$PARSEC/pkgs/kernels/canneal/src"
    for f in main netlist netlist_elem rng annealer_thread; do
        clang++-18 $CXXFLAGS "$CN/$f.cpp" -o "$TMP/cn_$f.ll"
    done
    llvm-link-18 -S "$TMP/cn_main.ll" "$TMP/cn_netlist.ll" \
        "$TMP/cn_netlist_elem.ll" "$TMP/cn_rng.ll" "$TMP/cn_annealer_thread.ll" \
        -o "$OUT/canneal.ll"
fi

echo "done: $(ls "$OUT"/*.ll | wc -l) merged IR files in $OUT"
