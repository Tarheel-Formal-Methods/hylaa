'''
Stanley Bak
December 2016

Utility functions/classes for star.py
'''

import itertools

import numpy as np
from hylaa.hybrid_automaton import LinearAutomatonMode, LinearAutomatonTransition
from hylaa.util import Freezable
from hylaa.glpk_interface import LpInstance

class StarParent(object):
    '''
    The parent object of a star. Used to track predecessors. This is a parent class for
    the more specific parent types:
    InitParent, ContinuousPostParent, DiscretePostParent, and AggregationParent
    '''

    def __init__(self, mode):
        self.mode = mode

        assert isinstance(mode, LinearAutomatonMode)

class InitParent(StarParent):
    'a parent which is an initial state'

    def __init__(self, mode):
        assert isinstance(mode, LinearAutomatonMode)
        StarParent.__init__(self, mode)

class ContinuousPostParent(StarParent):
    'a parent of a star which came from a continuous post operation'

    def __init__(self, mode, star):
        StarParent.__init__(self, mode)
        self.star = star

class DiscretePostParent(StarParent):
    'a parent of a star which came from a discrete post operation'

    def __init__(self, premode, prestar, prestar_basis_center, transition):
        StarParent.__init__(self, premode)
        self.transition = transition
        self.prestar = prestar
        self.prestar_basis_center = prestar_basis_center

        assert isinstance(prestar_basis_center, np.ndarray)
        assert isinstance(transition, LinearAutomatonTransition)
        assert premode == transition.from_mode

class AggregationParent(StarParent):
    'a parent of a star which resulted from guard successor aggregation'

    def __init__(self, mode, stars):
        StarParent.__init__(self, mode)

        self.stars = stars

        assert len(stars) > 1, "aggregation successor should be of 2 or more stars"

