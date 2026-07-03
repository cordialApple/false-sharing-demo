// SCENARIO: STRUCT LOOK PADDED BUT PADDING TOO SMALL. pad[16] GIVE 24B TOTAL.
//           24 < 64. STILL FALSE SHARING. HARD TO SPOT BY EYE.
// REAL WORLD: DEVELOPER ADD pad FIELD THINKING IT HELP. OFF BY FACTOR OF 3.5.
//             CORRECT FIX: pad[56] FOR 64-BYTE TOTAL.
// EXPECTED: H2/HIGH (deceptive_t array, struct 24B < 64B, variable tid index)
// WHY: STRUCT = 8 (long) + 16 (pad) = 24 BYTES. 24 < 64. MULTIPLE STRUCTS
//      PER LINE. THREAD i ACCESS arr[i]. CLASSIC H2 PATTERN. DECEPTIVE!

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4

// STRUCT LOOK LIKE IT PADDED. HAS pad FIELD. BUT ONLY 16 BYTES.
// TOTAL = 8 + 16 = 24 BYTES. 24 < 64. STILL FALSE SHARING. DECEPTIVE!
// FIX: pad MUST BE 56 BYTES (NOT 16) FOR 64-BYTE TOTAL.
typedef struct {
    long v;        // DATA. OFFSET 0. 8 BYTES.
    char pad[16];  // PAD LOOK BIG. BUT 24 < 64. STILL BAD.
} deceptive_t;

deceptive_t *arr;

void *worker(void *arg) {
    int tid = *(int *)arg;
    for (int i = 0; i < 1000000; i++) {
        arr[tid].v++;  // VARIABLE INDEX = tid. 24-BYTE STRUCT. MULTIPLE PER LINE.
    }
    return NULL;
}

int main(void) {
    arr = malloc(sizeof(deceptive_t) * NUM_THREADS);
    pthread_t threads[NUM_THREADS];
    int tids[NUM_THREADS];
    for (int i = 0; i < NUM_THREADS; i++) {
        tids[i] = i;
        pthread_create(&threads[i], NULL, worker, &tids[i]);
    }
    for (int i = 0; i < NUM_THREADS; i++) pthread_join(threads[i], NULL);
    free(arr);
    return 0;
}
