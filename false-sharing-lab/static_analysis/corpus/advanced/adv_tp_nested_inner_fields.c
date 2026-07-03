// SCENARIO: NESTED STRUCT. outer { long x; struct inner { long a; long b; } in; }.
//           THREAD A WRITE o->x (OFFSET 0). THREAD B WRITE o->in.b (OFFSET 16).
//           SAME CACHE LINE. TESTS MULTI-LEVEL FIELD RESOLUTION VIA NESTED GEP.
// REAL WORLD: COMMON IN C STRUCTS WITH EMBEDDED CONTROL BLOCKS.
// EXPECTED: H1/MEDIUM (outer fields x at offset 0 and in.b at offset 16, same bucket)
// WHY: x=0, inner.a=8, inner.b=16. ALL IN BUCKET 0 [0..63].
//      THREAD A WRITE offset 0, THREAD B WRITE offset 16. H1 FIRES.

#include <pthread.h>

struct inner {
    long a;   // OFFSET 0 WITHIN inner. ABSOLUTE OFFSET 8 IN outer.
    long b;   // OFFSET 8 WITHIN inner. ABSOLUTE OFFSET 16 IN outer.
};

struct outer {
    long x;          // OFFSET 0. THREAD A WRITE THIS.
    struct inner in; // OFFSET 8. NESTED STRUCT.
};

struct outer g = {0, {0, 0}};

void *thread_a(void *arg) {
    struct outer *o = (struct outer *)arg;
    for (int i = 0; i < 1000000; i++) {
        o->x++;   // WRITE offset 0. BUCKET 0. GEP %outer*, i32 0, i32 0.
    }
    return NULL;
}

void *thread_b(void *arg) {
    struct outer *o = (struct outer *)arg;
    for (int i = 0; i < 1000000; i++) {
        o->in.b++;  // WRITE offset 16. BUCKET 0. NESTED GEP: i32 0, i32 1, i32 1.
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
