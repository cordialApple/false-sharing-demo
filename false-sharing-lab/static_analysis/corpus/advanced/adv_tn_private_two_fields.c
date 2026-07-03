// SCENARIO: THREAD MALLOC OWN TWO-FIELD STRUCT. WRITE BOTH FIELDS. NO SHARING.
// REAL WORLD: SPLASH-2 lu_ncb LocalCopies — PER-THREAD SCRATCH STRUCT.
//             HURON RUN FLAGGED IT H1: FP. THIS CASE IS THE REGRESSION TEST
//             FOR THE H1 INSTANCE-PRIVACY FIX.
// EXPECTED: [] (true negative — both fields same bucket BUT instance private)
// WHY: POINTER BORN FROM malloc INSIDE THREAD FN. NEVER STORED TO GLOBAL,
//      NEVER PASSED TO pthread_create, NEVER RETURNED. ONE THREAD ONLY.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4

typedef struct {
    long sum;    // OFFSET 0. BUCKET 0.
    long count;  // OFFSET 8. SAME BUCKET. WITHOUT PRIVACY CHECK H1 FIRES.
} scratch_t;

void *worker(void *arg) {
    (void)arg;
    scratch_t *s = malloc(sizeof(scratch_t));
    s->sum = 0;
    s->count = 0;
    for (int i = 0; i < 1000000; i++) {
        s->sum += i;
        s->count++;
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
