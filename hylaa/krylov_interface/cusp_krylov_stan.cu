// Dung Tran & Stanley Bak
// Krylov subspace - based simulation using Gpu- Cusp / Cuda for sparse ode
// June 2017

#include <new>
#include <stdio.h>
#include <stdlib.h>
#include <cusp/array1d.h>
#include <cusp/coo_matrix.h>
#include <cusp/csr_matrix.h>
#include <cusp/multiply.h>
#include <cusp/print.h>
#include <sys/time.h>
#include "gpu_util.h"

typedef double FLOAT_TYPE;

template <class MEMORY_TYPE>
class CuspData
{
    typedef cusp::array1d<FLOAT_TYPE, MEMORY_TYPE> Array1d;
    typedef typename Array1d::view Array1dView;

    typedef cusp::array2d<FLOAT_TYPE, MEMORY_TYPE> Array2d;
    typedef typename Array2d::view Array2dView;

    typedef cusp::array1d<FLOAT_TYPE, cusp::host_memory> HostFloatArray1d;
    typedef typename HostFloatArray1d::view HostFloatArray1dView;

    typedef cusp::array1d<int, cusp::host_memory> HostIntArray1d;
    typedef typename HostIntArray1d::view HostIntArray1dView;

    typedef cusp::csr_matrix<int, FLOAT_TYPE, MEMORY_TYPE> CsrMatrix;

    typedef cusp::csr_matrix<int, FLOAT_TYPE, cusp::host_memory> HostCsrMatrix;
    typedef typename HostCsrMatrix::view HostCsrMatrixView;

   public:
    GpuUtil util;  // timers and other utility functions

    CsrMatrix* aMatrix;
    CsrMatrix* keyDirMatrix;

    Array1d* vMatrix;     // p * [(i+1) * n]
    Array1d* hMatrix;     // p * [(i+1) * i]
    Array1d* vProjected;  // p * [k * (i+1)]

    unsigned long _n;  // number of dimensions in the system
    unsigned long _k;  // number of key directions
    unsigned long _i;  // number of arnoldi iterations
    unsigned long _p;  // number of parallel initial vectors in arnoldi

    // profiling variables
    bool useProfiling;
    int aMatrixNonzeros;
    int keyDirMatrixNonzeros;

    CuspData(bool useCpu) : util(useCpu)
    {
        aMatrix = 0;
        keyDirMatrix = 0;

        vMatrix = 0;
        hMatrix = 0;
        vProjected = 0;

        reset();  // this resets all variables
    }

    ~CuspData() { reset(); }

    void reset()
    {
        if (aMatrix != 0)
        {
            delete aMatrix;
            aMatrix = 0;
        }

        if (keyDirMatrix != 0)
        {
            delete keyDirMatrix;
            keyDirMatrix = 0;
        }

        if (vMatrix != 0)
        {
            delete vMatrix;
            vMatrix = 0;
        }

        if (hMatrix != 0)
        {
            delete hMatrix;
            hMatrix = 0;
        }

        if (vProjected != 0)
        {
            delete vProjected;
            vProjected = 0;
        }

        util.clearTimers();

        _n = 0;
        _k = 0;
        _i = 0;
        _p = 0;

        setUseProfiling(false);
        aMatrixNonzeros = 0;
        keyDirMatrixNonzeros = 0;
    }

    void setUseProfiling(bool enabled)
    {
        useProfiling = enabled;
        util.setUseProfiling(enabled);
    }

    // load A matrix, passed in as a csr matrix
    void loadAMatrix(int w, int h, int* rowOffsets, int rowOffsetsLen, int* colInds, int colIndsLen,
                     FLOAT_TYPE* values, int valuesLen)
    {
        if (w != h)
            error("loadAMatrix() expected square A matrix, got w=%d, h=%d", w, h);

        if (useProfiling)
            printf("loadAMatrix() with sparse matrix size: %.2f MB (%d nonzeros)\n",
                   valuesLen * (8 + 4 + 4) / 1024.0 / 1024.0, valuesLen);

        _n = w;
        aMatrixNonzeros = valuesLen;

        HostIntArray1dView rowOffsetsView(rowOffsets, rowOffsets + rowOffsetsLen);
        HostIntArray1dView colIndsView(colInds, colInds + colIndsLen);
        HostFloatArray1dView valuesView(values, values + colIndsLen);

        HostCsrMatrixView view(_n, _n, valuesLen, rowOffsetsView, colIndsView, valuesView);

        if (aMatrix != 0)
        {
            delete aMatrix;
            aMatrix = 0;
        }

        aMatrix = new (std::nothrow) CsrMatrix(view);

        if (aMatrix == 0)
            error("memory allocation of aMatrix returned nullptr\n");
    }

