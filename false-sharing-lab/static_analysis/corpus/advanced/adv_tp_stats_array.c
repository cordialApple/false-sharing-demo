// SCENARIO: REPLICA OF llvm::TrackingStatistic. STRUCT { name ptr + atomic ulong }
//           = 16 BYTES. 4 STRUCTS FIT IN ONE 64-BYTE CACHE LINE.
//           THREAD i WRITE stats[i].value. DIFFERENT INDEX, SAME LINE. BAD.
// REAL WORLD: lshaz FOUND THIS IN llvm::TrackingStatistic.
//             SEE: https://discourse.llvm.org/t/lshaz-a-clang-llvm-static-analyzer-for-microarchitectural-hazards/90100
// EXPECTED: H2/HIGH (variable-index array of 16B structs, thread-reachable)
// WHY: STRUCT SIZE 16 < 64. THREAD USE tid AS ARRAY INDEX. ADJACENT STRUCTS
//      ON SAME CACHE LINE. CLASSIC STATISTIC ARRAY ANTI-PATTERN.

#include <pthread.h>
#include <stdatomic.h>

#define NUM_STATS 4
#define NUM_THREADS 4

// REPLICA OF llvm::TrackingStatistic. NAME + ATOMIC VALUE. 16 BYTES.
// 4 SUCH STRUCTS FIT IN ONE 64-BYTE CACHE LINE.
// THREAD i WRITES stats[i].value. DIFFERENT INDEX, SAME LINE. BAD.
typedef struct {
    const char *name;            // OFFSET 0. 8 BYTES. POINTER.
    _Atomic unsigned long value; // OFFSET 8. 8 BYTES. ATOMIC COUNTER.
} stat_t;

stat_t stats[NUM_STATS] = {
    {"allocs", 0}, {"frees", 0}, {"hits", 0}, {"misses", 0}
};

void *worker(void *arg) {
    int tid = *(int *)arg;
    for (int i = 0; i < 1000000; i++) {
        atomic_fetch_add(&stats[tid].value, 1);  // VARIABLE INDEX = tid.
    }
    return NULL;
}

int main(void) {
    pthread_t threads[NUM_THREADS];
    int tids[NUM_THREADS];
    for (int i = 0; i < NUM_THREADS; i++) {
        tids[i] = i;
        pthread_create(&threads[i], NULL, worker, &tids[i]);
    }
    for (int i = 0; i < NUM_THREADS; i++) pthread_join(threads[i], NULL);
    return 0;
}
