// TN H2 PADDED ARRAY
// GROK USE PADDING TO FIX FALSE SHARING. SAME PATTERN AS tp_h2_tid_array.
// BUT STRUCT NOW 64 BYTES. ONE ELEMENT PER CACHE LINE. NO SHARING. GOOD.
// EXPECTED: CLEAN (no findings)
// WHY: struct_size = 64 = CACHE_LINE_BYTES. H2 CONDITION sz < 64 IS FALSE.
//      H4 CONDITION sz % 64 != 0 IS ALSO FALSE. ANALYZER MUST STAY QUIET.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4
#define ITERS 1000000
#define CACHE_LINE 64

typedef struct {
    long value;                              // REAL DATA. 8 BYTES.
    char padding[CACHE_LINE - sizeof(long)]; // MANUAL PAD. 56 BYTES. TOTAL = 64.
} padded_counter_t;

padded_counter_t *counters;  // GLOBAL POINTER. THREAD LOAD THEN INDEX.

void *worker(void *arg) {
    // SAME PATTERN AS tp_h2. TID INDEX. BUT EACH ELEMENT ON OWN LINE NOW.
    int tid = *(int *)arg;
    for (int i = 0; i < ITERS; i++) {
        counters[tid].value++;  // ONE ELEMENT PER LINE. NO SHARING. FAST.
    }
    return NULL;
}

int main(void) {
    counters = malloc(sizeof(padded_counter_t) * NUM_THREADS);
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
