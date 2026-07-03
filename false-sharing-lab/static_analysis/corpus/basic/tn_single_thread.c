// TN SINGLE THREAD
// GROK MAKE SMALL STRUCT ARRAY. VARIABLE INDEX. BUT NO PTHREAD_CREATE.
// NO THREADS MEANS NO FALSE SHARING. ONLY MAIN THREAD. SAFE.
// EXPECTED: CLEAN (no findings)
// WHY H2 NOT FIRE: H2 REQUIRES THREAD-REACHABLE FUNCTION. NO PTHREAD_CREATE.
//                  NO THREAD ENTRIES. NO THREAD-REACHABLE CODE. H2 SKIP.
// NOTE: H4 MAY FIRE (STRUCT SIZE 8, NOT MULTIPLE OF 64). H4 HAS NO THREAD-CONTEXT
//       GUARD. THIS IS A GENUINE TIER-1 WEAKNESS DOCUMENTED BY THIS TEST CASE.
//       FALSE SHARING REQUIRES MULTIPLE THREADS. H4 ADVISORY WITHOUT THREADS = FP.

#include <stdlib.h>

#define N 8

typedef struct {
    long value;   // 8 BYTES. SMALL STRUCT. MANY PER CACHE LINE IF THREAD USED IT.
} small_item_t;

small_item_t *items;  // GLOBAL POINTER. ACCESSED WITH VARIABLE INDEX.

// GROK SINGLE FUNCTION. NO THREAD. COMPUTE SOMETHING WITH items.
long compute_sum(int n) {
    long sum = 0;
    for (int i = 0; i < n; i++) {
        items[i].value = i;        // VARIABLE-INDEX WRITE (BUT SINGLE THREAD).
        sum += items[i].value;     // VARIABLE-INDEX READ.
    }
    return sum;
}

int main(void) {
    // NO PTHREAD_CREATE HERE. SINGLE THREAD ONLY.
    items = malloc(sizeof(small_item_t) * N);
    long result = compute_sum(N);
    (void)result;
    free(items);
    return 0;
}
