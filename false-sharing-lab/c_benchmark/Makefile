CC = gcc
CFLAGS = -O2 -Wall -pthread
TARGET = benchmark

all: $(TARGET)

$(TARGET): false_sharing.c
	$(CC) $(CFLAGS) -o $(TARGET) false_sharing.c

clean:
	rm -f $(TARGET)
