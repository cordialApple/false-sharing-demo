#include <stdio.h>
#include <stdlib.h>
#include <pthread.h>
#include <time.h>

#define NUM_ITERATIONS 500000000
#define CACHE_LINE_SIZE 64

typedef struct {
    long long value;
} unpadded_counter_t;

typedef struct {
    long long value;
    char padding[CACHE_LINE_SIZE - sizeof(long long)];
} padded_counter_t;

unpadded_counter_t *unpadded_counters;
padded_counter_t *padded_counters;

int num_threads;

void *worker_unpadded(void *arg) {
    int tid = *(int *)arg;
    for (long long i = 0; i < NUM_ITERATIONS / num_threads; i++) {
        unpadded_counters[tid].value++;
    }
    return NULL;
}

void *worker_padded(void *arg) {
    int tid = *(int *)arg;
    for (long long i = 0; i < NUM_ITERATIONS / num_threads; i++) {
        padded_counters[tid].value++;
    }
    return NULL;
}

double get_time_sec() {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec + ts.tv_nsec / 1e9;
}

int main(int argc, char *argv[]) {
    if (argc != 2) {
        fprintf(stderr, "Usage: %s <num_threads>\n", argv[0]);
        return 1;
    }

    num_threads = atoi(argv[1]);
    if (num_threads <= 0) {
        fprintf(stderr, "Number of threads must be > 0\n");
        return 1;
    }

    unpadded_counters = malloc(sizeof(unpadded_counter_t) * num_threads);
    padded_counters = malloc(sizeof(padded_counter_t) * num_threads);

    for (int i = 0; i < num_threads; i++) {
        unpadded_counters[i].value = 0;
        padded_counters[i].value = 0;
    }

    pthread_t *threads = malloc(sizeof(pthread_t) * num_threads);
    int *tids = malloc(sizeof(int) * num_threads);

    // Unpadded benchmark
    double start = get_time_sec();
    for (int i = 0; i < num_threads; i++) {
        tids[i] = i;
        pthread_create(&threads[i], NULL, worker_unpadded, &tids[i]);
    }
    for (int i = 0; i < num_threads; i++) {
        pthread_join(threads[i], NULL);
    }
    double end = get_time_sec();
    double unpadded_time = end - start;

    // Padded benchmark
    start = get_time_sec();
    for (int i = 0; i < num_threads; i++) {
        pthread_create(&threads[i], NULL, worker_padded, &tids[i]);
    }
    for (int i = 0; i < num_threads; i++) {
        pthread_join(threads[i], NULL);
    }
    end = get_time_sec();
    double padded_time = end - start;

    FILE *fp = fopen("../results/benchmark_results.csv", "a");
    if (!fp) {
        perror("Failed to open results CSV");
        return 1;
    }

    fprintf(fp, "unpadded,%d,%.6f\n", num_threads, unpadded_time);
    fprintf(fp, "padded,%d,%.6f\n", num_threads, padded_time);

    fclose(fp);

    free(unpadded_counters);
    free(padded_counters);
    free(threads);
    free(tids);

    return 0;
}
