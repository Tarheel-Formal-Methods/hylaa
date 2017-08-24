'''
Dung Tran & Stanley Bak
August 2017


Simulation of linear system x' = Ax using krylov supspace method in CPU and GPU
'''

import ctypes
import os

import numpy as np
from numpy.ctypeslib import ndpointer
from hylaa.util import Freezable, get_script_path
from scipy.sparse import csr_matrix

class CuspData(Freezable):
    'Function pointers / data for gpu or cpu'

    def __init__(self):
        self.set_use_profiling = None
        self.load_a_matrix = None
        self.load_key_dir_matrix = None
        self.get_free_memory_mb = None
        self.preallocate_memory = None
        self.arnoldi_parallel = None

        self.n = 0 # dimensions of a matrix
        self.k = 0 # number of key directions
        self.i = 0 # number of iterations
        self.p = 0 # number of parallel initial vectors

        self.freeze_attrs()

class KrylovInterface(object):
    'GPU (and CPU) interface for Krylov subspace simulations of a linear system'

    # static member (library)
    _lib = None
    _lib_path = os.path.join(get_script_path(__file__), 'krylov_interface', 'cusp_krylov_stan.so')

    def __init__(self):
        raise RuntimeError(
            'KrylovInterface is a static class and should not be instantiated')

    @staticmethod
    def _init_static():
        'open the library (if not opened already) and initialize the static members'

        if KrylovInterface._lib is None:

            KrylovInterface._lib = lib = ctypes.CDLL(KrylovInterface._lib_path)

            # int hasGpu()
            KrylovInterface._has_gpu = lib.hasGpu
            KrylovInterface._has_gpu.restype = ctypes.c_int
            KrylovInterface._has_gpu.argtypes = None

            # void reset()
            KrylovInterface._reset = lib.reset
            KrylovInterface._reset.restype = None
            KrylovInterface._reset.argtypes = None

            # CPU and GPU container objects... _funcs stores the selected version
            KrylovInterface._cpu = CuspData()
            KrylovInterface._gpu = CuspData()
            KrylovInterface._cusp = KrylovInterface._cpu # can be changed programatically

            #void setUseProfilingCpu(int enabled)
            cpu_func = KrylovInterface._cpu.set_use_profiling = lib.setUseProfilingCpu
            gpu_func = KrylovInterface._gpu.set_use_profiling = lib.setUseProfilingGpu
            gpu_func.restype = cpu_func.restype = None
            gpu_func.argtypes = cpu_func.argtypes = [ctypes.c_int]

            #void loadAMatrixGpu(int w, int h, int* rowOffsets, int rowOffsetsLen, int* colInds, int colIndsLen,
            #        double* values, int valuesLen)
            cpu_func = KrylovInterface._cpu.load_a_matrix = lib.loadAMatrixCpu
            gpu_func = KrylovInterface._gpu.load_a_matrix = lib.loadAMatrixGpu
            gpu_func.restype = cpu_func.restype = None
            gpu_func.argtypes = cpu_func.argtypes = [
                ctypes.c_int, ctypes.c_int,
                ndpointer(ctypes.c_int, flags="C_CONTIGUOUS"), ctypes.c_int,
                ndpointer(ctypes.c_int, flags="C_CONTIGUOUS"), ctypes.c_int,
                ndpointer(ctypes.c_double, flags="C_CONTIGUOUS"), ctypes.c_int
            ]

            # void loadKeyDirMatrixGpu(int w, int h, int* rowOffsets, int rowOffsetsLen, int* colInds,
            #                          int colIndsLen, double* values, int valuesLen)
            cpu_func = KrylovInterface._cpu.load_key_dir_matrix = lib.loadKeyDirMatrixCpu
            gpu_func = KrylovInterface._gpu.load_key_dir_matrix = lib.loadKeyDirMatrixGpu
            gpu_func.restype = cpu_func.restype = None
            gpu_func.argtypes = cpu_func.argtypes = [
                ctypes.c_int, ctypes.c_int,
                ndpointer(ctypes.c_int, flags="C_CONTIGUOUS"), ctypes.c_int,
                ndpointer(ctypes.c_int, flags="C_CONTIGUOUS"), ctypes.c_int,
                ndpointer(ctypes.c_double, flags="C_CONTIGUOUS"), ctypes.c_int
            ]

            # double getFreeMemoryMbCpu()
            cpu_func = KrylovInterface._cpu.get_free_memory_mb = lib.getFreeMemoryMbCpu
            gpu_func = KrylovInterface._gpu.get_free_memory_mb = lib.getFreeMemoryMbGpu
            gpu_func.restype = cpu_func.restype = ctypes.c_float
            gpu_func.argtypes = cpu_func.argtypes = None

            # int preallocateMemoryGpu(int arnoldiIterations, int numParallel)
            cpu_func = KrylovInterface._cpu.preallocate_memory = lib.preallocateMemoryCpu
            gpu_func = KrylovInterface._gpu.preallocate_memory = lib.preallocateMemoryGpu
            gpu_func.restype = cpu_func.restype = ctypes.c_int
            gpu_func.argtypes = cpu_func.argtypes = [
                ctypes.c_int, ctypes.c_int
            ]

            # void arnoldiParallelGpu(int startDim, double* resultH, int sizeResultH, double* resultPV,
            #            int sizeResultPV)
            cpu_func = KrylovInterface._cpu.arnoldi_parallel = lib.arnoldiParallelCpu
            gpu_func = KrylovInterface._gpu.arnoldi_parallel = lib.arnoldiParallelGpu
            gpu_func.restype = cpu_func.restype = None
            gpu_func.argtypes = cpu_func.argtypes = [
                ctypes.c_int, 
                ndpointer(ctypes.c_double, flags="C_CONTIGUOUS"), ctypes.c_int,
                ndpointer(ctypes.c_double, flags="C_CONTIGUOUS"), ctypes.c_int
            ]

            # initialize GPU ?

    @staticmethod
    def set_use_gpu(use_gpu):
        'set if the GPU should be used (false = CPU)'

        KrylovInterface._init_static()

        if use_gpu:
            assert KrylovInterface.has_gpu(), "set_use_gpu(True) called, but no GPU hardware was detected"

            KrylovInterface._cusp = KrylovInterface._gpu
        else:
            KrylovInterface._cusp = KrylovInterface._cpu

    @staticmethod
    def has_gpu():
        'is a GPU detected?'

        KrylovInterface._init_static()
        return KrylovInterface._has_gpu() != 0

    @staticmethod
    def reset():
        'reset BOTH gpu and cpu variables used in c code'

        KrylovInterface._init_static()
        KrylovInterface._reset()

    @staticmethod
    def get_free_memory_mb():
        'get the amount of free memory in megabytes'

        KrylovInterface._init_static()

        return KrylovInterface._cusp.get_free_memory_mb()

    @staticmethod
    def set_use_profiling(use_profiling):
        'set if timing profiling should be used'

        KrylovInterface._init_static()
        KrylovInterface._cusp.set_use_profiling(1 if use_profiling else 0)

    @staticmethod
    def load_a_matrix(matrix):
        'load dynamics A matrix (should be a csr sparse matrix)'

        KrylovInterface._init_static()
        h, w = matrix.shape

        assert isinstance(matrix, csr_matrix), "expected a_matrix to be csr_matrix, got {}".format(type(matrix))
        assert matrix.dtype == float
        assert w == h, "a matrix should be square"

        values = matrix.data
        row_offsets = matrix.indptr
        col_inds = matrix.indices

        KrylovInterface._cusp.n = w

        KrylovInterface._cusp.load_a_matrix(w, h, row_offsets, len(row_offsets), col_inds, len(col_inds), values,
                                            len(values))

    @staticmethod
    def load_key_dir_matrix(matrix):
        'load key direction sparse matrix'

        KrylovInterface._init_static()

        assert isinstance(matrix, csr_matrix)
        assert matrix.dtype == float

        values = matrix.data
        row_offsets = matrix.indptr
        col_inds = matrix.indices

        h, w = matrix.shape
        assert w == KrylovInterface._cusp.n, "key dir matrix width ({}) should equal number of dimensions ({})".format(
            w, KrylovInterface._cusp.n)

        KrylovInterface._cusp.k = h
        KrylovInterface._cusp.load_key_dir_matrix(w, h, row_offsets, len(row_offsets), col_inds, len(col_inds),
                                                  values, len(values))

    @staticmethod
    def preallocate_memory(arnoldi_iterations, parallel_init_vecs):
        '''
        preallocate memory used in the parallel arnoldi iteration
        returns True on sucess and False on (memory allocation) error
        '''

        KrylovInterface._init_static()

        KrylovInterface._cusp.i = arnoldi_iterations
        KrylovInterface._cusp.p = parallel_init_vecs

        result = KrylovInterface._cusp.preallocate_memory(arnoldi_iterations, parallel_init_vecs) != 0

        KrylovInterface._preallocated_memory = result
        KrylovInterface._arnoldi_iterations = arnoldi_iterations
        KrylovInterface._parallel_init_vecs = parallel_init_vecs

        return result

    @staticmethod
    def arnoldi_parallel(start_dim):
        '''
        Run the arnoldi algorithm in parallel for a certain number of orthonormal vectors
        Returns a tuple: (h_matrix, projected_v_matrix)

        h_matrix is of size (arnoldi_iter * (arnoldi_iter + 1)) x parallel_init_vecs
        projected_v_matrix is of size (init_vecs * parallel_init_vecs) x key_dirs

        The matrix may be partially assigned if start_dim + parallel_init_vecs > toal_dims
        '''

        KrylovInterface._init_static()

        # allocate results
        p = KrylovInterface._cusp.p
        k = KrylovInterface._cusp.k
        i = KrylovInterface._cusp.i

        result_h = np.zeros((i * (i + 1)), dtype=float)
        result_pv = np.zeros((i * p * k), dtype=float)

        KrylovInterface._cusp.arnoldi_parallel(start_dim, result_h, len(result_h), result_pv, len(result_pv))

        result_h.shape = (i, i+1)
        result_pv.shape = (i*p, k)

        return result_h, result_pv
