// TN H2 ALIGNED ATTR
// USE __attribute__((aligned(64))) INSTEAD OF MANUAL PADDING.
// COMPILER HANDLE PADDING. SAME EFFECT AS tn_h2_padded_array. STRUCT SIZE = 64.
// EXPECTED: CLEAN (no findings)
// WHY: aligned(64) FORCES sizeof TO BE MULTIPLE OF 64.
//      CLANG EMIT [56 x i8] PADDING IN LLVM IR TYPE BODY.
//      ANALYZER SEE SIZE = 64. H2 AND H4 DO NOT FIRE.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4
#define ITERS 1000000

// USE ATTRIBUTE. COMPILER ADD PADDING. SIZE BECOME 64.
typedef struct {
    long value;
} __attribute__((aligned(64))) aligned_counter_t;

aligned_counter_t *counters;  // GLOBAL POINTER. THREAD LOAD THEN INDEX.

void *worker(void *arg) {
    // SAME PATTERN. TID INDEX. STRUCT IS 64 BYTES. EACH THREAD OWN LINE.
    int tid = *(int *)arg;
    for (int i = 0; i < ITERS; i++) {
        counters[tid].value++;
    }
    return NULL;
}

int main(void) {
    counters = malloc(sizeof(aligned_counter_t) * NUM_THREADS);
    for (int i = 0; i < NUM_THREADS; i++) counters[i].value = 0;

    pthread_t threads[NUM_THREADS];
    int tids[NUM_THREADS];
    for (int i = 0; i < NUM_THREADS; i++) {
        tids[i] = i;
        pthread_create(&threads[i], NULL, worker, &tids[i]);
    }
    for (int i = 0; i < NUM_THREADS; i++) pthread_join(threads[i], NULL);

    free(counters);
    return 0;
}
