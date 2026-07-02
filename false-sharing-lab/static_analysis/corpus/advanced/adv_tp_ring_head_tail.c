// SCENARIO: SPSC RING BUFFER. PRODUCER WRITE head (OFFSET 0). CONSUMER WRITE
// tail (OFFSET 8). BOTH IN SAME 64B CACHE LINE. CLASSIC QUEUE FALSE SHARING.
// REAL WORLD: LMAX DISRUPTOR / folly ProducerConsumerQueue PAD THESE WITH
//             hardware_destructive_interference_size TO FIX.
// EXPECTED: H1/MEDIUM (fields head and tail, offsets 0 and 8, same bucket 0)
// WHY: head AT OFFSET 0, tail AT OFFSET 8. BOTH IN [0..63]. DIFFERENT THREADS
//      WRITE DIFFERENT FIELDS. CLASSIC SPSC ANTI-PATTERN.

#include <pthread.h>

#define BUF_SIZE 256

typedef struct {
    unsigned long head;   // OFFSET 0. PRODUCER WRITE THIS.
    unsigned long tail;   // OFFSET 8. CONSUMER WRITE THIS. SAME LINE AS head!
    char buf[BUF_SIZE];   // OFFSET 16. RING BUFFER DATA.
} spsc_ring_t;

static spsc_ring_t ring = {0, 0, {0}};

void *producer(void *arg) {
    spsc_ring_t *r = (spsc_ring_t *)arg;
    for (unsigned long i = 0; i < 1000000; i++) {
        r->buf[r->head % BUF_SIZE] = (char)i;
        r->head++;   // WRITE head. OFFSET 0. BUCKET 0.
    }
    return NULL;
}

void *consumer(void *arg) {
    spsc_ring_t *r = (spsc_ring_t *)arg;
    volatile char sink = 0;
    while (r->tail < 1000000) {
        sink = r->buf[r->tail % BUF_SIZE];
        r->tail++;   // WRITE tail. OFFSET 8. BUCKET 0. SAME LINE AS head!
    }
    (void)sink;
    return NULL;
}

int main(void) {
    pthread_t tp, tc;
    pthread_create(&tp, NULL, producer, &ring);
    pthread_create(&tc, NULL, consumer, &ring);
    pthread_join(tp, NULL);
    pthread_join(tc, NULL);
    return 0;
}
