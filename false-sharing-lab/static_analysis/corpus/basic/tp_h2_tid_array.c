// TP H2 TID ARRAY
// GROK MAKE CLASSIC TRAP. MANY THREAD. ONE WORKER FUNCTION.
// EACH THREAD WRITE counters[tid].value. TID IS THREAD ID.
// STRUCT TINY (8 BYTES). MANY ELEMENT FIT SAME CACHE LINE.
// 64 / 8 = 8 ELEMENT PER LINE. THREAD 0 AND THREAD 1 SHARE LINE. VERY BAD.
// EXPECTED: H2/HIGH on struct tid_counter_t
// WHY: VARIABLE-INDEX GEP INTO SMALL STRUCT. CLASSIC FALSE SHARING ANTI-PATTERN.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4
#define ITERS 1000000

typedef struct {
    long value;          // GROK ONLY FIELD. 8 BYTES. STRUCT TOO SMALL.
} tid_counter_t;

tid_counter_t *counters;  // GLOBAL POINTER. THREAD LOAD THEN INDEX WITH TID.

void *worker(void *arg) {
    // GROK: TID FROM ARG. USED AS ARRAY INDEX. VARIABLE INDEX. BAD.
    int tid = *(int *)arg;
    for (int i = 0; i < ITERS; i++) {
        counters[tid].value++;  // DIFFERENT TID, SAME CACHE LINE. PING PONG.
    }
    return NULL;
}

int main(void) {
    counters = malloc(sizeof(tid_counter_t) * NUM_THREADS);
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
