// SCENARIO: PER-THREAD ARG STRUCT BIGGER THAN A LINE BUT NOT A MULTIPLE OF
//           64. EACH THREAD ONLY TOUCH OWN ELEMENT. BOUNDARIES STILL SHARED.
// REAL WORLD: HURON/PHOENIX histogram thread_arg_t (3096B, 3096 % 64 != 0).
// EXPECTED: H7 MEDIUM (thread-arg array element straddles line boundaries)
// WHY: sizeof(barg_t) = 104. ELEMENT i END AND ELEMENT i+1 START SHARE A
//      LINE. THREAD i AND i+1 WRITE THAT LINE CONCURRENTLY.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4

typedef struct {
    int tid;
    int hist[25];  // 104B TOTAL. 104 % 64 = 40. STRADDLE.
} barg_t;

void *worker(void *arg) {
    barg_t *t = (barg_t *)arg;
    for (int i = 0; i < 1000000; i++) {
        t->hist[i % 25]++;  // OWN ELEMENT ONLY. BOUNDARY LINE STILL BOUNCE.
    }
    return NULL;
}

int main(void) {
    pthread_t threads[NUM_THREADS];
    barg_t *args = malloc(NUM_THREADS * sizeof(barg_t));
    for (int i = 0; i < NUM_THREADS; i++) {
        args[i].tid = i;
        pthread_create(&threads[i], NULL, worker, &args[i]);
    }
    for (int i = 0; i < NUM_THREADS; i++) pthread_join(threads[i], NULL);
    free(args);
    return 0;
}
