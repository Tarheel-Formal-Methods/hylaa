// Stanley Bak
// Aug 2017
// GPU FLOPS measurement

#include <stdlib.h>
#include <stdio.h>
#include <sys/time.h>
#include <thread>
#include <vector>

#include <cusp/hyb_matrix.h>
#include <cusp/coo_matrix.h>
#include <cusp/multiply.h>
#include <cusp/print.h>

using namespace std;

long now() {
  struct timeval nowUs;

  if (gettimeofday(&nowUs, 0)) {
    perror("gettimeofday");
    exit(1);
  }

  return 1000000l * nowUs.tv_sec + nowUs.tv_usec;
}

typedef float FLOAT_TYPE;
typedef cusp::device_memory MEMORY_TYPE;

typedef cusp::array1d<FLOAT_TYPE, MEMORY_TYPE> Array1d;
typedef typename Array1d::view Array1dView;

void task(Array1dView result, int y, Array1dView matRow, Array1dView vecView) {
  result[y] = cusp::blas::dot(matRow, vecView);
}

void measure(const char *label, int height, int width) {
  printf("making...\n");

  cusp::array1d<FLOAT_TYPE, cusp::host_memory> hostMat(height * width);
  cusp::array1d<FLOAT_TYPE, cusp::host_memory> hostVec(width);

  for (int y = 0; y < height; ++y)
    for (int x = 0; x < width; ++x)
      hostMat[y * width + x] = rand() / 100.0;

  for (int x = 0; x < width; ++x)
    hostVec[x] = rand() / 100.0;

  cusp::array1d<FLOAT_TYPE, MEMORY_TYPE> mat(hostMat);
  cusp::array1d<FLOAT_TYPE, MEMORY_TYPE> vec(hostVec);
  cusp::array1d<FLOAT_TYPE, MEMORY_TYPE> result(height);

  Array1dView resultView(result);
  Array1dView vecView(vec);

  printf("starting...\n");
  long start = now();

  vector<thread> threads;

  for (int y = 0; y < height; ++y) {
    Array1dView matRow = mat.subarray(y * width, width);

    // threads.push_back(thread(task, resultView, y, matRow, vecView));
    task(resultView, y, matRow, vecView);

    // result[y] = cusp::blas::dot(matRow, vec);
  }

  for (int i = 0; i < (int)threads.size(); ++i)
    threads[i].join();

  long elapsed = now() - start;

  long ops = 2 * mat.size();
  float gflops = ops / elapsed / 1000.0;

  printf("%s Elapsed time: %.2f ms (%.3f GFLOPS)\n", label, elapsed / 1000.0,
         gflops);
}

int main(int argc, char **argv) {
  srand(0);

  int h = 10;
  int w = 1000;

  if (argc == 3) {
    h = atoi(argv[1]);
    w = atoi(argv[2]);
  }

  printf("Running with h=%d, w=%d\n", h, w);

  measure("CPU", h, w);

  // measure<cusp::device_memory>("GPU", h, w);

  return 0;
}
