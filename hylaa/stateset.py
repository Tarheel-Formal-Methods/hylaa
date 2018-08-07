'''
Generalized Star and other Star data structures
Stanley Bak
Aug 2016
'''

from collections import namedtuple

import numpy as np

from hylaa import lputil

from hylaa.hybrid_automaton import Mode
from hylaa.timerutil import Timers
from hylaa.util import Freezable
from hylaa.lpinstance import LpInstance

from hylaa import lpplot

# predecessor types
AggregationPredecessor = namedtuple('AggregationPredecessor', ['states'])
TransitionPredecessor = namedtuple('TransitionPredecessor', ['state', 'transition', 'transition_lpi'])

class StateSet(Freezable):
    '''
    A set of states with a common mode.
    '''

    def __init__(self, lpi, mode, cur_step_since_start=0, predecessor=None):
        assert isinstance(lpi, LpInstance)
        assert isinstance(mode, Mode)

        self.mode = mode
        self.lpi = lpi

        self.cur_step_in_mode = 0
        self.cur_step_since_start = cur_step_since_start

        # the predecessor to this StateSet
        assert isinstance(predecessor, (type(None), AggregationPredecessor, TransitionPredecessor))
        self.predecessor = predecessor
        
        # the LP row of the strongest constraint for each invariant condition
        # this is used to eliminate redundant constraints as the lpi is intersected with the invariant at each step
        self.invariant_constraint_rows = None 

        self.basis_matrix = np.identity(mode.a_csr.shape[0])
        self.input_effects_list = None if mode.b_csr is None else [] # list of input effects at each step

        self._verts = None # cached vertices at the current step

        self.assigned_plot_dim = False # set to True on first call to verts()
        self.xdim = None # set on first call to verts()
        self.ydim = None # set on first call to verts()

        self.freeze_attrs()

    def clone(self):
        'deep copy this StateSet'

        rv = StateSet(self.lpi.clone(), self.mode, self.cur_step_since_start, self.predecessor)

        rv.cur_step_in_mode = self.cur_step_in_mode
        rv.invariant_constraint_rows = self.invariant_constraint_rows.copy()
        rv.basis_matrix = self.basis_matrix.copy()

        return rv

    def __str__(self):
        'short string representation of this state set'

        return "[StateSet in '{}']".format(self.mode.name)

    def step(self):
        'update the star based on values from a new simulation time instant'

        Timers.tic("step")

        self.cur_step_in_mode += 1
        self.cur_step_since_start += 1

        Timers.tic('get_bm')
        self.basis_matrix, input_effects_matrix = self.mode.time_elapse.get_basis_matrix(self.cur_step_in_mode)
        Timers.toc('get_bm')

        Timers.tic('set_bm')
        lputil.set_basis_matrix(self.lpi, self.basis_matrix)
        Timers.toc('set_bm')

        if input_effects_matrix is not None:
            self.input_effects_list.append(input_effects_matrix)
            
            Timers.tic('add_input_effects')
            lputil.add_input_effects_matrix(self.lpi, input_effects_matrix, self.mode)
            Timers.toc('add_input_effects')

        self._verts = None # cached vertices no longer valid

        Timers.toc("step")

    def verts(self, plotman):
        'get the vertices for plotting this state set, wraps around so rv[0] == rv[-1]'

        Timers.tic('verts')

        if self._verts is None:
            cur_time = self.cur_step_since_start * plotman.core.settings.step_size

            if not self.assigned_plot_dim:
                self.assigned_plot_dim = True
                self.xdim = plotman.settings.xdim_dir
                self.ydim = plotman.settings.ydim_dir

                if isinstance(self.xdim, dict):
                    assert self.mode.name in self.xdim, "mode {} not in xdim plot direction dict".format(self.mode.name)
                    self.xdim = self.xdim[self.mode.name]

                if isinstance(self.ydim, dict):
                    assert self.mode.name in self.ydim, "mode {} not in ydim plot direction dict".format(self.mode.name)
                    self.ydim = self.ydim[self.mode.name]

            self._verts = lpplot.get_verts(self.lpi, xdim=self.xdim, ydim=self.ydim, plot_vecs=plotman.plot_vecs, \
                                           cur_time=cur_time)
            assert self._verts is not None, "verts() was unsat"
            
        Timers.toc('verts')

        return self._verts

    def intersect_invariant(self):
        '''intersect the current state set with the mode invariant

        returns whether the state set is still feasbile after intersection'''

        Timers.tic("intersect_invariant")

        has_intersection = False

        if self.invariant_constraint_rows is None:
            self.invariant_constraint_rows = [None] * len(self.mode.inv_list)

        print(". stateset.intersect_invariant()")

        for invariant_index, lc in enumerate(self.mode.inv_list):
            print(". checking invariant condition #{}: {}".format(invariant_index, lc))
            
            if lputil.check_intersection(self.lpi, lc.negate()):
                print(". has intersection!")

                has_intersection = True
                old_row = self.invariant_constraint_rows[invariant_index]
                vec = lc.csr.toarray()[0]
                rhs = lc.rhs

                if old_row is None:
                    # new constriant
                    row = lputil.add_init_constraint(self.lpi, vec, rhs, self.basis_matrix, self.input_effects_list)
                    self.invariant_constraint_rows[invariant_index] = row
                else:
                    # strengthen existing constraint possibly
                    row = lputil.try_replace_init_constraint(self.lpi, old_row, vec, rhs, self.basis_matrix, \
                                                             self.input_effects_list)
                    self.invariant_constraint_rows[invariant_index] = row

        is_feasible = True if not has_intersection else self.lpi.minimize(columns=[], fail_on_unsat=False) is not None

        print(". intersects invariant returning is_feasible={}".format(is_feasible))

        Timers.toc("intersect_invariant")

        return is_feasible
