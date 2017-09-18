'''
Hybrid Automaton generic definition for Hylaa
Stanley Bak (Sept 2016)
'''

import numpy as np
from scipy.sparse import csr_matrix

from hylaa.util import Freezable

def make_constraint_matrix(bounds_list):
    'make a constraints matrix and rhs vector from a list of bounds in each dimension'

    dims = len(bounds_list)
    values = []
    indices = []
    indptr = []
    constraint_rhs = []

    for dim in xrange(dims):
        lb, ub = bounds_list[dim]
        assert lb <= ub, "lower bound ({}) should be less than upper bound ({})".format(lb, ub)

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

    init_mat = csr_matrix((values, indices, indptr), shape=(2*dims, dims), dtype=float)
    init_rhs = np.array(constraint_rhs, dtype=float)

    return (init_mat, init_rhs)

def make_seperated_constraints(bounds_list):
    '''
    make a constraints matrix for the non-fixed varialbles, and return a list of tuples for the fixed ones
    The constraint matrix has one extra variable (the fixed variables), which is constrained to 1

    returns (init_mat, init_rhs, [variable_dim1, ...], [(fixed_dim1, fixed_val1), ...])

    '''

    dims = len(bounds_list)
    values = []
    indices = []
    indptr = []
    constraint_rhs = []

    fixed_dim_tuples = []
    variable_dim_list = []

    dim_index = 0

    for dim in xrange(dims):
        lb, ub = bounds_list[dim]
        assert lb <= ub, "lower bound ({}) should be less than upper bound ({})".format(lb, ub)

        if abs(lb-ub) < 1e-13:
            fixed_dim_tuples.append((dim, lb))
        else:
            # upper bound
            values.append(1)
            indices.append(dim_index)
            indptr.append(2*dim_index)
            constraint_rhs.append(ub)

            # lower bound
            values.append(-1)
            indices.append(dim_index)
            indptr.append(2*dim_index+1)
            constraint_rhs.append(-lb)

            variable_dim_list.append(dim)
            dim_index = dim_index + 1

    # add one more constraint for the fixed variables
    lb = ub = 1

    # upper bound
    values.append(1)
    indices.append(dim_index)
    indptr.append(2*dim_index)
    constraint_rhs.append(ub)

    # lower bound
    values.append(-1)
    indices.append(dim_index)
    indptr.append(2*dim_index+1)
    constraint_rhs.append(-lb)

    dim_index = dim_index + 1

    indptr.append(len(values))

    init_mat = csr_matrix((values, indices, indptr), shape=(2*dim_index, dim_index), dtype=float)
    init_rhs = np.array(constraint_rhs, dtype=float)

    return (init_mat, init_rhs, variable_dim_list, fixed_dim_tuples)

class HyperRectangle(object):
    'An n-dimensional box'

    def __init__(self, dims):
        self.dims = dims # list of tuples

        for d in xrange(len(dims)):
            low = dims[d][0]
            high = dims[d][1]
            assert low <= high, "Invalid Hyperrectange: dim #{} min({}) > max({})".format(
                d, low, high)

    def center(self):
        'Returns a point in the center of the box'
        rv = []

        for d in self.dims:
            rv.append((d[0] + d[1]) / 2.0)

        return rv

    def diamond(self):
        'Returns a list of the so-called diamond points of this box (2*dims of them)'
        center = self.center()
        num_dims = len(self.dims)
        rv = []

        for index in xrange(num_dims):
            # min edge in dimension d
            pt = list(center)
            pt[index] = self.dims[index][0]
            rv.append(pt)

            # max edge in dimension d
            pt = list(center)
            pt[index] = self.dims[index][1]
            rv.append(pt)

        return rv

    def unique_corners(self, tol=1e-9):
        'Returns a list of the unique corner points of this box (up to 2^dims of them)'
        rv = []
        num_dims = len(self.dims)

        # compute max iterator index and make is_flat list
        max_iterator = 1
        is_flat = []

        for d in xrange(num_dims):
            if abs(self.dims[d][0] - self.dims[d][1]) > tol:
                is_flat.append(False)
                max_iterator *= 2
            else:
                is_flat.append(True)

        for it in xrange(max_iterator):
            point = []

            # construct point
            for d in xrange(num_dims):
                if is_flat[d]:
                    point.append(self.dims[d][0])
                else:
                    min_max_index = it % 2
                    point.append(self.dims[d][min_max_index])
                    it /= 2

            # append constructed point
            rv.append(point)

        return rv

