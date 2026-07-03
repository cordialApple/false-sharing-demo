// TN H1 SEPARATE LINES
// FIX HOT FIELDS WITH PADDING. SAME TWO-THREAD PATTERN AS tp_h1.
// BUT FIELD a AND FIELD b NOW ON DIFFERENT CACHE LINES.
// THREAD A WRITE FIELD a (OFFSET 0, BUCKET 0).
// THREAD B WRITE FIELD b (OFFSET 64, BUCKET 1). DIFFERENT BUCKET. NO H1.
// EXPECTED: CLEAN (no findings)
// WHY: unique_fields PER BUCKET < 2. H1 CONDITION NOT MET. ANALYZER QUIET.

#include <pthread.h>

// STRUCT WITH EXPLICIT GAP. FIELD a AND b ON DIFFERENT CACHE LINES.
struct separated_hot {
    long a;        // FIELD 0. OFFSET 0. BUCKET 0. THREAD A WRITE.
    char pad[56];  // FIELD 1. OFFSET 8. PADDING. NOBODY WRITE THIS.
    long b;        // FIELD 2. OFFSET 64. BUCKET 1. THREAD B WRITE.
};

struct separated_hot g = {0};  // SINGLE GLOBAL INSTANCE.

void *thread_a(void *arg) {
    // WRITE FIELD 0 (a). BUCKET 0. ONLY ONE WRITER IN THIS BUCKET.
    struct separated_hot *p = (struct separated_hot *)arg;
    for (int i = 0; i < 1000000; i++) {
        p->a++;  // GEP i32 0, i32 0. OFFSET 0. BUCKET 0.
    }
    return NULL;
}

void *thread_b(void *arg) {
    // WRITE FIELD 2 (b). BUCKET 1. ONLY ONE WRITER IN THIS BUCKET TOO.
    struct separated_hot *p = (struct separated_hot *)arg;
    for (int i = 0; i < 1000000; i++) {
        p->b++;  // GEP i32 0, i32 2. OFFSET 64. BUCKET 1. DIFFERENT LINE!
    }
    return NULL;
}

int main(void) {
    pthread_t t1, t2;
    pthread_create(&t1, NULL, thread_a, &g);
    pthread_create(&t2, NULL, thread_b, &g);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    return 0;
}