class GuardOptData(Freezable):
    'data for guard optimization'

    def __init__(self, star):
        self.star = star

        if star.settings.opt_warm_start_lp:
            self.combined_lpis = [self.make_combined_lpi(trans, skip_inputs=True) for trans in star.mode.transitions]

        if star.settings.opt_decompose_lp:
            # one lpi for every direction in every guard
            self.guard_constraint_min_list = []

            for trans in star.mode.transitions:
                num_conditions = len(trans.condition_list)
                self.guard_constraint_min_list.append([0.0] * num_conditions)

        if star.settings.opt_warm_start_lp and star.settings.opt_decompose_lp:
            self.solved_full_lp = False # gets set when the full lp is solved the first time

            self.no_input_lpis = []
            self.input_lpis = []

            for trans in star.mode.transitions:
                num_conditions = len(trans.condition_list)

                self.no_input_lpis.append([self.make_no_input_lpi() for _ in xrange(num_conditions)])
                self.input_lpis.append([self.make_input_lpi() for _ in xrange(num_conditions)])

        self.total_steps = 0
        self.freeze_attrs()

    def add_basis_constraint(self, lc):
        '''
        add a constraint which is given in the star's basis. This assumes there are no inputs.
        '''

        assert self.star.mode.num_inputs == 0, 'adding constaints w/ inputs unsupported'

        if self.star.settings.opt_warm_start_lp:
            for lpi in self.combined_lpis:
                lpi.add_basis_constraint(lc.vector, lc.value)

        if self.star.settings.opt_decompose_lp:
            for lpi in self.no_input_lpis:
                lpi.add_basis_constraint(lc.vector, lc.value)

    def make_combined_lpi(self, automaton_transition=None, skip_inputs=False):
        'create one lpi per guard, which will have both the star and input effects, as well as the guard condition'

        lpi = LpInstance(self.star.num_dims, self.star.num_dims)
        lpi.update_basis_matrix(self.star.basis_matrix)

        for lc in self.star.constraint_list:
            lpi.add_basis_constraint(lc.vector, lc.value)

        # add standard basis guard constraints
        if automaton_transition is not None:
            for lc in automaton_transition.condition_list:
                lpi.add_standard_constraint(lc.vector, lc.value)

        # add any input star constraints
        mode = self.star.mode

        if not skip_inputs and self.star.input_stars is not None:
            for input_star in self.star.input_stars:
                lpi.add_input_star(mode.u_constraints_a_t, mode.u_constraints_b, input_star.input_basis_matrix)

        return lpi

    def make_no_input_lpi(self, basis_matrix=None):
        '''make the lpi object for the input-free star, using the current star's basis matrix'''

        if basis_matrix is None:
            basis_matrix = np.zeros((self.star.num_dims, self.star.num_dims))

        rv = LpInstance(self.star.num_dims, self.star.num_dims)
        rv.update_basis_matrix(basis_matrix)

        for lc in self.star.constraint_list:
            rv.add_basis_constraint(lc.vector, lc.value)

        return rv

    def make_input_lpi(self, basis_matrix=None):
        'make the lpi object for the input star'

        rv = None

        if self.star.mode.num_inputs > 0:
            rv = LpInstance(self.star.num_dims, self.star.mode.num_inputs)

            if basis_matrix is None:
                basis_matrix = np.zeros((self.star.mode.num_inputs, self.star.num_dims))

            rv.update_basis_matrix(basis_matrix)

            for i in xrange(self.star.mode.u_constraints_b.shape[0]):
                rv.add_basis_constraint(self.star.mode.u_constraints_a[i, :], self.star.mode.u_constraints_b[i])

        return rv

    def update_from_sim(self, input_star):
        '''update the basis matrix based on the star's current basis matrix'''

        self.total_steps += 1
        mode = self.star.mode

        if mode.b_matrix is not None:
            # update combined_lpis
            if self.star.settings.opt_warm_start_lp:
                for guard_index in xrange(len(mode.transitions)):
                    combined_lpi = self.combined_lpis[guard_index]
                    combined_lpi.add_input_star(mode.u_constraints_a_t, mode.u_constraints_b,
                                                input_star.input_basis_matrix)

            # update no-input and input lpis
            if self.star.settings.opt_decompose_lp:
                for guard_index in xrange(len(mode.transitions)):
                    guard = mode.transitions[guard_index]
                    constraint_min_list = self.guard_constraint_min_list[guard_index]

                    # for each constraint, optimize in its direction and add to constraint_min_list
                    result = np.zeros(self.star.num_dims)

                    for condition_index in xrange(len(guard.condition_list)):
                        lc = guard.condition_list[condition_index]

                        # we are going to upscale the star conditions, which gives a more accurate LP result
                        # when the constraints are small (for example, for small time steps)
                        # we probably want to make this a setting or auto-detect when it's needed
                        scale = 1024.0 #65536.0 # powers of two should be marginally faster to multiply

                        input_basis_matrix = scale * input_star.input_basis_matrix

                        if not self.star.settings.opt_warm_start_lp:
                            input_lpi = self.make_input_lpi(input_basis_matrix)
                        else:
                            input_lpi = self.input_lpis[guard_index][condition_index]
                            input_lpi.update_basis_matrix(input_basis_matrix)

                        input_lpi.minimize(lc.vector, result, error_if_infeasible=True)

                        value = np.dot(result, lc.vector)

                        constraint_min_list[condition_index] += value / scale

                        if condition_index == 0 and value != 0:
                            # if we haven't solved the full LP yet, reuse the first star's solution in combined_lpi
                            if self.star.settings.opt_warm_start_lp and not self.solved_full_lp:
                                numi = mode.num_inputs
                                numcons = mode.u_constraints_a.shape[0]
                                dims = self.star.num_dims

                                cols = np.array([0] * (dims + numi), dtype=np.dtype('int8'))
                                rows = np.array([0] * (dims + numcons), dtype=np.dtype('int8'))

                                input_lpi.get_row_statuses(rows)
                                input_lpi.get_col_statuses(cols)

                                total_basic = sum([1 if stat == 1 else 0 for stat in
                                                   itertools.chain(rows[-numcons:], cols[-numi:])])

                                if total_basic != numcons:
                                    # in certain cases at certain times, the input value doesn't affect
                                    # the variables we're optimizing (the input effect is orthogonal)
                                    # in that case, the LP has multiple possible solutions, and can choose to make
                                    # both input constraints basic variables... we shouldn't try to reuse the solution
                                    # in these cases, as it's invalid in the larger problem

                                    # I added a filter for these cases above (if value != 0), so this shouldn't
                                    # happen anymore. Print a warning for now.
                                    print "Warning: Num basic vars in star LP != number of constraints in starutil.py"
                                else:
                                    # initialize the solution for the new rows / cols
                                    combined_lpi = self.combined_lpis[guard_index]
                                    combined_lpi.set_last_input_statuses(rows[-numcons:], cols[-numi:])

    def get_guard_intersection(self, guard_index):
        '''Does the star intersect the guard with the given index?
        This one first tries an optimized approach which is a sufficient condition... and only calls
        the more-expensive exact check if that one succeeds.

        returns the point where the guard condition is feasible or None if no intersection
        '''

        rv = None
        guard = self.star.mode.transitions[guard_index]
        condition_list = guard.condition_list

        result = np.zeros(self.star.num_dims)
        all_guards_possible = True

        if self.star.settings.opt_decompose_lp:
            no_input_basis_matrix = self.star.basis_matrix

            for condition_index in xrange(len(condition_list)):
                if not self.star.settings.opt_warm_start_lp:
                    no_input_lpi = self.make_no_input_lpi(basis_matrix=no_input_basis_matrix)
                else:
                    no_input_lpi = self.no_input_lpis[guard_index][condition_index]
                    no_input_lpi.update_basis_matrix(no_input_basis_matrix)

                lc = condition_list[condition_index]

                # add no_input term
                no_input_lpi.minimize(lc.vector, result)

                accumulated_min = np.dot(result, lc.vector)

                # add center term
                accumulated_min += np.dot(self.star.center, lc.vector)

                # add input term
                accumulated_min += self.guard_constraint_min_list[guard_index][condition_index]
                #print "... sum of inputs = {}".format(constraint_min_list[i])

                #print "... total = {} ?>? {}".format(accumulated_min, lc.value)

                if accumulated_min > lc.value:
                    all_guards_possible = False
                    break

        if all_guards_possible:
            rv = self.get_guard_intersection_exact(guard_index)

        return rv

    def get_guard_intersection_exact(self, guard_index):
        '''Does the star intersect the guard with the given index?
        This one uses the combined lpi to do the check (slow).

        returns the point where the guard condition is feasible or None if no intersection
        '''

        rv = None

        if not self.star.settings.opt_warm_start_lp:
            combined_lpi = self.make_combined_lpi(self.star.mode.transitions[guard_index])
        else:
            combined_lpi = self.combined_lpis[guard_index]

            # update combined_lpi to have the current basis matrix
            combined_lpi.update_basis_matrix(self.star.basis_matrix)

        # update combined_lpi to account for star.center
        constraints = self.star.mode.transitions[guard_index].condition_list
        constraint_vals = np.zeros(len(constraints))

        for i in xrange(len(constraints)):
            lc = constraints[i]
            sim_value = np.dot(self.star.center, lc.vector)

            constraint_vals[i] = lc.value - sim_value

            combined_lpi.set_standard_constraint_values(constraint_vals)

        dims = self.star.num_dims

        # possibly update solution in the combined lpi to be the solution in the no input lpi
        if self.star.settings.opt_warm_start_lp and self.star.settings.opt_decompose_lp and not self.solved_full_lp:
            self.solved_full_lp = True

            cols = np.array([0] * (dims * 2), dtype=np.dtype('int8'))
            rows = np.array([0] * (dims + len(self.star.constraint_list)), dtype=np.dtype('int8'))
            self.no_input_lpis[guard_index][0].get_row_statuses(rows)
            self.no_input_lpis[guard_index][0].get_col_statuses(cols)
            combined_lpi.set_standard_basis_statuses(rows, cols)

        # combined_lpi is now up to date. check if it's feasible
        num_inputs = self.star.mode.num_inputs
        input_dims = self.total_steps * num_inputs
        result = np.zeros(2 * dims + input_dims)

        opt_direction = np.zeros(dims)
        before_iterations = combined_lpi.total_iterations()

        if combined_lpi.minimize(opt_direction, result, error_if_infeasible=False):
            # lp was feasible

            rv = result[0:dims] + self.star.center

            ce_filename = self.star.settings.counter_example_filename
            diff_iterations = combined_lpi.total_iterations() - before_iterations

            if self.star.settings.print_output:
                print "Exact LP was feasible at step {}! Final LP iterations = {}".format(
                    self.total_steps, diff_iterations)

            if ce_filename is not None:

                if self.star.settings.print_output:
                    print "Writing counter-example to {}".format(ce_filename)

                export_counter_example(ce_filename, self.star.mode, result, self.star.center, dims, \
                    self.star.settings.step, self.total_steps, constraints[0])
            elif self.star.settings.print_output:
                print "Counter-example file disabled in settings; skipping"
        else:
            rv = None

        return rv

