// TP H3 ADJACENT ATOMICS
// GROK MAKE STRUCT WITH TWO ATOMIC FIELDS. ADJACENT IN MEMORY. SAME LINE.
// THREAD A HAMMER atomic_a. THREAD B HAMMER atomic_b. SAME CACHE LINE. BAD.
// ATOMIC NOT HELP WITH FALSE SHARING. ATOMIC PREVENT DATA RACE BUT NOT PING PONG.
// EXPECTED: H3 on struct atomic_pair
// WHY H3: ADJACENT _Atomic FIELDS FROM DIFFERENT THREADS = KNOWN PATTERN.
// NOTE: TIER-1 DOES NOT IMPLEMENT H3. THIS CASE DOCUMENTS A COVERAGE GAP.
//       TIER-1 ALSO CANNOT DETECT atomic STORE (store atomic != plain store).
//       FINDING WILL BE ABSENT. VERDICT = MISS (FN). NOT A TIER-1 BUG, A GAP.

#include <stdatomic.h>
#include <pthread.h>

struct atomic_pair {
    _Atomic long a;   // FIELD 0. OFFSET 0. THREAD A HIT THIS.
    _Atomic long b;   // FIELD 1. OFFSET 8. THREAD B HIT THIS. SAME LINE.
};

struct atomic_pair ap = {0, 0};  // SINGLE GLOBAL INSTANCE.

void *thread_a(void *arg) {
    // GROK ATOMICALLY INCREMENT a. CACHE LINE OWNED BY a BUT b ALSO THERE.
    struct atomic_pair *p = (struct atomic_pair *)arg;
    for (int i = 0; i < 1000000; i++) {
        atomic_fetch_add(&p->a, 1);
    }
    return NULL;
}

void *thread_b(void *arg) {
    // GROK ATOMICALLY INCREMENT b. SHARE LINE WITH a. LINE BOUNCE BETWEEN CORES.
    struct atomic_pair *p = (struct atomic_pair *)arg;
    for (int i = 0; i < 1000000; i++) {
        atomic_fetch_add(&p->b, 1);
    }
    return NULL;
}

int main(void) {
    pthread_t t1, t2;
    pthread_create(&t1, NULL, thread_a, &ap);
    pthread_create(&t2, NULL, thread_b, &ap);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    return 0;
}
