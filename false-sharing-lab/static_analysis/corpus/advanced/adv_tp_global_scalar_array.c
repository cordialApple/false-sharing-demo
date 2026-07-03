// SCENARIO: PLAIN GLOBAL SCALAR ARRAY long counters[8]. NO STRUCT.
//           THREAD i WRITE counters[tid]++. ALL 8 SHARE SAME 64B CACHE LINE.
// REAL WORLD: PER-CPU / PER-THREAD COUNTERS STORED IN FLAT ARRAY.
//             COMMON IN METRICS LIBS BEFORE THEY PAD. VERY BAD PATTERN.
// EXPECTED: [{"heuristic": "H6", "struct_contains": null, "severity": "MEDIUM"}]
//           WITH known_limitation: true (H6 NOT YET IMPLEMENTED)
// WHY: H2 IS STRUCT-TYPED, H5 IS DISTINCT GLOBALS. NEITHER COVERS SCALAR
//      ARRAYS. H6 CANDIDATE: VARIABLE-INDEX STORE INTO GLOBAL SCALAR ARRAY
//      WHERE ELEMENT SIZE < 64B. NEXT HEURISTIC TO IMPLEMENT.

#include <pthread.h>

#define NUM_THREADS 8

// PLAIN GLOBAL ARRAY. NO STRUCT. EACH long IS 8 BYTES.
// 8 ELEMENTS x 8 BYTES = 64 BYTES TOTAL. BUT EACH ELEMENT ONLY 8 BYTES.
// THREAD i WRITES counters[i]. ALL 8 SHARE SAME CACHE LINE. VERY BAD.
// ANALYZER CANNOT DETECT: H2 IS STRUCT-TYPED, H5 IS DISTINCT GLOBALS.
// THIS IS H6 CANDIDATE: VARIABLE-INDEX STORE INTO GLOBAL SCALAR ARRAY.
long counters[NUM_THREADS];

void *worker(void *arg) {
    int tid = *(int *)arg;
    for (int i = 0; i < 1000000; i++) {
        counters[tid]++;  // VARIABLE INDEX INTO SCALAR ARRAY. NO STRUCT. H6 NEEDED.
    }
    return NULL;
}

int main(void) {
    pthread_t threads[NUM_THREADS];
    int tids[NUM_THREADS];
    for (int i = 0; i < NUM_THREADS; i++) {
        tids[i] = i;
        pthread_create(&threads[i], NULL, worker, &tids[i]);
    }
    for (int i = 0; i < NUM_THREADS; i++) pthread_join(threads[i], NULL);
    return 0;
}
