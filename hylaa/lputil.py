'''
LP Utilities

This assumes a common LP structure, where the
first N columns correspond to the current-time variables, and
the first N rows are the current-time constraints (equality constraints equal to zero)
'''

import math

import numpy as np
import scipy as sp
from scipy.sparse import csr_matrix, csc_matrix

from hylaa.lpinstance import LpInstance
from hylaa.timerutil import Timers

def from_box(box_list, mode):
    'make a new lp instance from a passed-in box'

    rhs = []

    for lb, ub in box_list:
        assert lb <= ub, "lower bound ({}) > upper bound ({})".format(lb, ub)
        rhs.append(-lb)
        rhs.append(ub)

    # make constraints as csr_matrix
    dims = len(box_list)
    data = []
    inds = []
    indptr = [0]

    # -1 <= -lb
    # 1 <= ub
    for n in range(dims):
        data.append(-1)
        inds.append(n)
        indptr.append(len(data))

        data.append(1)
        inds.append(n)
        indptr.append(len(data))

    csr = csr_matrix((data, inds, indptr), shape=(2*dims, dims), dtype=float)
    csr.check_format()

    return from_constraints(csr, rhs, mode)

def from_constraints(csr, rhs, mode):
    'make a new lp instance from a passed-in set of constraints and rhs'

    if not isinstance(csr, csr_matrix):
        csr = csr_matrix(csr, dtype=float)

    if not isinstance(rhs, np.ndarray):
        rhs = np.array(rhs, dtype=float)

    assert len(rhs.shape) == 1
    assert csr.shape[0] == len(rhs)
    assert is_feasible(csr, rhs), "initial constraints are not feasible"
    
    dims = csr.shape[1]

    lpi = LpInstance()
    lpi.add_rows_equal_zero(dims)

    names = ["m{}_i{}".format(mode.mode_id, var_index) for var_index in range(dims)]
    names += ["m{}_c{}".format(mode.mode_id, var_index) for var_index in range(dims)]
    
    lpi.add_cols(names)

    lpi.add_rows_less_equal(rhs)

    has_inputs = mode.b_csr is not None

    if has_inputs:
        names = ["m{}_ti{}".format(mode.mode_id, n) for n in range(dims)]
        lpi.add_cols(names)

    # make constraints as csr_matrix
    data = []
    inds = []
    indptr = [0]

    # I -I for first n rows
    for n in range(dims):
        data.append(1)
        inds.append(n)

        data.append(-1)
        inds.append(dims + n)

        if has_inputs:
            data.append(1)
            inds.append(2*dims+n)

        indptr.append(len(data))
        
    num_cols = 2*dims if not has_inputs else 3*dims
    basis_constraints = csr_matrix((data, inds, indptr), shape=(dims, num_cols), dtype=float)
    basis_constraints.check_format()

    lpi.set_constraints_csr(basis_constraints)

    # add constraints on initial conditions
    lpi.set_constraints_csr(csr, offset=(dims, 0))

    # add total input effects
    if has_inputs:
        rows_before = lpi.get_num_rows()
        ie_pos = (rows_before, 2*dims)
        lpi.add_rows_equal_zero(dims)

        # -I
        csr = -1 * sp.sparse.identity(dims, dtype=float, format='csr')
        lpi.set_constraints_csr(csr, offset=ie_pos)
    else:
        ie_pos = None

    lpi.set_reach_vars(dims, (0, 0), dims, ie_pos)

    return lpi

def set_basis_matrix(lpi, basis_mat):
    'modify the lpi in place to set the basis matrix'

    assert basis_mat.shape[0] == basis_mat.shape[1], "expected square matrix"
    assert basis_mat.shape[0] == lpi.dims, "basis matrix wrong shape"

    # do it row by row, assume -I is first part, and last N is basis matrix

    # make constraints as csr_matrix
    data = []
    inds = []
    indptr = [0]

    # 0 BM 0 -I 0 (I? <- if inputs exist)
    for row in range(lpi.dims):
        for col in range(lpi.dims):
            data.append(basis_mat[row, col])
            inds.append(col + lpi.basis_mat_pos[1])
            
        data.append(-1)
        inds.append(lpi.cur_vars_offset + row)

        if lpi.input_effects_offsets is not None:
            data.append(1)
            inds.append(row + lpi.input_effects_offsets[1])

        indptr.append(len(data))

    mat = csr_matrix((data, inds, indptr), shape=(lpi.dims, lpi.get_num_cols()), dtype=float)

    mat.check_format()
        
    lpi.set_constraints_csr(mat, offset=(lpi.basis_mat_pos[0], 0))

