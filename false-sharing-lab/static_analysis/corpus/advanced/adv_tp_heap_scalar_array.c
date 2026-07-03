// SCENARIO: HEAP int ARRAY. THREAD i WRITE array[i]. NO STRUCT ANYWHERE.
// REAL WORLD: DOMINANT HURON-SUITE PATTERN (false.c, locked, lockless, lu_ncb).
//             4 OF 7 HURON GROUND-TRUTH BUGS ARE EXACTLY THIS SHAPE.
// EXPECTED: H6 MEDIUM (variable-index store into shared scalar heap array)
// WHY: 16 ints = 64 BYTES. ALL SLOTS ON ONE CACHE LINE. EACH THREAD HAMMER
//      OWN SLOT. LINE PING-PONG BETWEEN CORES.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4

// SHARED HEAP ARRAY. GLOBAL POINTER SO EVERY THREAD SEE SAME BLOCK.
static int *counters;

typedef struct {
    int tid;
} targ_t;

void *worker(void *arg) {
    int tid = ((targ_t *)arg)->tid;
    for (int i = 0; i < 1000000; i++) {
        counters[tid]++;  // VARIABLE INDEX. SCALAR ELEMENT. SHARED LINE.
    }
    return NULL;
}

int main(void) {
    counters = malloc(NUM_THREADS * sizeof(int));
    pthread_t threads[NUM_THREADS];
    targ_t args[NUM_THREADS];
    for (int i = 0; i < NUM_THREADS; i++) {
        args[i].tid = i;
        pthread_create(&threads[i], NULL, worker, &args[i]);
    }
    for (int i = 0; i < NUM_THREADS; i++) pthread_join(threads[i], NULL);
    free(counters);
    return 0;
}
