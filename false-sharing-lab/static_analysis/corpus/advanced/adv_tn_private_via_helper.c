// SCENARIO: THREAD MALLOC OWN STRUCT, PASS POINTER TO HELPER. HELPER WRITE
//           BOTH FIELDS. STILL ONE THREAD ONLY.
// REAL WORLD: SPLASH-2 lu_ncb LocalCopies — malloc IN SlaveStart, WRITES IN
//             lu()/OneSolve() HELPERS. INTRA-FUNCTION PRIVACY MISSED IT;
//             THIS CASE IS THE REGRESSION TEST FOR INTERPROCEDURAL PRIVACY.
// EXPECTED: [] (true negative — helper param private at every call site)
// WHY: bump'S PARAM RECEIVES ONLY THE PRIVATE malloc POINTER. bump'S
//      ADDRESS NEVER TAKEN. NO OTHER CALL SITE. ONE THREAD OWNS THE BLOCK.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4

typedef struct {
    long sum;    // OFFSET 0. BUCKET 0.
    long count;  // OFFSET 8. SAME BUCKET. H1 BAIT WITHOUT INTERPROC PRIVACY.
} scratch_t;

static void bump(scratch_t *s, int i) {
    s->sum += i;
    s->count++;
}

void *worker(void *arg) {
    (void)arg;
    scratch_t *s = malloc(sizeof(scratch_t));
    s->sum = 0;
    s->count = 0;
    for (int i = 0; i < 1000000; i++) {
        bump(s, i);
    }
    free(s);
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
