'''
Hybrid Automaton generic definition for Hylaa
Stanley Bak (Sept 2016)
'''

import numpy as np
from scipy.sparse import csc_matrix, csr_matrix

from hylaa.util import Freezable

def add_time_var(a_matrix, b_matrix=None):
    '''
    modify the matrix and init state to add a time variable (this adds two rows and cols)

    if both a_matrix and b_matrix are passed in, this returns a tuple (a_matrix, b_matrix)
    else, if only a_matrix is passed in, this simply returns a_matrix
    '''

    rv = None
    n = a_matrix.shape[0]
    assert a_matrix.shape[1] == n
    assert isinstance(a_matrix, csc_matrix)

    nnz = len(a_matrix.data)
    data = np.concatenate((a_matrix.data, [1]))
    indptr = np.concatenate((a_matrix.indptr, [nnz, nnz + 1]))
    indices = np.concatenate((a_matrix.indices, [n]))
    a_matrix = csc_matrix((data, indices, indptr), shape=(n + 2, n + 2))

    if b_matrix is None:
        rv = a_matrix
    else:
        assert b_matrix.shape[0] == n
        assert isinstance(b_matrix, csc_matrix)

        # add two rows of zeros to b_matrix
        b_matrix = csc_matrix((b_matrix.data, b_matrix.indices, b_matrix.indptr), shape=(n+2, b_matrix.shape[1]))

        rv = (a_matrix, b_matrix)

    return rv

def add_zero_cols(mat, num_new_cols):
    '''
    modify the csc_matrix by adding a certain number of nonzero columns
    '''

    mat = csc_matrix(mat)
    nnz = len(mat.data)

    rows = mat.shape[0]
    cols = mat.shape[1]

    indptr = np.concatenate((mat.indptr, [nnz, nnz]))

    return csc_matrix((mat.data, mat.indices, indptr), shape=(rows, cols + num_new_cols))

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

        assert isinstance(a_matrix, csc_matrix)
        assert len(a_matrix.shape) == 2
        assert a_matrix.shape[0] == a_matrix.shape[1]

        if b_matrix is not None:
            assert isinstance(b_matrix, csc_matrix)
            assert b_matrix.shape[0] == a_matrix.shape[0]

        if self.parent.dims is None:
            self.parent.dims = a_matrix.shape[0]

        if self.parent.inputs is None:
            self.parent.inputs = 0 if b_matrix is None else b_matrix.shape[1]

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
        assert matrix.shape[1] == self.parent.dims

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
