'''
Stanley Bak
Aggregation Directed Acyclic Graph (DAG) implementation
'''

from collections import namedtuple

import numpy as np

from termcolor import cprint

from graphviz import Digraph

from namedlist import namedlist

from hylaa.settings import HylaaSettings, AggregationSettings
from hylaa.util import Freezable
from hylaa.stateset import StateSet
from hylaa.timerutil import Timers
from hylaa import lputil

# Operation types
OpInvIntersect = namedtuple('OpInvIntersect', ['step', 'node', 'i_index', 'is_stronger'])
OpTransition = namedlist('OpTransition', ['step', 'parent_node', 'child_node', 'transition', 'premode_center',
                                          'postmode_state'])

class AggDag(Freezable):
    'Aggregation directed acyclic graph (DAG) used to manage the deaggregation process'

    def __init__(self, settings, core):
        self.settings = settings
        self.core = core
        
        self.roots = [] # list of root AggDagNode where the computation begins
        self.cur_node = None # the aggdag_node currently under a continuous post operation

        self.waiting_list = [] # a list of tuples: (StateSet, OpTransition)
        
        self.freeze_attrs()

    def get_cur_state(self):
        '''get the current state being propagated

        This may be None, an aggregated state, or a concrete state
        '''

        rv = None

        if self.cur_node is not None:
            rv = self.cur_node.get_cur_state()

        return rv

    def cur_state_left_invariant(self):
        '''called when the current state left the invariant'''

        self.cur_node = None        

    def add_init_state(self, state):
        'add an initial state'

        self.waiting_list.append((state, None))

    def add_transition_successor(self, t, t_lpi, premode_center):
        '''a transition was feasible, update the aggdag / waiting list

        t is the AutomaotnTransition object
        t_lpi is the LpInstance object after applying the reset
        premode_center is the center of the box hull of the premode states (used for aggregation)
        '''

        cur_state = self.get_cur_state()

        op_list = []
        state = StateSet(t_lpi, t.to_mode, cur_state.cur_steps_since_start, op_list, cur_state.is_concrete)
        
        # OpTransition: ['step', 'parent_node', 'child_node', 'transition', 'premode_center', 'postmode_state'])
        op = OpTransition(cur_state.cur_step_in_mode, self.cur_node, None, t, premode_center, state)
        op_list.append(op)

        self.cur_node.op_list.append(op)
        
        self.waiting_list.append((state, op))

    def print_waiting_list(self):
        'print out the waiting list'

        if self.settings.stdout >= HylaaSettings.STDOUT_VERBOSE:
            col = self.settings.stdout_colors[HylaaSettings.STDOUT_VERBOSE]
            
            cprint("Waiting list has {} states".format(len(self.waiting_list)), col)

            if len(self.waiting_list) < 10:
                for state in self.waiting_list:
                    cprint(" {}".format(state), col)

    @staticmethod
    def pop_score(state, strategy):
        '''
        returns a score used to decide which state to pop off the waiting list. The state with the highest score
        will be removed first.
        '''

        if strategy == AggregationSettings.POP_LOWEST_MINTIME:
            score = -(state.cur_steps_since_start[0])
        elif strategy == AggregationSettings.POP_LOWEST_AVGTIME:
            score = -(state.cur_steps_since_start[0] + state.cur_steps_since_start[1])
        elif strategy == AggregationSettings.POP_LARGEST_MAXTIME:
            score = state.cur_steps_since_start[1]
        else:
            raise RuntimeError("Unknown waiting list pop strategy: {}".format(strategy))

        return score

    def default_pop_func(self):
        '''
        Get the states to remove from the waiting list based on a score-based method
        '''

        # use score method to decide which mode to pop
        to_remove, to_remove_op = self.waiting_list[0]
        to_remove_score = AggDag.pop_score(to_remove, self.settings.aggregation.pop_strategy)

        for state, _ in self.waiting_list:
            score = AggDag.pop_score(state, self.settings.aggregation.pop_strategy)

            if score > to_remove_score or score == to_remove_score and state.mode.name < to_remove.mode.name:
                to_remove_score = score
                to_remove = state

        self.core.print_verbose("Aggregating with state at time {} in mode {}".format(to_remove.cur_steps_since_start,
                                                                                      to_remove.mode.name))

        # remove all states for aggregation
        agg_list = []

        for state, state_op in self.waiting_list:
            should_add = False

            if state is to_remove:
                should_add = True
            elif state.mode is to_remove.mode:
                if not self.settings.aggregation.require_same_path:
                    should_add = True
                else: # require same path; paths are the same if the parent node and transitions match
                    if to_remove_op is None and state_op is None:
                        should_add = True
                    elif to_remove_op and state_op:
                        if to_remove_op.transition is state_op.transition and \
                                                    to_remove_op.parent_node is state_op.parent_node:
                            should_add = True

            if should_add:
                agg_list.append(state)

        return agg_list

    def get_aggregation_states(self):
        '''get the states from the waiting list we are going to aggregate

        This also updates the internal data structures (waiting_list and AggDag nodes)

        returns agg_list, op_list
        '''

        Timers.tic('get_aggregation_states')

        if self.settings.aggregation.custom_pop_func:
            self.core.print_verbose("Aggregating based on custom pop function")

            states = [pair[0] for pair in self.waiting_list] 

            agg_list = self.settings.aggregation.custom_pop_func(states)
        else:
            agg_list = self.default_pop_func()

        new_waiting_list = []
        op_list = []

        for state, op in self.waiting_list:
            if not state in agg_list:
                new_waiting_list.append((state, op))
            else:
                op_list.append(op)

        self.core.print_verbose("agg_list had {} states, new_waiting_list has {} states".format(
            len(agg_list), len(new_waiting_list)))

        assert agg_list, "agg_list was empty"
        assert len(agg_list) + len(new_waiting_list) == len(self.waiting_list), "agg_list had new states in it?"

        self.waiting_list = new_waiting_list

        Timers.toc('get_aggregation_states')

        return agg_list, op_list

    def pop_waiting_list(self):
        'pop a state off the waiting list, possibly doing state-set aggregation'

        aggregated = False

        if self.settings.aggregation.agg_mode == AggregationSettings.AGG_NONE:
            state, op = self.waiting_list.pop(0)
            agg_list = [state]
            op_list = [op]
        else:
            agg_list, op_list = self.get_aggregation_states()

            self.core.print_verbose("Removed {} state{} for aggregation".format(
                len(agg_list), "s" if len(agg_list) > 1 else ""))

        if len(agg_list) == 1:
            rv = agg_list[0]
        else:
            rv = perform_aggregation(agg_list, op_list, self.settings.aggregation, self.core.print_debug)
            aggregated = True

        # create a new AggDagNode for the current computation
        self.cur_node = AggDagNode(op_list)

        # update the OpTransition objects with the child information
        all_none = True

        for op in op_list:
            if op:
                all_none = False
                op.child_node = self.cur_node

        if all_none:
            self.roots.append(self.cur_node)

        if not aggregated:
            self.cur_node.concrete_state = rv
        else:
            self.cur_node.aggregated_state = rv

        return rv

    def show(self):
        'visualize the aggdag using graphviz'

        # rankdir='LR'

        g = Digraph(name='aggdag')
        already_drawn_nodes = []

        for i, root in enumerate(self.roots):
            preroot = 'preroot{}'.format(i)
            g.node(preroot, style="invis")

            name = "node_{}".format(id(root))
            g.edge(preroot, name)

            root.viz(g, already_drawn_nodes)

        g.view(cleanup=True)

