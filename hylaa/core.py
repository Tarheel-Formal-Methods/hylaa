'''
Main Hylaa Reachability Implementation
Stanley Bak, 2018
'''

from collections import deque, defaultdict

import numpy as np
from termcolor import cprint

from hylaa.settings import HylaaSettings, PlotSettings

from hylaa.aggdag import AggDag
from hylaa.plotutil import PlotManager

from hylaa.stateset import StateSet
from hylaa.hybrid_automaton import HybridAutomaton, was_tt_taken
from hylaa.timerutil import Timers
from hylaa.util import Freezable
from hylaa.lpinstance import LpInstance
from hylaa import lputil

class Core(Freezable):
    'main computation object. initialize and call run()'

    def __init__(self, ha, hylaa_settings):
        assert isinstance(hylaa_settings, HylaaSettings)
        assert isinstance(ha, HybridAutomaton)

        self.hybrid_automaton = ha
        
        self.settings = hylaa_settings

        self.plotman = PlotManager(self)

        # computation
        self.aggdag = AggDag(hylaa_settings, self) # manages the waiting list and aggregation dag computation state
        
        self.max_steps_remaining = None # bound on num steps left in current mode ; assigned on pop

        self.took_tt_transition = False # flag for if a tt transition was taken (cur_state should be cleared)

        self.result = None # a HylaaResult... assigned on run() to store verification result

        self.continuous_steps = 0

        # make random number generation (for example, to find orthogonal directions) deterministic
        np.random.seed(seed=0)

        LpInstance.print_normal = self.print_normal
        LpInstance.print_verbose = self.print_verbose
        LpInstance.print_debug = self.print_debug

        self.freeze_attrs()

    def print_normal(self, msg):
        'print function for STDOUT_NORMAL and above'

        if self.settings.stdout >= HylaaSettings.STDOUT_NORMAL:
            cprint(msg, self.settings.stdout_colors[HylaaSettings.STDOUT_NORMAL])

    def print_verbose(self, msg):
        'print function for STDOUT_VERBOSE and above'

        if self.settings.stdout >= HylaaSettings.STDOUT_VERBOSE:
            cprint(msg, self.settings.stdout_colors[HylaaSettings.STDOUT_VERBOSE])

    def print_debug(self, msg):
        'print function for STDOUT_DEBUG and above'

        if self.settings.stdout >= HylaaSettings.STDOUT_DEBUG:
            cprint(msg, self.settings.stdout_colors[HylaaSettings.STDOUT_DEBUG])

    def is_finished(self):
        'is the computation finished'

        finished = False

        if self.settings.stop_on_aggregated_error and self.result.has_aggergated_error:
            finished = True
        elif self.settings.stop_on_concrete_error and self.result.has_concrete_error:
            finished = True
        else:    
            finished = self.aggdag.get_cur_state() is None and not self.aggdag.waiting_list

        return finished

    def error_reached(self, t, lpi):
        'an error mode was reached after taking transition t, report and create counterexample'

        cur_state = self.aggdag.get_cur_state()

        step_num = cur_state.cur_steps_since_start
        times = [round(self.settings.step_size * step_num[0], 12), round(self.settings.step_size * step_num[1], 12)]

        if step_num[0] == step_num[1]:
            step_num = step_num[0]
            times = times[0]
        
        self.print_normal("Unsafe Mode Reached at Step: {} / {}, time {}".format( \
            step_num, self.settings.num_steps, times))

        self.result.has_aggregated_error = True

        # if this is a concrete state (not aggregated) and we don't yet have a counter-example
        if cur_state.is_concrete:
            self.result.has_concrete_error = True

            if not self.result.counterexample:
                self.result.counterexample = make_counterexample(self.hybrid_automaton, t, lpi)

    def check_guards(self):
        '''check for discrete successors with the guards'''

        Timers.tic("check_guards")

        cur_state = self.aggdag.get_cur_state()

        for t in cur_state.mode.transitions:
            t_lpi = t.get_guard_intersection(cur_state.lpi)

            if t_lpi:
                if t.to_mode.is_error():
                    self.error_reached(t, t_lpi)

                    if self.settings.stop_on_aggregated_error:
                        break

                    if cur_state.is_concrete and self.settings.stop_on_concrete_error:
                        break
                
                self.aggdag.add_transition_successor(t, t_lpi)

                self.print_verbose("Added Discrete Successor to '{}' at step {}".format( \
                                   t.to_mode.name, cur_state.cur_steps_since_start))

                # if it's a time-triggered transition, we may remove cur_state immediately
                if self.settings.optimize_tt_transitions and t.time_triggered:
                    if was_tt_taken(cur_state.lpi, t):
                        self.print_verbose("Transition was time-triggered, finished with current state analysis")
                        self.took_tt_transition = True
                    else:
                        self.print_verbose("Transition was NOT taken as time-triggered, due to runtime checks")

        Timers.toc("check_guards")

    def intersect_invariant(self, state, add_ops_to_aggdag=True):
        '''intersect the (current or passed-in) state with the mode invariant'''

        Timers.tic("intersect_invariant")

        is_feasible = True

        for invariant_index, lc in enumerate(state.mode.inv_list):
            if lputil.check_intersection(state.lpi, lc.negate()):
                old_row = state.invariant_constraint_rows[invariant_index]
                vec = lc.csr.toarray()[0]
                rhs = lc.rhs

                if old_row is None:
                    # new constraint
                    row = lputil.add_init_constraint(state.lpi, vec, rhs, state.basis_matrix,
                                                     state.input_effects_list)
                    state.invariant_constraint_rows[invariant_index] = row
                    is_stronger = False
                else:
                    # strengthen existing constraint possibly
                    row, is_stronger = lputil.try_replace_init_constraint(state.lpi, old_row, vec, rhs, \
                        state.basis_matrix, state.input_effects_list)
                    state.invariant_constraint_rows[invariant_index] = row

                if add_ops_to_aggdag:
                    self.aggdag.add_invariant_op(state.cur_step_in_mode, invariant_index, is_stronger)

                # adding the invariant condition may make the lp infeasible
                if not state.lpi.is_feasible():
                    is_feasible = False
                    break

        Timers.toc("intersect_invariant")

        return is_feasible

    def print_current_step_time(self):
        'print the current step and time'

        step_num = self.aggdag.get_cur_state().cur_steps_since_start
        times = [round(self.settings.step_size * step_num[0], 12), round(self.settings.step_size * step_num[1], 12)]

        if step_num[0] == step_num[1]:
            step_num = step_num[0]
            times = times[0]

        self.print_verbose("Step From {} / {} ({})".format(step_num, self.settings.num_steps, times))

    def do_step_continuous_post(self):
        '''do a step where it's part of a continuous post'''

        Timers.tic('do_step_continuous_post')

        cur_state = self.aggdag.get_cur_state()
        self.print_current_step_time()

        if not self.is_finished():
            if cur_state.cur_steps_since_start[0] >= self.settings.num_steps:
                self.print_normal("State reached computation time bound")
                self.aggdag.cur_state_left_invariant()

            elif self.took_tt_transition:
                self.print_normal("State reached a time-triggered transition")
                self.took_tt_transition = False # reset the flag
                self.aggdag.cur_state_left_invariant()
            else:
                still_feasible = self.intersect_invariant(cur_state)
                
                if not still_feasible:
                    self.print_normal("State left the invariant after {} steps".format(cur_state.cur_step_in_mode))
                    self.aggdag.cur_state_left_invariant()
                else:
                    cur_state.step()
                    self.check_guards() # check guards here, before doing an invariant intersection

                    # if the current mode has zero dynamic, remove it here
                    if cur_state.mode.a_csr.nnz == 0:
                        self.print_normal("State in mode '{}' with zero dynamics, skipping remaining steps".format( \
                            cur_state.mode.name))
                        self.aggdag.cur_state_left_invariant()

        if self.is_finished():
            self.print_normal("Computation finished after {} continuous-post steps.".format(self.continuous_steps))

        Timers.toc('do_step_continuous_post')

    def do_step_pop(self):
        'do a step where we pop from the waiting list'

        Timers.tic('do_step_pop')

        self.plotman.state_popped() # reset certain per-mode plot variables
        self.aggdag.print_waiting_list()

        self.result.last_cur_state = cur_state = self.aggdag.pop_waiting_list()

        self.print_normal("Removed state in mode '{}' at step {} ({} in mode) (Waiting list has {} left)".format( \
                cur_state.mode.name, cur_state.cur_steps_since_start, cur_state.cur_step_in_mode, \
                len(self.aggdag.waiting_list)))

        # if a_matrix is None, it's an error mode
        if cur_state.mode.a_csr is None:
            self.print_normal("Mode '{}' was an error mode; skipping.".format(cur_state.mode.name))

            self.aggdag.cur_state_left_invariant()
        else:
            self.max_steps_remaining = self.settings.num_steps - cur_state.cur_steps_since_start[0]

            still_feasible = self.intersect_invariant(cur_state)

            if not still_feasible:
                self.print_normal("Continuous state was outside of the mode's invariant; skipping.")
                self.aggdag.cur_state_left_invariant()

        # pause after popping when using PLOT_INTERACTIVE
        if self.plotman.settings.plot_mode == PlotSettings.PLOT_INTERACTIVE:
            self.plotman.interactive.paused = True

        Timers.toc('do_step_pop')
                
    def do_step(self):
        'do a single step of the computation'

        Timers.tic('do_step')

        if not self.is_finished():
            if self.aggdag.get_cur_state() is None:
                self.do_step_pop()

                if self.settings.process_urgent_guards and self.aggdag.get_cur_state() is not None:
                    self.check_guards()
            else:
                self.do_step_continuous_post()
                self.continuous_steps += 1

        Timers.toc('do_step')

    def setup(self, init_state_list):
        'setup the computation (called by run())'

        Timers.tic('setup')

        for state in init_state_list:
            assert isinstance(state, StateSet), "initial states should be a list of StateSet objects"

        assert init_state_list, "expected list of initial states"

        self.result = HylaaResult()

        # initialize time elapse in each mode of the hybrid automaton
        ha = init_state_list[0].mode.ha

        for mode in ha.modes.values():
            mode.init_time_elapse(self.settings.step_size)

        if self.settings.optimize_tt_transitions:
            ha.detect_tt_transitions(self.print_debug)

        if self.settings.do_guard_strengthening:
            ha.do_guard_strengthening()

        ha.check_transitions()
        
        self.plotman.create_plot()

        # populate waiting list
        assert not self.aggdag.waiting_list, "waiting list was not empty"

        for state in init_state_list:
            if not state.lpi.is_feasible():
                self.print_normal("Removed an infeasible initial set in mode {}".format(state.mode.name))
                continue
            
            still_feasible = self.intersect_invariant(state, add_ops_to_aggdag=False)

            if still_feasible:
                # reset the cached info about invariant intersections, since the intersection ops are not in the aggdag
                state.invariant_constraint_rows = [None] * len(state.mode.inv_list)
                
                self.aggdag.add_init_state(state)
            else:
                self.print_normal("Removed an infeasible initial set after invariant intersection in mode {}".format( \
                        state.mode.name))

        if not self.aggdag.waiting_list:
            raise RuntimeError("Error: No feasible initial states were defined.")

        Timers.toc('setup')

    def run_to_completion(self):
        'run the model to completion (called by run() if not plot is desired)'

        self.plotman.run_to_completion(compute_plot=self.settings.plot.store_plot_result)

    def run(self, init_state_list):
        '''
        Run the computation (main entry point)

        init_star is the initial state

        fixed_dim_list, if used, is a list of dimensions with fixed initial values
        '''

        Timers.reset()
        Timers.tic("total")

        self.setup(init_state_list)

        if self.settings.plot.plot_mode == PlotSettings.PLOT_NONE:
            self.run_to_completion()
        else:
            self.plotman.compute_and_animate()

        Timers.toc("total")

        if self.settings.stdout >= HylaaSettings.STDOUT_VERBOSE:
            Timers.print_stats()

        if self.result.has_concrete_error:
            self.print_normal("Result: Error modes are reachable (found counter-example).\n")
        elif self.result.has_aggergated_error:
            self.print_normal("Result: Error modes are reachable when aggergation (overapproximation) was used.\n")
        else:
            self.print_normal("Result: System is safe. Error modes are NOT reachable.\n")

        self.print_normal("Total Runtime: {:.2f} sec".format(Timers.top_level_timer.total_secs))

        # assign results
        self.result.top_level_timer = Timers.top_level_timer
        Timers.reset()

        return self.result