class LinearAutomatonMode(Freezable):
    'A single mode of a hybrid automaton'

    def __init__(self, parent, name):
        self.name = name

        # dynamics are x' = Ax + Bu
        self.a_matrix = None
        self.b_matrix = None

        self.parent = parent
        self.transitions = [] # outgoing transitions

        self.freeze_attrs()

    def set_dynamics(self, a_matrix, b_matrix=None):
        'sets the autonomous system dynamics'

        assert isinstance(a_matrix, csr_matrix)
        assert len(a_matrix.shape) == 2
        assert a_matrix.shape[0] == a_matrix.shape[1]

        if b_matrix is not None:
            assert isinstance(b_matrix, csr_matrix)
            assert b_matrix.shape[0] == a_matrix.shape[0], "B-mat shape {} incompatible with A-mat shape {}".format(
                b_matrix.shape, a_matrix.shape)

        if self.parent.dims is None:
            self.parent.dims = a_matrix.shape[0]
        else:
            assert self.parent.dims == a_matrix.shape[0]

        if self.parent.inputs is None:
            self.parent.inputs = 0 if b_matrix is None else b_matrix.shape[1]
        else:
            assert self.parent.inputs == b_matrix.shape[1]

        if self.parent.inputs == 0:
            assert b_matrix is None
        else:
            assert b_matrix.shape[1] == self.parent.inputs

        assert a_matrix.shape[0] == self.parent.dims, \
            "Hybrid Automaton has {} dimensions, but a_matrix.shape was {}".format(self.parent.dims, a_matrix.shape)

        self.a_matrix = a_matrix
        self.b_matrix = b_matrix

    def __str__(self):
        return '[LinearAutomatonMode: {}]'.format(self.name)

class LinearAutomatonTransition(Freezable):
    'A transition of a hybrid automaton'

    def __init__(self, parent, from_mode, to_mode):
        self.parent = parent
        self.from_mode = from_mode
        self.to_mode = to_mode

        # mat * vars <= rhs
        self.guard_matrix = None
        self.guard_rhs = None

        self.freeze_attrs()

        from_mode.transitions.append(self)

    def set_guard(self, matrix, rhs):
        '''set the guard matrix and right-hand side. The transition is enabled if
        matrix * var_list <= rhs
        '''

        assert isinstance(matrix, csr_matrix)
        assert isinstance(rhs, np.ndarray)

        assert rhs.shape == (matrix.shape[0],)
        assert matrix.shape[1] == self.parent.dims, "guard constraint len({}) does not equal matrix dims ({})".format(
            matrix.shape[1], self.parent.dims)

        self.guard_matrix = matrix
        self.guard_rhs = rhs

    def __str__(self):
        return self.from_mode.name + " -> " + self.to_mode.name

class LinearHybridAutomaton(Freezable):
    'The hybrid automaton'

    def __init__(self, name='HybridAutomaton', dims=None, inputs=None):
        self.name = name
        self.modes = {}
        self.transitions = []
        self.dims = dims
        self.inputs = inputs

        self.freeze_attrs()

    def new_mode(self, name):
        '''add a mode'''
        m = LinearAutomatonMode(self, name)
        self.modes[m.name] = m
        return m

    def new_transition(self, from_mode, to_mode):
        '''add a transition'''
        t = LinearAutomatonTransition(self, from_mode, to_mode)
        self.transitions.append(t)

        return t
