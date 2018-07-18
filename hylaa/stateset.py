'''
Generalized Star and other Star data structures
Stanley Bak
Aug 2016
'''

from hylaa import lputil

from hylaa.hybrid_automaton import Mode
from hylaa.timerutil import Timers
from hylaa.util import Freezable
from hylaa.lpinstance import LpInstance

from hylaa import lpplot

class StateSet(Freezable):
    '''
    A set of states with a common mode.
    '''

    def __init__(self, lpi, mode):
        assert isinstance(lpi, LpInstance)
        assert isinstance(mode, Mode)

        self.mode = mode
        self.lpi = lpi

        self.cur_step_in_mode = 0
        self.cur_step_since_start = 0

        self._verts = None # cached vertices at the current step

        self.freeze_attrs()

    def step(self):
        'update the star based on values from a new simulation time instant'

        self.cur_step_in_mode += 1
        self.cur_step_since_start += 1

        basis_matrix, _ = self.mode.time_elapse.get_basis_matrix(self.cur_step_in_mode)

        lputil.set_basis_matrix(self.lpi, basis_matrix)

        # update each transition's basis matrix
        for t in self.mode.transitions:
            lputil.set_basis_matrix(t.lpi, basis_matrix)

        self._verts = None # cached vertices no longer valid

    def verts(self, plotman):
        'get the vertices for plotting this state set, wraps around so rv[0] == rv[-1]'

        Timers.tic('verts')

        if self._verts is None:
            xdim = plotman.settings.xdim_dir
            ydim = plotman.settings.ydim_dir
            cur_time = self.cur_step_since_start * plotman.core.settings.step_size

            self._verts = lpplot.get_verts(self.lpi, xdim=xdim, ydim=ydim, plot_vecs=plotman.plot_vecs, \
                                           cur_time=cur_time)
            
        Timers.toc('verts')

        return self._verts

    def __str__(self):
        'short string representation of this state set'

        return "[StateSet in '{}']".format(self.mode.name)