    // load key dir matrix, passed in as a csr matrix
    void loadKeyDirMatrix(unsigned long w, unsigned long h, int* rowOffsets, int rowOffsetsLen, int* colInds,
                          int colIndsLen, FLOAT_TYPE* values, int valuesLen)
    {
        if (w != _n)
            error("in loadKeyDirMatrix() width (%lu) to equal dims (%lu)", w, _n);

        if (useProfiling)
            printf("loadKeyDirMatrix() with dense matrix size: %.2f MB\n",
                   w * h * (8 + 4 + 4) / 1024.0 / 1024.0);

        _k = h;
        keyDirMatrixNonzeros = valuesLen;

        HostIntArray1dView rowOffsetsView(rowOffsets, rowOffsets + rowOffsetsLen);
        HostIntArray1dView colIndsView(colInds, colInds + colIndsLen);
        HostFloatArray1dView valuesView(values, values + colIndsLen);

        HostCsrMatrixView view(h, w, valuesLen, rowOffsetsView, colIndsView, valuesView);

        if (keyDirMatrix != 0)
        {
            delete keyDirMatrix;
            keyDirMatrix = 0;
        }

        keyDirMatrix = new (std::nothrow) CsrMatrix(view);

        if (keyDirMatrix == 0)
            error("memory allocation of keyDirMatrix() returned nullptr\n");
    }

    double getFreeMemoryMb()
    {
        unsigned long bytes = util.getFreeMemory();

        return bytes / 1024.0 / 1024.0;
    }

    // frees memory if it was previously allocated, returns false if memory error occurs
    bool preallocateMemory(int arnoldiIt, int numParallelInit)
    {
        if (_n == 0)
            error("preallocateMemory() called before loadAMatrix() (_n==0)\n");

        if (_k == 0)
            error("preallocateMemory() called before loadKeyDirMatrix() (_k==0)\n");

        _i = arnoldiIt;
        _p = numParallelInit;

        // preallocate vMatrix, width = dims * iterations, height = numParInit
        if (vMatrix != 0)
        {
            delete vMatrix;
            vMatrix = 0;
        }

        unsigned long vMatrixSize = _p * _n * (_i + 1);
        vMatrix = new (std::nothrow) Array1d(vMatrixSize, 0);

        // preallocate hMatrix, numParInit * iterations * iterations
        if (hMatrix != 0)
        {
            delete hMatrix;
            hMatrix = 0;
        }

        unsigned long hMatrixSize = _p * _i * (_i + 1);
        hMatrix = new (std::nothrow) Array1d(hMatrixSize, 0);

        // preallocate vProjected
        if (vProjected != 0)
        {
            delete vProjected;
            vProjected = 0;
        }

        unsigned long vProjectedSize = _p * _k * (_i + 1);
        vProjected = new (std::nothrow) Array1d(vProjectedSize, 0);

        bool success = vMatrix != 0 && hMatrix != 0 && vProjected != 0;

        if (!success)
        {
            _i = 0;
            _p = 0;
        }

        return success;
    }

    void initParallelArnoldi(unsigned long startDim, unsigned long numInitVecs)
    {
        util.tic("init parallel");

        if (startDim + numInitVecs > _n)
            error("initParallelArnoldiV called with startDim=%lu, numInitVecs=%lu, but dims=%lu",
                  startDim, numInitVecs, _n);

        // fill with zeros
        cusp::blas::fill(*vMatrix, 0.0);

        unsigned long rowWidth = _n * (_i + 1);

        for (unsigned long rowNum = 0; rowNum < (unsigned long)numInitVecs; ++rowNum)
        {
            // initialize the "1.0" in each row
            unsigned long rowOffset = rowNum * rowWidth;

            (*vMatrix)[rowOffset + startDim + rowNum] = 1.0;
        }

        // also fill h with zeros
        cusp::blas::fill(*hMatrix, 0.0);

        // also fill projected vMatrix with zeros
        cusp::blas::fill(*vProjected, 0.0);

        util.toc("init parallel");
    }