def add_input_effects_matrix(lpi, input_mat, mode):
    'add an input effects matrix to this lpi'

    assert lpi.input_effects_offsets is not None
    assert mode.b_csr is not None
    assert mode.b_csr.shape[1] == input_mat.shape[1]
    assert input_mat.shape[0] == mode.a_csr.shape[0]
    assert lpi.dims == mode.a_csr.shape[0]

    num_inputs = input_mat.shape[1]
    num_constraints = len(mode.u_constraints_rhs)

    # add new row/cols
    names = ["m{}_I{}".format(mode.mode_id, i) for i in range(num_inputs)]
    pre_cols = lpi.get_num_cols()
    lpi.add_cols(names)

    pre_rows = lpi.get_num_rows()
    lpi.add_rows_less_equal(mode.u_constraints_rhs)

    # set constaints on the rows/cols, as well as the input basis matrix using a csc_matrix
    data = []
    inds = []
    indptr = [0]

    for c in range(num_inputs):
        # input basis matrix column c
        for row in range(lpi.dims):
            data.append(input_mat[row, c])
            inds.append(row + lpi.input_effects_offsets[0])

        # constraints_csr column c
        for i in range(mode.u_constraints_csc.indptr[c], mode.u_constraints_csc.indptr[c+1]):
            row = mode.u_constraints_csc.indices[i]
            val = mode.u_constraints_csc.data[i]

            data.append(val)
            inds.append(pre_rows + row)

        indptr.append(len(data))

    num_rows = pre_rows + num_constraints
    
    csc = csc_matrix((data, inds, indptr), shape=(num_rows, num_inputs), dtype=float)
    csc.check_format()

    lpi.set_constraints_csc(csc, offset=(0, pre_cols))

def check_intersection(lpi, lc, tol=1e-13):
    '''check if there is an intersection between the LP constriants and the LinearConstraint object lc

    This solves an LP optimizing in the given direction... without adding the constraint to the LP
    '''

    Timers.tic("check_intersection")

    lpi.set_minimize_direction(lc.csr, is_csr=True)

    columns = lc.csr.indices[0:lc.csr.indptr[1]]
    lp_columns = [lpi.cur_vars_offset + c for c in columns]

    lp_res = lpi.minimize(columns=lp_columns)

    dot_res = np.dot(lc.csr.data, lp_res)

    Timers.toc("check_intersection")

    return dot_res + tol <= lc.rhs

def add_init_constraint(lpi, vec, rhs, basis_matrix=None, input_effects_list=None):
    '''
    add a constraint to the lpi

    this adds a new row, with constraints assigned to the right-most variables (where the basis matrix is)

    this returns the row of the newly-created constraint
    '''

    if basis_matrix is None:
        basis_matrix = get_basis_matrix(lpi)

    assert isinstance(basis_matrix, np.ndarray)

    # we need to project the basis matrix using the passed in direction vector
    preshape = vec.shape
    
    dims = basis_matrix.shape[0]
    vec.shape = (1, dims) # vec is now the projection matrix for this direction
    bm_projection = np.dot(vec, basis_matrix)

    lpi.add_rows_less_equal([rhs])

    rows = lpi.get_num_rows()
    cols = lpi.get_num_cols()

    indptr = [0]

    # basis matrix
    inds = [lpi.basis_mat_pos[1] + i for i in range(dims)]
    data = [val for val in bm_projection[0]]

    # each of the input effects matrices
    if input_effects_list:
        num_inputs = input_effects_list[0].shape[1]
        offset = lpi.input_effects_offsets[1] + dims
        
        for ie_mat in input_effects_list:
            ie_projection = np.dot(vec, ie_mat)
            assert len(ie_projection) == num_inputs

            inds += [offset + i for i in range(num_inputs)]
            data += [val for val in ie_projection[0]]
            offset += num_inputs
 
    indptr.append(len(data))

    csr_row_mat = csr_matrix((data, inds, indptr), dtype=float, shape=(1, cols))
    csr_row_mat.check_format()

    lpi.set_constraints_csr(csr_row_mat, offset=(rows-1, 0))

    # restore vector shape to what it was when passed in
    vec.shape = preshape

    return rows - 1

