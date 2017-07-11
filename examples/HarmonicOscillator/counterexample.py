"Counter-example trace generated using HyLAA"

import sys
from numpy import array, int32
from scipy.sparse import csc_matrix
from hylaa.check_trace import check, plot

def check_instance():
    'define parameters for one instance and call checking function'

    data = array([-1.,  1.,  1.])
    indices = array([1, 0, 2], dtype=int32)
    indptr = array([0, 1, 2, 2, 3], dtype=int32)
    a_matrix = csc_matrix((data, indices, indptr), dtype=float, shape=(4, 4))
    data = array([ 1.,  1.])
    indices = array([0, 1], dtype=int32)
    indptr = array([0, 1, 2], dtype=int32)
    b_matrix = csc_matrix((data, indices, indptr), dtype=float, shape=(4, 2))
    inputs = []
    inputs += [[-0.5, 0.5]] * 2
    inputs += [[0.5, 0.5]] * 2
    step = 0.785398163397
    max_time = 3.14159265359

    start_point = array([-6.,  1.,  0.,  1.])
    normal_vec = array([-1.,  0.,  0.,  0.])
    normal_val = -7.5

    end_val = -8.0
    sim_states, sim_times = check(a_matrix, b_matrix, step, max_time, start_point, inputs, normal_vec, end_val)

    if len(sys.argv) < 2 or sys.argv[1] != "noplot":
        plot(sim_states, sim_times, inputs, normal_vec, normal_val, max_time, step)

if __name__ == "__main__":
    check_instance()