def make_counterexample(ha, transition_to_error, lpi):
    '''make and return the result counter-example from the lp solution'''

    lp_solution = lpi.minimize() # resolves the LP to get the full unsafe solution
    names = lpi.get_names()

    counterexample = []

    for name, value in zip(names, lp_solution):

        # if first initial variable of mode then assign the segment.mode variable
        if name.startswith('m') and '_i0' in name:
            seg = CounterExampleSegment()
            counterexample.append(seg)

            parts = name.split('_')

            if len(parts) == 2:
                assert len(counterexample) == 1, "only the initial mode should have no predecessor transition"
            else:
                assert len(parts) == 3

                # assign outgoing transition of previous counterexample segment
                transition_index = int(parts[2][1:])
                t = counterexample[-2].mode.transitions[transition_index]
                counterexample[-2].outgoing_transition = t

            mode_id = int(parts[0][1:])

            for mode in ha.modes.values():
                if mode.mode_id == mode_id:
                    seg.mode = mode
                    break

            assert seg.mode is not None, "mode id {} not found in automaton".format(mode_id)

        if name.startswith('m'): # mode variable
            if '_i' in name:
                seg.start.append(value)
            elif '_c' in name:
                seg.end.append(value)
            elif '_I' in name:
                if '_I0' in name:
                    seg.inputs.appendleft([])
                    
                # inputs are in backwards order due to how the LP is constructed, prepend it
                seg.inputs[0].append(value)

        elif name.startswith('reset'):
            seg.reset_minkowski_vars.append(value)

    # add the final transition which is not encoded in the names of the variables
    seg.outgoing_transition = transition_to_error

    return counterexample

class CounterExampleSegment(Freezable):
    'a part of a counter-example trace'

    def __init__(self):
        self.mode = None # Mode object
        self.start = []
        self.end = []
        self.outgoing_transition = None # Transition object
        self.reset_minkowski_vars = [] # a list of minkowski variables in the outgoing reset

        self.inputs = deque() # inputs at each step (a deque of m-tuples, where m is the number of inputs)
        
        self.freeze_attrs()

    def __str__(self):
        return "[CE_Segment: {} -> {} in '{}']".format( \
            self.start, self.end, "<None>" if self.mode is None else self.mode.name)

    def __repr__(self):
        return str(self)

class HylaaResult(Freezable): # pylint: disable=too-few-public-methods
    'result object returned by core.run()'

    def __init__(self):
        self.top_level_timer = None # TimerData for total time

        # verification result:
        self.has_aggregated_error = False
        self.has_concrete_error = False

        self.counterexample = [] # if unsafe, a list of CounterExampleSegment objects

        # assigned if setting.plot.store_plot_result is True, a map name -> list of lists (the verts at each step)
        self.mode_to_polys = defaultdict(list)

        # the last core.cur_state object... used for unit testing
        self.last_cur_state = None

        self.freeze_attrs()