def try_replace_init_constraint(lpi, old_row_index, direction, rhs, basis_mat=None, input_effects_list=None):
    '''replace the constraint in row_index by a new constraint, if the new constraint is stronger, otherwise
    create new constriant

    this is used for removing redundant invariant constraints

    This returns row_index, if the constriant is replaced, or the new row index of the new constraint
    '''

    if basis_mat is None:
        basis_mat = get_basis_matrix(lpi)

    # how can we check if the passed in constraint is stronger than the existing one?
    # if negating the existing constraint, and adding the new one is UNSAT
    rv = None

    lpi.flip_constraint(old_row_index)

    new_row_index = add_init_constraint(lpi, direction, rhs, basis_matrix=basis_mat, \
                                        input_effects_list=input_effects_list)

    is_sat = lpi.minimize(columns=[], fail_on_unsat=False) is not None

    lpi.flip_constraint(old_row_index) # flip it back

    if is_sat:
        # keep both constraints
        rv = new_row_index
    else:
        # keep only the new constraint
        
        # delete new constraint row
        lpi.del_constraint(new_row_index)

        # replace the old constraint row with the new constraint condition
        dims = basis_mat.shape[0]

        indptr = [0, dims]
        inds = [i for i in range(dims)]
        new_vec = np.dot(direction, basis_mat) # convert the constraint using the basis matrix
        data = new_vec
        data.shape = (dims,)

        csr_row_mat = csr_matrix((data, inds, indptr), dtype=float, shape=(1, dims))
        csr_row_mat.check_format()

        lpi.set_constraints_csr(csr_row_mat, offset=(old_row_index, lpi.basis_mat_pos[1]))
        lpi.set_constraint_rhs(old_row_index, rhs)

        rv = old_row_index

    return rv

def aggregate(lpi_list, direction_matrix, mode):
    '''
    return a new lpi consisting of an aggregation of the passed-in lpi list

    This creates a template polytope using the passed-in directions (passed in as rows of direction_matrix).

    use lputil.make_direction_matrix() to create the direction_matrix with arnoldi directions
    '''

    assert isinstance(direction_matrix, np.ndarray)
    assert direction_matrix.dtype == float
    assert direction_matrix.shape[0] >= direction_matrix.shape[1], "expected num directions >= dims"
    assert len(lpi_list) > 1, "expected more than one lpi to perform an aggregation"

    inds = []
    data = []
    indptrs = [0]
    rhs = []

    # for each direction, minimize and maximize it within the list
    for direction in direction_matrix:
        if abs(np.linalg.norm(direction)) < 1e-6:
            continue
        #assert abs(np.linalg.norm(direction) - 1) < 1e-9, "expected normalized directions, got {}".format(direction)

        dir_inds = [i for i, x in enumerate(direction) if x != 0]
        dir_data = [x for x in direction if x != 0]
        dir_neg_data = [-x for x in dir_data]

        max_val = -np.inf
        min_val = np.inf
       
        for lpi in lpi_list:
            assert direction_matrix.shape[1] == lpi.dims

            dir_columns = [i + lpi.cur_vars_offset for i in dir_inds]

            result = lpi.minimize(direction_vec=-direction, columns=dir_columns)
            max_val = max(max_val, np.dot(result, dir_data))
            
            result = lpi.minimize(direction_vec=direction, columns=dir_columns)
            min_val = min(min_val, np.dot(result, dir_data))

        inds += dir_inds
        data += dir_data
        indptrs.append(len(data))
        rhs.append(max_val)

        inds += dir_inds
        data += dir_neg_data
        indptrs.append(len(data))
        rhs.append(-min_val)

    rows = len(indptrs) - 1
    cols = direction_matrix.shape[1]
    csr_mat = csr_matrix((data, inds, indptrs), dtype=float, shape=(rows, cols))
    csr_mat.check_format()
    
    return from_constraints(csr_mat, rhs, mode)

