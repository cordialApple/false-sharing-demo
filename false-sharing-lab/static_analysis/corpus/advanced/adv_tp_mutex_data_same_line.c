// SCENARIO: MUTEX AND DATA SHARE CACHE LINE. MUTEX LOCK WORD AT OFFSET 0.
// COUNTER AT OFFSET 40. BOTH IN BUCKET 0 (0-63). THREAD LOCK MUTEX THEN
// WRITE COUNTER. LOCK WORD AND COUNTER PING-PONG.
// REAL WORLD: CLASSIC KERNEL/GLIBC ANTI-PATTERN. LOCK AND COUNTER IN SAME STRUCT.
// EXPECTED: H1/MEDIUM (struct mutex_counter_t, fields m and counter same bucket)
// WHY: SIZEOF(pthread_mutex_t)=40, COUNTER AT OFFSET 40, BOTH IN [0..63].
//      TWO THREAD-WRITTEN FIELDS SAME LINE.

#include <pthread.h>

typedef struct {
    pthread_mutex_t m;   // OFFSET 0. SIZE 40. MUTEX LOCK WORD HERE.
    long counter;        // OFFSET 40. SAME 64B LINE AS MUTEX INTERNALS.
} mutex_counter_t;

mutex_counter_t g = {PTHREAD_MUTEX_INITIALIZER, 0};

void *thread_a(void *arg) {
    mutex_counter_t *p = (mutex_counter_t *)arg;
    for (int i = 0; i < 1000000; i++) {
        pthread_mutex_lock(&p->m);
        p->counter++;
        pthread_mutex_unlock(&p->m);
    }
    return NULL;
}

void *thread_b(void *arg) {
    mutex_counter_t *p = (mutex_counter_t *)arg;
    for (int i = 0; i < 1000000; i++) {
        pthread_mutex_lock(&p->m);
        p->counter++;
        pthread_mutex_unlock(&p->m);
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
