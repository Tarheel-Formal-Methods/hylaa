'''
Generalized Star and other Star data structures
Stanley Bak
Aug 2016
'''

import numpy as np

from matplotlib.path import Path

from hylaa import lputil

from hylaa.hybrid_automaton import Mode
from hylaa.timerutil import Timers
from hylaa.util import Freezable
from hylaa.lpinstance import LpInstance

from hylaa import lpplot

class StateSet(Freezable):
    '''
    A set of states (possibly aggregated) in the same mode.
    '''

    def __init__(self, lpi, mode, cur_steps_since_start=None, aggdag_op_list=None, is_concrete=True):
        assert isinstance(lpi, LpInstance)
        assert isinstance(mode, Mode)

        self.mode = mode
        self.lpi = lpi

        self.cur_step_in_mode = 0

        if cur_steps_since_start is not None:
            assert len(cur_steps_since_start) == 2 # needs to be an interval in case this stateset is an aggregation
            self.cur_steps_since_start = cur_steps_since_start.copy()
        else:
            self.cur_steps_since_start = [0, 0]

        self.is_concrete = is_concrete

        if aggdag_op_list is None: # assume its an initial stateset
            aggdag_op_list = [None]

        assert isinstance(aggdag_op_list, (list, tuple))        
        self.aggdag_op_list = aggdag_op_list # list of OpTransition objects that created this state set

        # the LP row of the strongest constraint for each invariant condition
        # this is used to eliminate redundant constraints as the lpi is intersected with the invariant at each step
        self.invariant_constraint_rows = [None] * len(self.mode.inv_list)

        # mode might be an error mode, in which case a_csr is None
        self.basis_matrix = None if mode.a_csr is None else np.identity(mode.a_csr.shape[0])
        
        self.input_effects_list = None if mode.b_csr is None else [] # list of input effects at each step

        #### plotting variables below ####
        self._verts = None # cached vertices at the current step
        self.assigned_plot_dim = False # set to True on first call to verts()
        self.xdim = None # set on first call to verts()
        self.ydim = None # set on first call to verts()

        # map of step number in mode -> list (for each subplot) of pairs: (matploatlib Path object list, index)
        self.step_to_paths = {} 

        self.freeze_attrs()

    def __str__(self):
        'short string representation of this state set'

        return "[StateSet in '{}']".format(self.mode.name)

    def step(self, step_in_mode=None):
        '''update the star based on values from a new simulation time instant

        the default is to advance by one step, otherwise step_in_mode can force
        going to a specific step number
        '''

        Timers.tic("step")

        if step_in_mode is None:
            step_in_mode = self.cur_step_in_mode + 1

        num_steps = step_in_mode - self.cur_step_in_mode

        # we can't do negative steps because we add input effects in the lpi for each step
        assert num_steps >= 0, "step() called with negative num steps"

        if num_steps > 0:
            Timers.tic('get_bm')
            self.basis_matrix, input_effects_matrix = self.mode.time_elapse.get_basis_matrix(step_in_mode)
            Timers.toc('get_bm')

            Timers.tic('set_bm')
            lputil.set_basis_matrix(self.lpi, self.basis_matrix)
            Timers.toc('set_bm')

            if input_effects_matrix is not None:
                Timers.tic('input effects matrix')
                # if we're doing multiple steps here we need to get each step's input effects matrix
                for step in range(self.cur_step_in_mode + 1, step_in_mode):
                    _, ie_mat = self.mode.time_elapse.get_basis_matrix(step)
                    self.input_effects_list.append(ie_mat)
                    lputil.add_input_effects_matrix(self.lpi, ie_mat, self.mode)

                # add the input effects matrix for the final step (computed before with basis matrix)
                self.input_effects_list.append(input_effects_matrix)
                lputil.add_input_effects_matrix(self.lpi, input_effects_matrix, self.mode)
                Timers.toc('input effects matrix')

            self.cur_step_in_mode += num_steps
            self.cur_steps_since_start[0] += num_steps
            self.cur_steps_since_start[1] += num_steps
            self._verts = None # cached vertices no longer valid

        Timers.toc("step")

    def verts(self, plotman, subplot=0):
        'get the vertices for plotting this state set, wraps around so rv[0] == rv[-1]'

        Timers.tic('verts')

        if self._verts is None:
            self._verts = [None] * plotman.num_subplots

        if self._verts[subplot] is None:
            min_time = self.cur_steps_since_start[0] * plotman.core.settings.step_size
            max_time = self.cur_steps_since_start[1] * plotman.core.settings.step_size
            time_interval = (min_time, max_time)

            if not self.assigned_plot_dim:
                self.assigned_plot_dim = True

                self.xdim = []
                self.ydim = []

                for i in range(plotman.num_subplots):
                    self.xdim.append(plotman.settings.xdim_dir[i])
                    self.ydim.append(plotman.settings.ydim_dir[i])

                    if isinstance(self.xdim[i], dict):
                        assert self.mode.name in self.xdim[i], "mode {} not in xdim plot direction dict".format(
                            self.mode.name)
                        self.xdim[i] = self.xdim[i][self.mode.name]

                    if isinstance(self.ydim[i], dict):
                        assert self.mode.name in self.ydim[i], "mode {} not in ydim plot direction dict".format(
                            self.mode.name)
                        self.ydim[i] = self.ydim[i][self.mode.name]

            self._verts[subplot] = lpplot.get_verts(self.lpi, xdim=self.xdim[subplot], ydim=self.ydim[subplot], \
                                           plot_vecs=plotman.plot_vec_list[subplot], cur_time=time_interval)
            
            assert self._verts[subplot] is not None, "verts() was unsat"
            
        Timers.toc('verts')

        return self._verts[subplot]

    def set_plot_path(self, subplot, path_list, path_index):
        '''
        set the matplotlib path object for this stateset at the current step
        '''

        step = self.cur_step_in_mode

        if step not in self.step_to_paths:
            l = []
            self.step_to_paths[step] = l
        else:
            l = self.step_to_paths[step]

        while len(l) <= subplot:
            l.append([])

        l[subplot] = (path_list, path_index)

    def del_plot_path(self, step):
        '''
        delete a plotted matplotlib Path object for this stateset.

        returns a list of verts (one for each subplot) that was deleted
        '''

        rv = []
        l = self.step_to_paths[step]

        codes = [Path.MOVETO, Path.CLOSEPOLY]
        verts = [(0, 0), (0, 0)]

        # for every subplot
        for path_list, index in l:
            rv.append(path_list[index].vertices)
            path_list[index] = Path(verts, codes)

        return rv