# helper functions for adding constraints to a star
def add_guard_to_star(star, guard_lc_list):
    '''
    Add a guard's conditions to the passed-in star.

    star - the star to add the constraints to
    guard_lc_list - the list of linear constraints in the guard
    '''

    dims = star.num_dims
    c_list = []
    vec_list = []

    for lc in guard_lc_list:
        vec_list.append([ele for ele in lc.vector])
        c_list.append([-ele for ele in vec_list[-1]] + [0.0] * dims)

        vec_list.append([-ele for ele in lc.vector])
        c_list.append([-ele for ele in vec_list[-1]] + [0.0] * dims)

    lpc = star.to_lp_constraints()
    optutil.MultiOpt.reset_per_mode_vars()
    result_list = optutil.optimize_multi(Star.solver, c_list, lpc)
    standard_center = star.center()

    for i in xrange(len(vec_list)):
        vec = vec_list[i]
        result = result_list[i]
        offset = result[0:dims]
        point = standard_center + offset

        val = np.dot(point, vec)

        # convert the condition to the star's basis
        basis_influence = np.dot(star.basis_matrix, vec)
        center_value = np.dot(standard_center, vec)
        remaining_value = val - center_value

        lc = LinearConstraint(basis_influence, remaining_value)
        star.temp_constraints.append(lc)

