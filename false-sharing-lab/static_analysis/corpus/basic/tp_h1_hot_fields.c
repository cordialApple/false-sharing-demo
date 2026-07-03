// TP H1 HOT FIELDS
// MAKE STRUCT WITH TWO HOT FIELDS. ONE STRUCT. TWO THREADS.
// THREAD A WRITE FIELD a. THREAD B WRITE FIELD b.
// BOTH FIELDS IN SAME 64-BYTE BUCKET (OFFSET 0 AND 8). SAME LINE. BAD.
// NO ARRAY INDEXING. SINGLE STRUCT INSTANCE. H2 NOT FIRE. H1 MUST FIRE.
// EXPECTED: H1/MEDIUM on struct hot_fields
// WHY: TWO DISTINCT FIELDS BOTH WRITTEN FROM THREAD-REACHABLE CODE, SAME BUCKET.

#include <pthread.h>

// STRUCT WITH TWO FIELDS. BOTH IN FIRST CACHE LINE (OFFSETS 0 AND 8).
struct hot_fields {
    long a;   // FIELD 0. THREAD A WRITE THIS. OFFSET 0. BUCKET 0.
    long b;   // FIELD 1. THREAD B WRITE THIS. OFFSET 8. BUCKET 0. SAME LINE!
};

struct hot_fields g = {0, 0};  // SINGLE INSTANCE. GLOBAL. SHARED BY BOTH THREADS.

void *thread_a(void *arg) {
    // THREAD A. ONLY WRITE FIELD a. NOT FIELD b.
    struct hot_fields *p = (struct hot_fields *)arg;
    for (int i = 0; i < 1000000; i++) {
        p->a++;  // WRITE FIELD 0. ptr %p, i32 0, i32 0.
    }
    return NULL;
}

void *thread_b(void *arg) {
    // THREAD B. ONLY WRITE FIELD b. NOT FIELD a.
    struct hot_fields *p = (struct hot_fields *)arg;
    for (int i = 0; i < 1000000; i++) {
        p->b++;  // WRITE FIELD 1. ptr %p, i32 0, i32 1. SAME LINE AS FIELD 0.
    }
    return NULL;
}

int main(void) {
    pthread_t t1, t2;
    pthread_create(&t1, NULL, thread_a, &g);  // THREAD A GET POINTER TO g.
    pthread_create(&t2, NULL, thread_b, &g);  // THREAD B ALSO GET POINTER TO g.
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    return 0;
}
