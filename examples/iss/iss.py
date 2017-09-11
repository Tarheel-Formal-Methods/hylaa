'''
International Space Station Example in Hylaa-Continuous
'''

import numpy as np
from scipy.io import loadmat
from scipy.sparse import csr_matrix, csc_matrix

from hylaa.hybrid_automaton import LinearHybridAutomaton
from hylaa.engine import HylaaSettings
from hylaa.engine import HylaaEngine
from hylaa.containers import PlotSettings, SimulationSettings
from hylaa.star import Star

def define_ha():
    '''make the hybrid automaton and return it'''

    ha = LinearHybridAutomaton()

    mode = ha.new_mode('mode')
    dynamics = loadmat('iss.mat')
    a_matrix = dynamics['A']

    # a is a csc_matrix
    col_ptr = [n for n in a_matrix.indptr]
    rows = [n for n in a_matrix.indices]
    data = [n for n in a_matrix.data]

    b_matrix = dynamics['B']

    for u in xrange(3):
        rows += [n for n in b_matrix[:, u].indices]
        data += [n for n in b_matrix[:, u].data]
        col_ptr.append(len(data))

    combined_mat = csc_matrix((data, rows, col_ptr), shape=(a_matrix.shape[0] + 3, a_matrix.shape[1] + 3))

    mode.set_dynamics(csr_matrix(combined_mat))

    error = ha.new_mode('error')

    # need to add three more variables to y3 due to the input terms
    y3 = dynamics['C'][2]

    col_ptr = [n for n in y3.indptr]
    col_ptr.append(y3.data.shape[0])
    col_ptr.append(y3.data.shape[0])
    col_ptr.append(y3.data.shape[0])

    y3 = csc_matrix((y3.data, y3.indices, col_ptr), shape=(1, y3.shape[1] + 3))
    guard_matrix = csr_matrix(y3)

    limit = 0.0005
    #limit = 0.00017
    trans1 = ha.new_transition(mode, error)
    trans1.set_guard(guard_matrix, np.array([-limit], dtype=float)) # y3 <= -0.0005

    trans2 = ha.new_transition(mode, error)
    trans2.set_guard(-guard_matrix, np.array([-limit], dtype=float)) # y3 >= 0.0005

    return ha

def make_init_constraints(ha):
    '''return (init_mat, init_rhs)'''

    values = []
    indices = []
    indptr = []

    constraint_rhs = []

    for dim in xrange(ha.dims):
        if dim == 270: # input 1
            lb = 0
            ub = 0.1
        elif dim == 271: # input 2
            lb = 0.8
            ub = 1.0
        elif dim == 272: # input 3
            lb = 0.9
            ub = 1.0
        elif dim < 270:
            lb = -0.0001
            ub = 0.0001
        else:
            raise RuntimeError('Unknown dimension: {}'.format(dim))

        # upper bound
        values.append(1)
        indices.append(dim)
        indptr.append(2*dim)
        constraint_rhs.append(ub)

        # lower bound
        values.append(-1)
        indices.append(dim)
        indptr.append(2*dim+1)
        constraint_rhs.append(-lb)

    indptr.append(len(values))

    init_mat = csr_matrix((values, indices, indptr), shape=(2*ha.dims, ha.dims), dtype=float)
    init_rhs = np.array(constraint_rhs, dtype=float)

    return (init_mat, init_rhs)

def make_init_star(ha, hylaa_settings):
    '''returns a star'''

    init_mat, init_rhs = make_init_constraints(ha)

    return Star(hylaa_settings, ha.modes['mode'], init_mat, init_rhs)

def define_settings(_):
    'get the hylaa settings object'
    plot_settings = PlotSettings()
    plot_settings.plot_mode = PlotSettings.PLOT_NONE

    step_size = 0.01
    max_time = 1.0

    #max_time = 20.0
    #step_size = 0.001
    settings = HylaaSettings(step=step_size, max_time=max_time, plot_settings=plot_settings)
    settings.simulation.guard_mode = SimulationSettings.GUARD_DECOMPOSED

    #settings.simulation.sim_mode = SimulationSettings.EXP_MULT
    settings.simulation.sim_mode = SimulationSettings.KRYLOV
    settings.simulation.check_answer = True

    return settings

def run_hylaa():
    'Runs hylaa with the given settings, returning the HylaaResult object.'
    ha = define_ha()
    settings = define_settings(ha)
    init = make_init_star(ha, settings)

    engine = HylaaEngine(ha, settings)
    engine.run(init)

    return engine.result

if __name__ == '__main__':
    run_hylaa()