    // reads/writes from/to vMatrix, writes to hMatrix
    void runArnoldi(unsigned long iterations, unsigned long numInitVecs)
    {
        // Arnoldi parallel algorithm iteration
        for (unsigned long it = 1; it <= iterations; it++)
        {
            // do all the multiplications up front
            util.tic("sparse matrix vector multiply total");
            for (unsigned long curInitVec = 0; curInitVec < numInitVecs; ++curInitVec)
            {
                unsigned long pageOffset = curInitVec * _n * (iterations + 1);

                unsigned long prevRowOffset = _n * (it - 1);
                unsigned long curRowOffset = _n * it;

                Array1dView vecView = vMatrix->subarray(pageOffset + prevRowOffset, _n);
                Array1dView resultView = vMatrix->subarray(pageOffset + curRowOffset, _n);

                util.tic("sparse matrix vector multiply");
                cusp::multiply(*aMatrix, vecView, resultView);
                util.toc("sparse matrix vector multiply", 2 * aMatrixNonzeros);
            }
            util.toc("sparse matrix vector multiply total", 2 * aMatrixNonzeros * numInitVecs);

            util.tic("dots total");
            // do all the dot products
            for (unsigned long curInitVec = 0; curInitVec < numInitVecs; ++curInitVec)
            {
                unsigned long pageOffset = curInitVec * _n * (iterations + 1);
                unsigned long rowOffset = _n * it;

                Array1dView vecView = vMatrix->subarray(pageOffset + rowOffset, _n);
                Array1dView matView1d = vMatrix->subarray(pageOffset, rowOffset);
                Array2dView matView2d = make_array2d_view(it, _n, _n, matView1d, cusp::row_major());

                pageOffset = curInitVec * (_i + 1) * _i;
                rowOffset = (it - 1) * (_i + 1);
                Array1dView resultView = hMatrix->subarray(pageOffset + rowOffset, it);

                util.tic("dense_multiply");
                dense_multiply(&matView2d, &vecView, &resultView);
                util.toc("dense_multiply", 2 * _n * it);
            }
            util.toc("dots total", 2 * _n * it * numInitVecs);

            util.tic("axpy total");
            // now scale each of the vecs by the computed dot products and subtract from curvec
            for (unsigned long prevVecIndex = 0; prevVecIndex < it; ++prevVecIndex)
            {
                for (unsigned long curInitVec = 0; curInitVec < numInitVecs; ++curInitVec)
                {
                    unsigned long pageOffset = curInitVec * _n * (iterations + 1);
                    unsigned long rowOffset = _n * it;

                    Array1dView curVec = vMatrix->subarray(pageOffset + rowOffset, _n);

                    rowOffset = _n * prevVecIndex;
                    Array1dView prevVec = vMatrix->subarray(pageOffset + rowOffset, _n);

                    // get the dot result
                    pageOffset = curInitVec * (_i + 1) * _i;
                    rowOffset = (it - 1) * (_i + 1);
                    double dotResult = (*hMatrix)[pageOffset + rowOffset + prevVecIndex];

                    // subtract dots * prevVec from curVec
                    util.tic("axpy");
                    cusp::blas::axpy(prevVec, curVec, -dotResult);
                    util.toc("axpy", 2 * _n);
                }
            }
            util.toc("axpy total");

            util.tic("magnitude and scale");
            for (unsigned long curInitVec = 0; curInitVec < numInitVecs; ++curInitVec)
            {
                unsigned long pageOffset = curInitVec * _n * (iterations + 1);
                unsigned long rowOffset = _n * it;

                Array1dView curVec = vMatrix->subarray(pageOffset + rowOffset, _n);

                double magnitude = cusp::blas::nrm2(curVec);

                // store magnitude in H
                pageOffset = curInitVec * (_i + 1) * _i;
                rowOffset = (it - 1) * (_i + 1);
                (*hMatrix)[pageOffset + rowOffset + it] = magnitude;

                // scale vector
                if (magnitude < 1e-10)
                    cusp::blas::scal(curVec, 0.0);
                else
                    cusp::blas::scal(curVec, 1.0 / magnitude);
            }
            util.toc("magnitude and scale");
        }
    }