def get_basis_matrix(lpi):
    'get the basis matrix from the lpi'

    return lpi.get_dense_constraints(lpi.basis_mat_pos[0], lpi.basis_mat_pos[1], lpi.dims, lpi.dims)

def add_reset_variables(lpi, mode_id, transition_index, # pylint: disable=too-many-locals, too-many-statements
                        reset_csr=None, minkowski_csr=None,
                        minkowski_constraints_csr=None, minkowski_constraints_rhs=None, successor_has_inputs=False): 
    '''
    add variables associated with a reset

    general resets are of the form x' = Rx + My, Cy <= rhs, where y are fresh variables
    the reset_minkowski variables can be None if no new variables are needed. If unassigned, the identity
    reset is assumed

    x' are the new variables
    x are the old variables       
    reset_csr is R (None -> identity)
    minkowski_csr is M
    minkowski_constraints_csr is C
    minkowski_constraints_rhs is rhs

    this function adds new variables for both the initial states and the current states in the new mode
    '''

    old_dims = lpi.dims
    cols = lpi.get_num_cols()
    rows = lpi.get_num_rows()

    if reset_csr is None:
        reset_csr = sp.sparse.identity(old_dims, dtype=float, format='csr')

    if minkowski_csr is None:
        minkowski_csr = csr_matrix((0, 0))
        minkowski_constraints_csr = csr_matrix((0, 0))
        minkowski_constraints_rhs = np.array([])

    assert isinstance(reset_csr, csr_matrix)
    assert isinstance(minkowski_csr, csr_matrix)
    assert old_dims == reset_csr.shape[1], "Reset matrix shape is wrong (expected {} cols)".format(old_dims)

    # it may be possible to change the number of dimensions between modes
    new_dims = reset_csr.shape[0]

    min_vars = minkowski_csr.shape[1]

    names = ["reset{}".format(min_var) for min_var in range(min_vars)]
    names += ["m{}_i0_t{}".format(mode_id, transition_index)]

    names += ["m{}_i{}".format(mode_id, d) for d in range(1, new_dims)]
    names += ["m{}_c{}".format(mode_id, d) for d in range(new_dims)]

    if successor_has_inputs:
        names += ["m{}_ti{}".format(mode_id, d) for d in range(new_dims)]
    
    lpi.add_cols(names)

    lpi.add_rows_equal_zero(2*new_dims)

    lpi.add_rows_less_equal(minkowski_constraints_rhs)

    if successor_has_inputs:
        lpi.add_rows_equal_zero(new_dims)

    data = []
    inds = []
    indptrs = [0]

    # new_init_vars = reset_mat * old_cur_vars + minkow_csr * minkow_vars:
    # -I for new mode initial vars, RM for old mode cur_vars, MK for minkow_vars
    for dim in range(new_dims):

        # old cur_vars
        for index in range(reset_csr.indptr[dim], reset_csr.indptr[dim + 1]):
            rm_col = reset_csr.indices[index]
            value = reset_csr.data[index]
            
            data.append(value)
            inds.append(lpi.cur_vars_offset + rm_col)

        # minkow_vars
        if minkowski_csr.shape[1] > 0:
            for index in range(minkowski_csr.indptr[dim], minkowski_csr.indptr[dim + 1]):
                minkowski_col = minkowski_csr.indices[index]
                value = minkowski_csr.data[index]

                data.append(value)
                inds.append(cols + minkowski_col)

        # new mode initial vars
        data.append(-1)
        inds.append(cols + min_vars + dim)

        indptrs.append(len(data))

    # new_cur_vars = BM * new_init_vars: -I for new cur vars, BM (initially identity) for new init vars
    for dim in range(new_dims):
        data.append(1)
        inds.append(cols + min_vars + dim)

        data.append(-1)
        inds.append(cols + min_vars + new_dims + dim)

        if successor_has_inputs:
            data.append(1)
            inds.append(cols + min_vars + 2*new_dims + dim)

        indptrs.append(len(data))

    # encode minkowski constraint rows
    for row in range(minkowski_constraints_csr.shape[0]):
        for index in range(minkowski_constraints_csr.indptr[row], minkowski_constraints_csr.indptr[row + 1]):
            col = minkowski_constraints_csr.indices[index]
            value = minkowski_constraints_csr.data[index]
            
            data.append(value)
            inds.append(cols + col)

        indptrs.append(len(data))

    # encode total input effects
    if successor_has_inputs:
        for dim in range(new_dims):
            data.append(-1)
            inds.append(cols + min_vars + 2*new_dims + dim)

            indptrs.append(len(data))

    height = 2*new_dims + len(minkowski_constraints_rhs)
    width = cols + 2*new_dims + min_vars

    if successor_has_inputs:
        height += new_dims
        width += new_dims

    mat = csr_matrix((data, inds, indptrs), dtype=float, \
                     shape=(height, width))
    mat.check_format()

    lpi.set_constraints_csr(mat, offset=(rows, 0))

    # input effects position
    if successor_has_inputs:
        ie_x = cols + min_vars + 2*new_dims
        ie_y = rows + 2*new_dims + len(minkowski_constraints_rhs)
        ie_offsets = (ie_y, ie_x)
    else:
        ie_offsets = None

    basis_mat_pos = (rows+new_dims, cols + minkowski_csr.shape[1])
    cur_vars_offset = cols + minkowski_csr.shape[1] + new_dims
    
    lpi.set_reach_vars(new_dims, basis_mat_pos, cur_vars_offset, ie_offsets)

