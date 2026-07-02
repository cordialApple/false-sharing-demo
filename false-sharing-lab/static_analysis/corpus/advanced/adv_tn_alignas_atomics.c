// SCENARIO: TWO ATOMIC LONGS, EACH _Alignas(64). OFFSET a=0, OFFSET b=64.
//           DIFFERENT CACHE LINES. THREADS HAMMER EACH. PROPERLY ALIGNED.
// REAL WORLD: CORRECT IMPLEMENTATION OF ALIGNED ATOMIC COUNTERS.
//             LINUX KERNEL __cacheline_aligned, C11 _Alignas(64) DO THIS.
// EXPECTED: [] (true negative — fields on different cache lines)
// WHY: _Alignas(64) ON EACH MEMBER. a AT OFFSET 0, b AT OFFSET 64.
//      BUCKET(a)=0, BUCKET(b)=1. DIFFERENT LINES. H3 MUST NOT FIRE.
//      OFFSET MATH PRECISION TEST FOR TIER1 AND TIER2.

#include <pthread.h>
#include <stdatomic.h>

// TWO ATOMIC LONGS. EACH ALIGNED TO 64 BYTES.
// OFFSET a = 0. OFFSET b = 64. DIFFERENT CACHE LINES.
// H3 MUST NOT FIRE. OFFSET MATH MUST SHOW DIFFERENT BUCKETS.
struct aligned_pair {
    _Alignas(64) _Atomic long a;  // OFFSET 0. BUCKET 0.
    _Alignas(64) _Atomic long b;  // OFFSET 64. BUCKET 1. DIFFERENT LINE.
};

struct aligned_pair g;

void *thread_a(void *arg) {
    struct aligned_pair *p = (struct aligned_pair *)arg;
    for (int i = 0; i < 1000000; i++) {
        atomic_fetch_add(&p->a, 1);  // OFFSET 0. BUCKET 0.
    }
    return NULL;
}

void *thread_b(void *arg) {
    struct aligned_pair *p = (struct aligned_pair *)arg;
    for (int i = 0; i < 1000000; i++) {
        atomic_fetch_add(&p->b, 1);  // OFFSET 64. BUCKET 1. SAFE.
    }
    return NULL;
}

int main(void) {
    atomic_init(&g.a, 0);
    atomic_init(&g.b, 0);
    pthread_t t1, t2;
    pthread_create(&t1, NULL, thread_a, &g);
    pthread_create(&t2, NULL, thread_b, &g);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    return 0;
}