    void projectV(unsigned long iterations, unsigned long numInitVecs)
    {
        // use vMatrix and keyDirMatrix to produce vProjected
        for (unsigned long iteration = 0; iteration <= iterations; ++iteration)
        {
            for (unsigned long curInitVec = 0; curInitVec < numInitVecs; ++curInitVec)
            {
                unsigned long pageOffset = curInitVec * _n * (iterations + 1);
                unsigned long rowOffset = _n * (iteration);

                Array1dView vecView = vMatrix->subarray(pageOffset + rowOffset, _n);

                // result view is in vProjected
                pageOffset = curInitVec * _k * (iterations + 1);
                rowOffset = _k * iteration;

                Array1dView resultView = vProjected->subarray(pageOffset + rowOffset, iterations);

                util.tic("project-v sparse matrix vector multiply");
                cusp::multiply(*keyDirMatrix, vecView, resultView);
                util.toc("project-v sparse matrix vector multiply", 2 * keyDirMatrixNonzeros);
            }
        }
    }

    void arnoldiParallel(unsigned long startDim, double* resultH, unsigned long sizeResultH, double* resultPV,
                         unsigned long sizeResultPV)
    {
        if (_n == 0)
            error("arnoldiParallel() called before loadAMatrix() (_n==0)\n");

        if (_k == 0)
            error("arnoldiParrallel() called before loadKeyDirMatrix() (_k==0)\n");

        if (_i == 0 || _p == 0)
            error("arnoldiParrallel() called before preallocate() (_i==0 or _p==0)\n");

        // check expected results sizes
        unsigned long expectedH = _p * _i * (_i + 1);
        unsigned long expectedPV = _p * (_i + 1) * _k;

        if (sizeResultH != expectedH)
            error("Wrong size for resultH with i = %lu. Got %lu, expected %lu.", _i, sizeResultH,
                  expectedH);

        if (sizeResultPV != expectedPV)
            error("Wrong size for resultPV with (i, p, k) = (%lu, %lu, %lu). Got %d, expected %d.", _i,
                  _p, _k, sizeResultPV, expectedPV);

        if (startDim >= _n)
            error("invalid startDim in arnoldi (%lu dim system): %lu", _n, startDim);

        util.tic("arnoldi parallel total");

        int parInitVecs = _p;

        if (startDim + parInitVecs > _n)
            parInitVecs = _n - startDim;

        initParallelArnoldi(startDim, parInitVecs);

        util.tic("runArnoldi()");
        runArnoldi(_i, parInitVecs);
        util.toc("runArnoldi()");

        // project v_matrix onto keyDirMatrix
        util.tic("projectV()");
        projectV(_i, parInitVecs);
        util.toc("projectV()");

        // copying H matrix to np.ndarray
        util.tic("copying H matrix to np.ndarray");
        HostFloatArray1dView hostHView(resultH, resultH + expectedH);
        cusp::blas::copy(*hMatrix, hostHView);  // hostHView = *hMatrix
        util.toc("copying H matrix to np.ndarray");

        // copy vProjected to np.ndarray

        util.tic("copying V-projected matrix to np.ndarray");
        HostFloatArray1dView hostPVView(resultPV, resultPV + expectedPV);
        cusp::blas::copy(*vProjected, hostPVView);  // hostPVView = *vProjected
        util.toc("copying V-projected matrix to np.ndarray");

        util.toc("arnoldi parallel total");
        util.printTimers();
        util.clearTimers();
    }

