// SCENARIO: EACH THREAD MALLOC OWN STRUCT INSIDE THREAD FN. NO SHARING.
//           NO GLOBAL. NO THREAD-VISIBLE STRUCT FROM OUTSIDE.
// REAL WORLD: PROPERLY ISOLATED THREAD-LOCAL HEAP ALLOCATION.
//             JEMALLOC / tcmalloc USE PER-THREAD ARENAS FOR THIS REASON.
// EXPECTED: [] (true negative — no false sharing, each thread own block)
// WHY: private_t MALLOC INSIDE THREAD. NOT PASSED TO OTHER THREADS. NOT GLOBAL.
//      STATIC ANALYZER MAY FALSE POSITIVE: HEAP PRIVACY INVISIBLE STATICALLY.
//      IF ANALYZER FIRES, LIST IN known_fp.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4

// EACH THREAD MALLOC OWN STRUCT. NO SHARING. PRIVATE HEAP BLOCK.
// STATIC ANALYZER CANNOT KNOW THIS IS PRIVATE. MAY FALSE POSITIVE.
typedef struct {
    long v;  // ONLY FIELD. 8 BYTES.
} private_t;

void *worker(void *arg) {
    (void)arg;
    // MALLOC INSIDE THREAD. NOT SHARED. PRIVATE.
    private_t *p = malloc(sizeof(private_t));
    p->v = 0;
    for (int i = 0; i < 1000000; i++) {
        p->v++;  // LOCAL TO THIS THREAD. NO FALSE SHARING.
    }
    free(p);
    return NULL;
}

int main(void) {
    pthread_t threads[NUM_THREADS];
    for (int i = 0; i < NUM_THREADS; i++) {
        pthread_create(&threads[i], NULL, worker, NULL);
    }
    for (int i = 0; i < NUM_THREADS; i++) pthread_join(threads[i], NULL);
    return 0;
}