def add_curtime_constraints(lpi, csr, rhs_vec):
    '''
    add constraints to the lpi

    this adds them on the current time variables (not the initial time variables)
    '''

    assert isinstance(csr, csr_matrix)

    prerows = lpi.get_num_rows()
    lpi.add_rows_less_equal(rhs_vec)

    lpi.set_constraints_csr(csr, offset=(prerows, lpi.cur_vars_offset))

def get_box_center(lpi):
    '''get the center of the box overapproximation of the passed-in lpi'''

    dims = lpi.dims
    pt = []

    for dim in range(dims):
        col = lpi.cur_vars_offset + dim
        min_dir = [1 if i == dim else 0 for i in range(dims)]
        max_dir = [-1 if i == dim else 0 for i in range(dims)]
        
        min_val = lpi.minimize(direction_vec=min_dir, columns=[col])[0]
        max_val = lpi.minimize(direction_vec=max_dir, columns=[col])[0]

        pt.append((min_val + max_val) / 2.0)

    return pt

def make_direction_matrix(point, a_csr):
    '''make the direction matrix for arnoldi aggregation

    this is a set of full rank, linearly-independent vectors, extracted from the dynamics using something
    similar to the arnoldi iteration

    the null-space vectors first try to be filled with the orthonormal directions, and then by random vectors

    point is the point where to sample the dynamics
    a_csr is the dynamics matrix
    '''

    Timers.tic('make_direction_matrix')

    assert isinstance(a_csr, csr_matrix)
    cur_vec = np.array(point, dtype=float)
    
    assert len(point) == a_csr.shape[1], "expected point dims({}) to equal A-matrix dims({})".format( \
                len(point), a_csr.shape[1])
    
    dims = len(point)
    rv = []

    while len(rv) < dims:
        if cur_vec is None: # inside the null space
            # first try to pick orthonormal directions if we can
            for d in range(dims):
                found_nonzero = False

                for vec in rv:
                    if vec[d] != 0:
                        found_nonzero = True
                        break

                if found_nonzero is False:
                    cur_vec = np.array([1 if n == d else 0 for n in range(dims)], dtype=float)
                    break

            # if that didn't work, just a random vector
            if cur_vec is None:
                cur_vec = np.random.rand(dims,)
        else:
            cur_vec = a_csr * cur_vec

        # project out the previous vectors
        for prev_vec in rv:
            dot_val = np.dot(prev_vec, cur_vec)

            cur_vec -= prev_vec * dot_val

        norm = np.linalg.norm(cur_vec, 2)

        assert not math.isinf(norm) and not math.isnan(norm), "vector norm was infinite in arnoldi"

        if norm < 1e-6:
            # super small norm... basically it's in the subspace spanned by previous vectors, restart
            cur_vec = None
        else:
            cur_vec = cur_vec / norm

            rv.append(cur_vec)

    Timers.toc('make_direction_matrix')

    return np.array(rv, dtype=float)