class AggDagNode(Freezable):
    'A node of the Aggregation DAG'

    def __init__(self, parent_ops):
        self.op_list = [] # list of Op* objects

        self.concrete_state = None # StateSet
        self.aggregated_state = None # StateSet, or None if this is a non-aggergated set

        # parent information
        self.parent_ops = parent_ops
        
        self.freeze_attrs()

    def get_mode(self):
        'get the mode for this aggdag node'

        return self.get_cur_state().mode

    def get_cur_state(self):
        'get the current state for this node (aggregated if it exists, else concrete)'

        if self.aggregated_state is not None:
            rv = self.aggregated_state
        else:
            rv = self.concrete_state

        return rv

    def viz(self, g, already_drawn_nodes):
        '''draw the aggdag node using the graphiz library

        g is the DiGraph object to draw to
        '''

        if not self in already_drawn_nodes:
            already_drawn_nodes.append(self)
            name = "node_{}".format(id(self))
            label = self.get_mode().name

            g.node(name, label=label)

            # collapse edges over multiple times into the same outgoing edge
            enabled_transitions = [] # contains tuples (child_name, step_list)

            for op in self.op_list:
                if isinstance(op, OpTransition):
                    if op.child_node is None:
                        # invisible outgoing edge
                        invis_name = "out_{}".format(id(op))
                        g.node(invis_name, style="invis")

                        g.edge(name, invis_name)
                    else:
                        child_name = "node_{}".format(id(op.child_node))
                        found = False

                        for pair in enabled_transitions:
                            if pair[0] == child_name:
                                pair[1].append(op.step)
                                found = True

                        if not found:
                            enabled_transitions.append((child_name, [op.step]))
                            
                    # remove enabled transitions that are no longer enabled
                    new_enabled_transitions = []

                    for pair in enabled_transitions:
                        step_list = pair[1]
                        
                        if step_list[-1] < op.step:
                            # print it
                            label = str(step_list[0]) if len(step_list) == 1 else "[{}, {}]".format( \
                                step_list[0], step_list[-1])
                            g.edge(name, child_name, label=label)
                        else:
                            # keep it
                            new_enabled_transitions.append(pair)

            # flush remaining enabled_transitions
            for child_name, step_list in enabled_transitions:
                label = str(step_list[0]) if len(step_list) == 1 else "[{}, {}]".format(step_list[0], step_list[-1])
                g.edge(name, child_name, label=label)

            # print the children after the current node
            for op in self.op_list:
                if isinstance(op, OpTransition):
                    if op.child_node is not None:
                        op.child_node.viz(g, already_drawn_nodes)

        # ['step', 'parent_node', 'child_node', 'transition', 'premode_center', 'postmode_state']