   private:
    void dense_multiply(Array2dView* mat, Array1dView* vec, Array1dView* result)
    {
        if (mat->pitch != vec->size())
            error("in dense_multiply(), mat.width (%lu) != vec.size (%lu)", mat->pitch,
                  vec->size());

        if (mat->values.size() / mat->pitch != result->size())
            error("in dense_multiply(), mat.height (%lu) != result.size (%lu)",
                  mat->values.size() / mat->pitch, result->size());

        int size = result->size();

        for (int row = 0; row < size; ++row)
        {
            Array1dView rowView = mat->row(row);

            (*result)[row] = cusp::blas::dot(rowView, *vec);
        }

        // only implemented on CPU:
        // cusp::multiply(*mat, *vec, *result);

        // not implemented anywhere in cusp 5.0.1:
        // cusp::blas::gemv(*mat, *vec, *result);
    }

    void printV()
    {
        unsigned long h = _p * (_i + 1);
        unsigned long w = _n;

        cusp::print(make_array2d_view(h, w, w, Array1dView(*vMatrix), cusp::row_major()));
    }

    void printH()
    {
        unsigned long h = _p * (_i + 1);
        unsigned long w = _i;

        cusp::print(make_array2d_view(h, w, w, Array1dView(*hMatrix), cusp::row_major()));
    }
};

CuspData<cusp::host_memory> cuspDataCpu(true);
CuspData<cusp::device_memory> cuspDataGpu(false);

extern "C" {
int hasGpu()
{
    return cuspDataGpu.util.hasGpu();
}

void reset()
{
    cuspDataCpu.reset();
    cuspDataGpu.reset();
}

////// CPU Version
void setUseProfilingCpu(int enabled)
{
    cuspDataCpu.setUseProfiling(enabled != 0);
}

// as csr matrix
void loadAMatrixCpu(int w, int h, int* rowOffsets, int rowOffsetsLen, int* colInds, int colIndsLen,
                    double* values, int valuesLen)
{
    cuspDataCpu.loadAMatrix(w, h, rowOffsets, rowOffsetsLen, colInds, colIndsLen, values,
                            valuesLen);
}

void loadKeyDirMatrixCpu(int w, int h, int* rowOffsets, int rowOffsetsLen, int* colInds,
                         int colIndsLen, double* values, int valuesLen)
{
    cuspDataCpu.loadKeyDirMatrix(w, h, rowOffsets, rowOffsetsLen, colInds, colIndsLen, values,
                                 valuesLen);
}

double getFreeMemoryMbCpu()
{
    return cuspDataCpu.getFreeMemoryMb();
}

int preallocateMemoryCpu(int arnoldiIt, int numParallelInitVecs)
{
    return cuspDataCpu.preallocateMemory(arnoldiIt, numParallelInitVecs) ? 1 : 0;
}

void arnoldiParallelCpu(int startDim, double* resultH, int sizeResultH, double* resultPV,
                        int sizeResultPV)
{
    cuspDataCpu.arnoldiParallel(startDim, resultH, sizeResultH, resultPV, sizeResultPV);
}

////// GPU Version
void setUseProfilingGpu(int enabled)
{
    cuspDataGpu.setUseProfiling(enabled != 0);
}

// as csr matrix
void loadAMatrixGpu(int w, int h, int* rowOffsets, int rowOffsetsLen, int* colInds, int colIndsLen,
                    double* values, int valuesLen)
{
    cuspDataGpu.loadAMatrix(w, h, rowOffsets, rowOffsetsLen, colInds, colIndsLen, values,
                            valuesLen);
}

// as csr matrix
void loadKeyDirMatrixGpu(int w, int h, int* rowOffsets, int rowOffsetsLen, int* colInds,
                         int colIndsLen, double* values, int valuesLen)
{
    cuspDataGpu.loadKeyDirMatrix(w, h, rowOffsets, rowOffsetsLen, colInds, colIndsLen, values,
                                 valuesLen);
}

double getFreeMemoryMbGpu()
{
    return cuspDataGpu.getFreeMemoryMb();
}

int preallocateMemoryGpu(int arnoldiIterations, int numParallelInitVecs)
{
    return cuspDataGpu.preallocateMemory(arnoldiIterations, numParallelInitVecs) ? 1 : 0;
}

void arnoldiParallelGpu(int startDim, double* resultH, int sizeResultH, double* resultPV,
                        int sizeResultPV)
{
    cuspDataGpu.arnoldiParallel(startDim, resultH, sizeResultH, resultPV, sizeResultPV);
}
}
