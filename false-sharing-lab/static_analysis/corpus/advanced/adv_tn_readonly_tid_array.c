// SCENARIO: THREADS INDEX SMALL-STRUCT ARRAY BY VARIABLE, ONLY EVER READ.
// REAL WORLD: PHOENIX linear_regression POINT_T INPUT ARRAY. HURON RUN
//             FLAGGED IT H2 HIGH: FP. THIS CASE IS THE REGRESSION TEST FOR
//             THE H2 WRITE-REQUIREMENT FIX.
// EXPECTED: [] (true negative — read-only sharing causes no invalidation)
// WHY: NO STORE THROUGH THE VARIABLE-INDEX GEP. LINES REPLICATE IN EVERY
//      CORE'S CACHE IN SHARED STATE. NO PING-PONG. RESULT GO BACK THROUGH
//      PER-THREAD ARG STRUCT, NOT A SHARED ARRAY.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4
#define N 1024

typedef struct {
    short x;  // 2 BYTES.
    short y;  // 4B TOTAL. 16 ELEMENTS PER LINE. WITHOUT WRITE CHECK H2 FIRES.
} point_t;

static point_t points[N];

typedef struct {
    int tid;      // WRITTEN BY main ONLY.
    long result;  // ONLY FIELD THREAD WRITES. ONE WRITER PER INSTANCE.
    char pad[48]; // ONE ARG PER CACHE LINE. ARG ARRAY ITSELF INNOCENT.
} targ_t;

void *worker(void *arg) {
    targ_t *t = (targ_t *)arg;
    long acc = 0;
    for (int i = t->tid; i < N; i += NUM_THREADS) {
        acc += points[i].x * points[i].y;  // LOADS ONLY. NEVER STORE.
    }
    t->result = acc;
    return NULL;
}

int main(void) {
    pthread_t threads[NUM_THREADS];
    targ_t args[NUM_THREADS];
    for (int i = 0; i < NUM_THREADS; i++) {
        args[i].tid = i;
        args[i].result = 0;
        pthread_create(&threads[i], NULL, worker, &args[i]);
    }
    for (int i = 0; i < NUM_THREADS; i++) pthread_join(threads[i], NULL);
    return 0;
}