def perform_aggregation(agg_list, op_list, agg_settings, print_debug):
    '''
    perform aggregation on the passed-in list of states
    '''

    min_step = min([state.cur_steps_since_start[0] for state in agg_list])
    max_step = max([state.cur_steps_since_start[1] for state in agg_list])
    step_interval = [min_step, max_step]

    print_debug("Aggregation step interval: {}".format(step_interval))

    # create a new state from the aggregation
    postmode = agg_list[0].mode
    postmode_dims = postmode.a_csr.shape[0]
    mid_index = len(agg_list) // 2

    op = op_list[mid_index]

    if agg_settings.agg_mode == AggregationSettings.AGG_BOX or op is None:
        agg_dir_mat = np.identity(postmode_dims)
    elif agg_settings.agg_mode == AggregationSettings.AGG_ARNOLDI_BOX:
        # aggregation with a predecessor, use arnoldi directions in predecessor mode in center of
        # middle aggregagted state, then project using the reset, and reorthogonalize

        premode = op.parent_node.get_mode()
        t = op.transition
        print_debug("aggregation point: {}".format(op.premode_center))

        premode_dir_mat = lputil.make_direction_matrix(op.premode_center, premode.a_csr)
        print_debug("premode dir mat:\n{}".format(premode_dir_mat))

        if t.reset_csr is None:
            agg_dir_mat = premode_dir_mat
        else:
            projected_dir_mat = premode_dir_mat * t.reset_csr.transpose()

            print_debug("projected dir mat:\n{}".format(projected_dir_mat))

            # re-orthgohonalize (and create new vectors if necessary)
            agg_dir_mat = lputil.reorthogonalize_matrix(projected_dir_mat, postmode_dims)

        # also add box directions in target mode (if they don't already exist)
        box_dirs = []
        for dim in range(postmode_dims):
            direction = [0 if d != dim else 1 for d in range(postmode_dims)]
            exists = False

            for row in agg_dir_mat:
                if np.allclose(direction, row):
                    exists = True
                    break

            if not exists:
                box_dirs.append(direction)

        if box_dirs:
            agg_dir_mat = np.concatenate((agg_dir_mat, box_dirs), axis=0)

    if op and agg_settings.add_guard:
        # add all the guard conditions to the agg_dir_mat
        
        t = op.transition

        if t.reset_csr is None: # identity reset
            guard_dir_mat = t.guard_csr
        else:
            # multiply each direction in the guard by the reset
            guard_dir_mat = t.guard_csr * t.reset_csr.transpose()

        if guard_dir_mat.shape[0] > 0:
            agg_dir_mat = np.concatenate((agg_dir_mat, guard_dir_mat.toarray()), axis=0)
    else:
        raise RuntimeError("Unknown aggregation mode: {}".format(agg_settings.agg__mode))

    print_debug("agg dir mat:\n{}".format(agg_dir_mat))
    lpi_list = [state.lpi for state in agg_list]

    new_lpi = lputil.aggregate(lpi_list, agg_dir_mat, postmode)

    return StateSet(new_lpi, agg_list[0].mode, step_interval, op_list, is_concrete=False)
