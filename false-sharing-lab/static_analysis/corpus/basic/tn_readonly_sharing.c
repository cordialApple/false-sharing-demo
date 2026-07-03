// TN READONLY SHARING
// THREADS ONLY READ SHARED DATA. NO WRITES TO SHARED MEMORY.
// THREADS MAY READ FROM ADJACENT LOCATIONS (SAME CACHE LINE).
// BUT READ-ONLY SHARING DOES NOT CAUSE FALSE SHARING. READERS NEVER DIRTY LINE.
// EXPECTED: CLEAN (no findings)
// WHY: ir_analyzer H1/H2 CHECK FOR store INSTRUCTIONS IN THREAD CODE.
//      THREADS ONLY DO load. NO store TO SHARED PTR. NO FIELD STORE MATCH.
//      NO STRUCT GEP WITH VARIABLE INDEX IN THREAD. H4 ALSO DOES NOT FIRE.

#include <pthread.h>

// ADJACENT LONGS. SAME CACHE LINE. BUT THREADS ONLY READ THEM.
long shared_data[2] = {42, 99};

void *reader(void *arg) {
    // THREAD. RECEIVE POINTER TO ONE ELEMENT. ONLY READ.
    long *p = (long *)arg;
    long local_sum = 0;
    for (int i = 0; i < 1000000; i++) {
        local_sum += *p;  // LOAD ONLY. NO STORE TO SHARED MEMORY.
    }
    // WRITE ONLY TO LOCAL STACK VARIABLE. NOT SHARED.
    return (void *)local_sum;
}

int main(void) {
    // PASS POINTERS TO ADJACENT ELEMENTS. THREADS READ SAME CACHE LINE.
    // BUT BOTH ARE READERS. NO FALSE SHARING.
    pthread_t t1, t2;
    pthread_create(&t1, NULL, reader, &shared_data[0]);
    pthread_create(&t2, NULL, reader, &shared_data[1]);
    pthread_join(t1, NULL);
    pthread_join(t2, NULL);
    return 0;
}
