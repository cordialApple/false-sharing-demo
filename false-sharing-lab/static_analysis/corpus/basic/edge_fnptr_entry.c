// EDGE FNPTR ENTRY
// GROK LOAD FUNCTION POINTER INTO VARIABLE. PASS VARIABLE TO PTHREAD_CREATE.
// SAME FALSE SHARING PATTERN AS tp_h2_tid_array (SMALL STRUCT, TID INDEX).
// BUT ANALYZER CANNOT SEE THROUGH FUNCTION POINTER. THREAD ENTRY UNKNOWN.
// EXPECTED: H2 on struct tiny_t  (known_limitation: true)
// WHY LIMITATION: ir_analyzer pthread_re LOOKS FOR LITERAL @function_name IN 3RD ARG.
//   IF ARG IS ptr %fn_var (REGISTER), NO @NAME TO EXTRACT. THREAD ENTRY = EMPTY.
//   THREAD-REACHABLE CLOSURE = EMPTY. WORKER NEVER SCANNED. H2 NOT FOUND.
//   THIS IS FUNDAMENTAL STATIC ANALYSIS LIMITATION. CANNOT TRACK RUNTIME POINTERS.

#include <pthread.h>
#include <stdlib.h>

#define NUM_THREADS 4
#define ITERS 1000000

typedef struct {
    long value;   // 8 BYTES. WOULD CAUSE FALSE SHARING IF ANALYZER COULD SEE.
} tiny_t;

tiny_t *arr;  // GLOBAL POINTER TO SMALL STRUCT ARRAY.

// GROK WORKER FUNCTION. SAME AS tp_h2. TID INDEX. SMALL STRUCT. FALSE SHARING.
void *worker(void *arg) {
    int tid = *(int *)arg;
    for (int i = 0; i < ITERS; i++) {
        arr[tid].value++;  // VARIABLE INDEX. BAD PATTERN. BUT ANALYZER BLIND HERE.
    }
    return NULL;
}

int main(void) {
    arr = malloc(sizeof(tiny_t) * NUM_THREADS);
    for (int i = 0; i < NUM_THREADS; i++) arr[i].value = 0;

    // GROK LOAD FUNCTION POINTER INTO LOCAL VARIABLE. KEY: fn IS REGISTER IN IR.
    void *(*fn)(void *) = worker;  // fn = ptr %fn_var. NOT ptr @worker LITERAL.

    pthread_t threads[NUM_THREADS];
    int tids[NUM_THREADS];
    for (int i = 0; i < NUM_THREADS; i++) {
        tids[i] = i;
        // GROK PASS fn (REGISTER) NOT worker (LITERAL). ANALYZER CANNOT EXTRACT NAME.
        pthread_create(&threads[i], NULL, fn, &tids[i]);
    }
    for (int i = 0; i < NUM_THREADS; i++) pthread_join(threads[i], NULL);

    free(arr);
    return 0;
}