def reorthogonalize_matrix(mat, dims):
    '''given an input matrix (one 'dims'-dimensional vector per row), return a new matrix such that the vectors are in 
    the same order, but orthonormal (project out earlier vectors and scale), with the passed-in number of dimensions 
    (a smaller matrix may be returned, or new vectors may be generated to fill the nullspace if the dims > dim(mat)'''

    if isinstance(mat, list):
        mat = np.array(mat, dtype=float)

    assert mat.shape[1] == dims, "mat should have width equal to dims({})".format(dims)

    # take approach similar to arnoldi, except without the matrix-vector multiplication (see make_direction_matrix)

    Timers.tic('reorthogonalize_matrix')

    rv = []

    next_index = 0

    while len(rv) < dims:
        if next_index >= mat.shape[0]:
            # first try to pick orthonormal directions if we can
            for d in range(dims):
                found_nonzero = False

                for vec in rv:
                    if vec[d] != 0:
                        found_nonzero = True
                        break

                if found_nonzero is False:
                    cur_vec = np.array([1 if n == d else 0 for n in range(dims)], dtype=float)
                    break

            # if that didn't work, just a random vector
            if cur_vec is None:
                cur_vec = np.random.rand(dims,)
        else:
            cur_vec = mat[next_index]
            next_index += 1

        # project out the previous vectors
        for prev_vec in rv:
            dot_val = np.dot(prev_vec, cur_vec)

            cur_vec -= prev_vec * dot_val

        norm = np.linalg.norm(cur_vec, 2)

        assert not math.isinf(norm) and not math.isnan(norm), "vector norm was infinite in arnoldi"

        if norm < 1e-6:
            # super small norm... basically it's in the subspace spanned by previous vectors, restart
            cur_vec = None
        else:
            cur_vec = cur_vec / norm

            rv.append(cur_vec)

    Timers.toc('reorthogonalize_matrix')

    return np.array(rv, dtype=float)

def is_feasible(csr, rhs):
    'are the passed in constraints feasible?'

    if not isinstance(csr, csr_matrix):
        csr = csr_matrix(csr, dtype=float)

    assert len(rhs) == csr.shape[0], "constraints RHS differs from number of rows"

    lpi = LpInstance()
    names = ["x{}".format(n) for n in range(csr.shape[1])]
    lpi.add_cols(names)
    lpi.add_rows_less_equal(rhs)

    lpi.set_constraints_csr(csr)

    return lpi.is_feasible()

def is_point_in_lpi(point, orig_lpi):
    '''is the passed-in point in the lpi?

    This function is strictly for unit testing as it's slow (copies the lpi). 
    A warning is printed to stdout to reflect this and discourage usage in other places.
    '''

    print("Warning: Using testing function lputil.is_point_in_lpi (slow)")

    assert len(point) == orig_lpi.dims

    inds = []
    data = []
    indptr = [0]
    rhs = []

    for i, x in enumerate(point):
        inds.append(i)
        data.append(1)
        indptr.append(len(data))
        rhs.append(x)

        inds.append(i)
        data.append(-1)
        indptr.append(len(data))
        rhs.append(-x)

    rows = len(indptr) - 1
    cols = len(point)
    csr = csr_matrix((data, inds, indptr), dtype=float, shape=(rows, cols))

    lpi = orig_lpi.clone()
    add_curtime_constraints(lpi, csr, rhs)

    return lpi.is_feasible()
