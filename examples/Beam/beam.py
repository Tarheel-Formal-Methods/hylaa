'''
Beam Example in Hylaa-Continuous
'''

from scipy.io import loadmat
from scipy.sparse import csr_matrix

from hylaa.hybrid_automaton import LinearHybridAutomaton, SparseLinearConstraint, add_time_var, add_zero_cols
from hylaa.engine import HylaaSettings
from hylaa.engine import HylaaEngine
from hylaa.containers import PlotSettings, SimulationSettings
from hylaa.star import Star

def define_ha():
    '''make the hybrid automaton and return it'''

    ha = LinearHybridAutomaton()

    mode = ha.new_mode('mode')
    dynamics = loadmat('beam.mat')
    a_matrix = add_time_var(dynamics['A'])
    mode.set_dynamics(a_matrix)

    error = ha.new_mode('error')

    # add two more variables due to the time term
    condition_mat = add_zero_cols(dynamics['C'], 2)

    trans1 = ha.new_transition(mode, error)
    trans1.condition_list.append(SparseLinearConstraint(-condition_mat[0], -1000.0)) # y1 >= 1000

    return ha

def define_init_states(ha, settings):
    '''returns a Star'''

    constraints = []

    n = ha.dims

    time_var = n - 2
    affine_var = n - 1

    for dim in xrange(n):
        if dim < 300:
            lb = ub = 0
        elif dim < time_var:
            lb = 0.0015
            ub = 0.0020
        elif dim == time_var:
            lb = ub = 0 # time variable
        elif dim == affine_var:
            lb = ub = 1 # affine variable

        # upper bound
        mat = csr_matrix(([1], [dim], [0, 1]), shape=(1, n))
        constraints.append(SparseLinearConstraint(mat, ub))

        # lower bound
        mat = csr_matrix(([-1], [dim], [0, 1]), shape=(1, n))
        constraints.append(SparseLinearConstraint(mat, -lb))

    return Star(settings, constraints, ha.modes['mode'])

def define_settings(ha):
    'get the hylaa settings object'
    plot_settings = PlotSettings()
    plot_settings.plot_mode = PlotSettings.PLOT_FULL

    plot_settings.xdim_dir = (ha.dims - 2)
    plot_settings.ydim_dir = ha.transitions[0].condition_list[0].vector

    # save a video file instead
    # plot_settings.make_video("vid.mp4", frames=220, fps=40)

    plot_settings.num_angles = 3
    plot_settings.max_shown_polys = 2048
    plot_settings.label.y_label = '$y_{1}$'
    plot_settings.label.x_label = 'Time'
    plot_settings.label.title = ''
    #plot_settings.label.axes_limits = (0, 1, -0.007, 0.006)
    plot_settings.plot_size = (12, 10)
    plot_settings.label.big(size=40)

    settings = HylaaSettings(step=0.05, max_time=20.0, plot_settings=plot_settings)
    settings.simulation.sim_mode = SimulationSettings.EXP_MULT

    return settings

def run_hylaa():
    'Runs hylaa with the given settings, returning the HylaaResult object.'
    ha = define_ha()
    settings = define_settings(ha)
    init = define_init_states(ha, settings)

    engine = HylaaEngine(ha, settings)
    engine.run(init)

    return engine.result

if __name__ == '__main__':
    run_hylaa()