def add_box_to_star(star):
    '''
    Add box constraints to the passed-in star.

    star - the star to add the constraints to
    '''

    dims = star.num_dims
    c_list = []
    vec_list = []

    ortho_vec_list = [[1.0 if d == index else 0.0 for d in xrange(dims)] for index in xrange(dims)]

    for vec in ortho_vec_list:
        vec_list.append([ele for ele in vec])
        c_list.append([-ele for ele in vec_list[-1]] + [0.0] * dims)

        vec_list.append([-ele for ele in vec])
        c_list.append([-ele for ele in vec_list[-1]] + [0.0] * dims)

    lpc = star.to_lp_constraints()
    optutil.MultiOpt.reset_per_mode_vars()
    result_list = optutil.optimize_multi(Star.solver, c_list, lpc)
    standard_center = star.center()

    for i in xrange(len(vec_list)):
        vec = vec_list[i]
        result = result_list[i]
        offset = result[0:dims]
        point = standard_center + offset

        val = np.dot(point, vec)

        # convert the condition to the star's basis
        basis_influence = np.dot(star.basis_matrix, vec)
        center_value = np.dot(standard_center, vec)
        remaining_value = val - center_value

        lc = LinearConstraint(basis_influence, remaining_value)
        star.temp_constraints.append(lc)

