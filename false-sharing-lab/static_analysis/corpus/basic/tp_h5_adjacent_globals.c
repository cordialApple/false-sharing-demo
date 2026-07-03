// TP H5 ADJACENT GLOBALS
// GROK MAKE TWO PLAIN GLOBAL LONGS. NO STRUCT. DIFFERENT THREADS WRITE EACH.
// LINKER PLACE THESE ADJACENT IN .BSS SECTION. BOTH FIT IN SAME 64-BYTE LINE.
// THREAD A WRITE counter_a. THREAD B WRITE counter_b. SAME LINE. BAD.
// EXPECTED: H5 on globals counter_a and counter_b
// WHY H5: GLOBALS WITHIN 64B IN DATA SEGMENT, BOTH THREAD-WRITTEN.
// NOTE: TIER-1 DOES NOT IMPLEMENT H5. NEEDS LINKER MAP OR LTO.
//       ALSO: store TO @global (not %reg) DOES NOT MATCH tier-1 store_re.
//       FINDING WILL BE ABSENT. VERDICT = MISS (FN). KNOWN COVERAGE GAP.

#include <pthread.h>

long counter_a = 0;  // GLOBAL LONG. THREAD A WRITE. LIKELY ADJACENT TO counter_b.
long counter_b = 0;  // GLOBAL LONG. THREAD B WRITE. SAME LINE AS counter_a.

void *thread_a(void *arg) {
    // GROK THREAD A. WRITE counter_a IN LOOP. DIRECT GLOBAL ACCESS.
    // IR: store i64 %val, ptr @counter_a  (GLOBAL, NOT REGISTER PTR)
    for (int i = 0; i < 1000000; i++) {
        counter_a++;
    }
    return NULL;
}

void *thread_b(void *arg) {
    // GROK THREAD B. WRITE counter_b. ADJACENT GLOBAL. SAME CACHE LINE.
    // IR: store i64 %val, ptr @counter_b  (GLOBAL, NOT REGISTER PTR)
    for (int i = 0; i < 1000000; i++) {
        counter_b++;
    }
    return NULL;
}

int main(void) {
    pthread_t t1, t2;
    pthread_create(&t1, NULL, thread_a, NULL);
    pthread_create(&t2, NULL, thread_b, NULL);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    return 0;
}
