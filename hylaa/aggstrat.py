'''
Stanley Bak
Aggregation Strategy Classes
'''

from collections import namedtuple

from hylaa import lputil
from hylaa.util import Freezable

# container class for description of how to perform a single aggregation
AggType = namedtuple('AggType', ['is_box', 'is_arnoldi_box', 'is_chull', 'add_guard'])

class AggregationStrategy(Freezable):
    '''Aggregation Strategy parent class

    An aggregation strategy controls the evolution of the AggDag. This is done by choosing which transitions create 
    the current node (aggregation), splitting existing nodes (deaggregation) and deciding if/when to stop the
    current node's continuous-post computation (pseudo-transitions).

    The default implementation in this class will perform no aggregation (pop first transition), never split nodes,
    and never stop the current computation. This means it's exact, but analysis can require an exponential amount of
    computation.
    '''

    def __init__(self):
        self.freeze_attrs()

    def init_aggdag_data(self, aggdag):
        'initialize data within the aggdag object by directly assigning to aggdag instance'

        pass

    def init_aggdag_node_data(self, aggdag_node):
        'initialize data within every aggdag node by directly assigning to the aggdag_node instance'

        pass

    def pop_waiting_list(self, waiting_list):
        '''determine which waiting list elements should be aggregated for the next continuous post computation

        waiting_list is a list of OpTransition

        this function returns a list of OpTransition. 
        If the list is a single element, no aggregation is performed.
        '''

        return [waiting_list[0]]

    def get_deagg_node(self, aggdag):
        '''Called before popping a state off the waiting list. Get the aggdag node to deaggregate (if any).
        '''

        return None

    def pretransition(self, t, t_lpi, op_transition):
        'event function, called when taking a transition before the reset is applied'

        # premode_center = lputil.get_box_center(t_lpi)
        pass

    def get_agg_type(self, op_list):
        '''
        Gets the type of aggregation to be performed for the passed in objects. 

        This returns an instance of AggType
        '''

        raise RuntimeError("Unaggregated strategy does not implement get_agg_type")

class Unaggregated(AggregationStrategy):
    'another name for the base implementation of AggregationStrategy'

class Aggregated(AggregationStrategy):
    'a fully aggregated strategy'

    AGG_BOX, AGG_ARNOLDI_BOX, AGG_CONVEX_HULL = range(3)
    POP_LOWEST_MINTIME, POP_LOWEST_AVGTIME, POP_LARGEST_MAXTIME = range(3)

    def __init__(self, agg_type=AGG_ARNOLDI_BOX, deaggregate=False):
        self.agg_type = agg_type
        self.pop_type = Aggregated.POP_LOWEST_AVGTIME

        self.add_guard = True # add the guard direction when performing aggregation
        self.require_same_path = True
        self.deaggregate = deaggregate
        self.deagg_leaves_first = True # should we deaggregate leaf nodes first?

        AggregationStrategy.__init__(self)

    def pop_waiting_list(self, waiting_list):
        '''
        Get the states to remove from the waiting list based on a score-based method
        '''

        # use score method to decide which mode to pop
        to_remove_op = waiting_list[0]
        to_remove_state = to_remove_op.poststate
        to_remove_score = self.pop_score(to_remove_state)

        for op in waiting_list:
            state = op.poststate
            score = self.pop_score(state)

            if score > to_remove_score or score == to_remove_score and state.mode.name < to_remove_state.mode.name:
                to_remove_score = score
                to_remove_state = state
                to_remove_op = op

        # remove all states for aggregation
        op_list = []

        for op in waiting_list:
            state = op.poststate
            should_add = False

            if state is to_remove_state:
                should_add = True
            elif state.mode is to_remove_state.mode:
                if not self.require_same_path:
                    should_add = True
                else: # require same path; paths are the same if the parent node and transitions match
                    if to_remove_op is None and op is None:
                        should_add = True
                    elif to_remove_op and op:
                        if to_remove_op.transition is op.transition and \
                                                    to_remove_op.parent_node is op.parent_node:
                            should_add = True

            if should_add:
                op_list.append(op)

        return op_list
    
    def pop_score(self, state):
        '''
        returns a score used to decide which state to pop off the waiting list. The state with the highest score
        will be removed first.
        '''

        if self.pop_type == Aggregated.POP_LOWEST_MINTIME:
            score = -(state.cur_steps_since_start[0])
        elif self.pop_type == Aggregated.POP_LOWEST_AVGTIME:
            score = -(state.cur_steps_since_start[0] + state.cur_steps_since_start[1])
        elif self.pop_type == Aggregated.POP_LARGEST_MAXTIME:
            score = state.cur_steps_since_start[1]
        else:
            raise RuntimeError("Unknown waiting list pop strategy: {}".format(self.pop_type))

        return score

    def pretransition(self, t, t_lpi, op_transition):
        'event function, called when taking a transition before the reset is applied'

        if self.agg_type == Aggregated.AGG_ARNOLDI_BOX:
            op_transition.premode_center = lputil.get_box_center(t_lpi)

    def get_agg_type(self, op_list):
        '''
        Gets the type of aggregation to be performed for the passed in objects. 

        This returns an instance of AggType
        '''

        return self._get_agg_type()

    def _get_agg_type(self):
        '''
        Gets the type of aggregation to be performed.
        '''
    
        is_box = self.agg_type == Aggregated.AGG_BOX
        is_arnoldi_box = self.agg_type == Aggregated.AGG_ARNOLDI_BOX
        is_chull = self.agg_type == Aggregated.AGG_CONVEX_HULL

        return AggType(is_box, is_arnoldi_box, is_chull, self.add_guard)

    def get_ancestors(self, node):
        '''
        get an ordered list of all the ancestors, starting from the root to the leaf
        '''

        rv = []

        if node.parent_ops[0].parent_node is not None:
            rv += self.get_ancestors(node.parent_ops[0].parent_node)

        rv.append(node)

        return rv

    def get_deagg_node(self, aggdag):
        '''Called before popping a state off the waiting list. Get the aggdag node to deaggregate (if any).
        '''

        rv = None

        if self.deaggregate:
            # scan the aggdag waiting list for non-concrete error mode states

            for op in aggdag.waiting_list:
                state = op.poststate
                
                if state.mode.is_error() and not state.is_concrete:
                    ancestors = self.get_ancestors(op.parent_node)

                    if self.deagg_leaves_first:
                        ancestors.reverse()

                    rv = None

                    for node in ancestors:
                        if len(node.parent_ops) > 1:
                            rv = node
                            break
                            
                    assert rv is not None, "didn't find aggregated ancestor?"
                    break

        if rv:
            aggdag.save_viz()

        return rv