def array_str(nums):
    'get a python-parsable spring reprentation for this list'

    if isinstance(nums, list):
        nums = np.array(nums, dtype=float)

    rv = None
    size = nums.shape[0]
    tol = 1e-12
    elements = 0

    for num in nums:
        if abs(num) > tol:
            elements += 1
    
    if size < 50 or float(elements) / size > 0.2:
        # use dense representation
        rv = '{}'.format(', '.join([str(num) for num in nums]))
    else:
        # use sparse representation

        rv = ''

        for i in xrange(size):
            num = nums[i]

            if abs(num) > tol:
                rv += '{} if i == {} else '.format(num, i)

        rv += '0.0 for i in xrange({})'.format(size)

    return '[{}]'.format(rv)

def export_counter_example(filename, mode, result, center, dims, step_size, total_steps, lc):
    'export a counter-example to a file which can be run using the HyLAA trace generator'

    end_point = result[0:dims] + center

    with open(filename, 'w') as f:

        f.write('\'Counter-example trace generated using HyLAA\'\n\n')
        f.write('import sys\n')
        f.write('import numpy as np\n')
        f.write('from hylaa.check_trace import check, plot\n\n')

        f.write('def check_instance():\n')
        f.write('    \'define parameters for one instance and call checking function\'\n\n')

        ###
        f.write('    # dynamics x\' = Ax + Bu + c\n')
        f.write('    a_matrix = np.array([\\\n')

        for row in mode.a_matrix:
            f.write('        {}, \\\n'.format(array_str(row)))

        f.write('        ])\n\n')

        if mode.b_matrix is None:
            f.write('    b_matrix = None\n')
        else:
            f.write('    b_matrix = np.array([\n')

            for row in mode.b_matrix:
                f.write('        {}, \n'.format(array_str(row)))

            f.write('        ])\n\n')

        f.write('    c_vector = np.array({})\n\n'.format(array_str(mode.c_vector)))

        ###

        if mode.b_matrix is None:
            f.write("    inputs = None\n")
        else:
            ordered_inputs = []

            inputs = list(result[2*dims:])
            inputs.reverse()

            for step in xrange(total_steps):
                offset = step * mode.num_inputs
                cur_inputs = inputs[offset:offset+mode.num_inputs]

                ordered_inputs.append([num for num in reversed(cur_inputs)])

            f.write("    inputs = []\n")

            prev_input = ordered_inputs[0]
            count = 0

            for i in xrange(len(ordered_inputs)):
                cur_input = ordered_inputs[i]

                if np.allclose(cur_input, prev_input):
                    count += 1
                else:
                    f.write("    inputs += [{}] * {}\n".format(array_str(prev_input), count))
                    prev_input = cur_input
                    count = 1

            f.write("    inputs += [{}] * {}\n\n".format(array_str(prev_input), count))

        ###

        f.write("    end_point = [{}]\n".format(", ".join([str(num) for num in end_point])))
        f.write("    start_point = [{}]\n\n".format(", ".join([str(num) for num in result[dims:2*dims]])))

        ###
        f.write('    step = {}\n'.format(step_size))
        f.write('    max_time = {}\n\n'.format(step_size * total_steps))

        ###

        f.write('    normal_vec = [{}]\n'.format(", ".join([str(num) for num in lc.vector])))
        f.write('    normal_val = {}\n\n'.format(lc.value))

        #####################
        f.write('    sim_states, sim_times = check(a_matrix, b_matrix, c_vector, step, max_time, start_point, ' + \
            'inputs, end_point)\n\n')
        f.write('    if len(sys.argv) < 2 or sys.argv[1] != "noplot":\n')
        f.write('        plot(sim_states, sim_times, inputs, normal_vec, normal_val, max_time, step)\n\n')

        f.write('if __name__ == "__main__":\n')
        f.write('    check_instance()\n')
