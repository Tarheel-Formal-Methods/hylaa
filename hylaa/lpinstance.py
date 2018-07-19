'''
Stanley Bak
May 2018
GLPK python <-> C++ interface
'''

import numpy as np
from scipy.sparse import csr_matrix, csc_matrix
import swiglpk as glpk

from hylaa.util import Freezable

class LpInstance(Freezable):
    'Linear programming wrapper using glpk (through swiglpk python interface)'

    def __init__(self):
        'initialize the lp instance'

        self.lp = glpk.glp_create_prob()

        # these are assigned on set_reach_vars()
        self.dims = None
        self.basis_mat_pos = None # 2-tuple
        self.cur_vars_offset = None

        # internal bookkeeping
        self.obj_cols = [] # columns in the LP with an assigned objective coefficient

        self.freeze_attrs()

    def clone(self):
        'create a copy of this lp instance'

        rv = LpInstance()

        glpk.glp_copy_prob(rv.lp, self.lp, glpk.GLP_ON)

        rv.set_reach_vars(self.dims, self.basis_mat_pos)
        rv.obj_cols = self.obj_cols.copy()

        return rv

    def set_reach_vars(self, dims, basis_mat_pos):
        'set reachability variables'

        num_rows = self.get_num_rows()
        num_cols = self.get_num_cols()

        assert basis_mat_pos[0] + dims <= num_rows
        assert basis_mat_pos[1] + 2 * dims <= num_cols  # need >= 2*dims for cur_time vars somewhere to the right of BM

        self.dims = dims
        self.basis_mat_pos = basis_mat_pos
        self.cur_vars_offset = num_cols - dims # right-most variables

    def __del__(self):
        if hasattr(self, 'lp') and self.lp is not None:
            glpk.glp_delete_prob(self.lp)
            self.lp = None

    def __str__(self):
        'get the LP as string (useful for debugging)'

        lp = self.lp

        rows = glpk.glp_get_num_rows(lp)
        cols = glpk.glp_get_num_cols(lp)

        rv = "Lp has {} columns (variables) and {} rows (constraints)\n".format(cols, rows)

        inds = glpk.intArray(cols + 1)
        vals = glpk.doubleArray(cols + 1)

        # the column names
        rv += "   "

        for col in range(1, cols + 1):
            name = glpk.glp_get_col_name(lp, col)
            name = "-" if name is None else name
            
            if len(name) < 6:
                name = (" " * (6 - len(name))) + name
            else:
                name = name[0:6]
                    
            rv += name + " "

        rv += "\n"

        # optimization direction
        rv += "min"

        for col in range(1, cols + 1):
            num = str(glpk.glp_get_obj_coef(lp, col))
            
            if len(num) < 6:
                num = (" " * (6 - len(num))) + num
            else:
                num = num[0:6]
                    
            rv += num + " "

        rv += "\nsubject to:\n"

        #  the column statuses
        stat_labels = ["?(0)?", "BS", "NL", "NU", "NF", "NS", "?(6)?"]
        rv += "   "

        for col in range(1, cols + 1):
            rv += "{:>6} ".format(stat_labels[glpk.glp_get_col_stat(lp, col)])

        rv += "\n"

        for row in range(1, rows + 1):
            rv += "{} ".format(stat_labels[glpk.glp_get_row_stat(lp, row)])

            num_inds = glpk.glp_get_mat_row(lp, row, inds, vals)

            for col in range(1, cols + 1):
                val = 0

                for index in range(1, num_inds+1):
                    if inds[index] == col:
                        val = vals[index]
                        break

                num = str(val)
                if len(num) < 6:
                    num = (" " * (6 - len(num))) + num
                else:
                    num = num[0:6]

                rv += num + " "

            row_type = glpk.glp_get_row_type(lp, row)

            if row_type == glpk.GLP_FX:
                val = glpk.glp_get_row_ub(lp, row)
                rv += " == "
            elif row_type == glpk.GLP_UP:
                val = glpk.glp_get_row_ub(lp, row)
                rv += " <= "
            elif row_type == glpk.GLP_LO:
                val = glpk.glp_get_row_lb(lp, row)
                rv += " >= "
            else:
                rv += " <?> (unknown bounds)"
                val = None

            if val is not None:
                num = str(val)
                if len(num) < 6:
                    num = (" " * (6 - len(num))) + num
                else:
                    num = num[0:6]

                rv += num

            rv += "\n"

        return rv

    def add_cols(self, names):
        'add a certain number of columns to the LP'

        assert isinstance(names, list)

        num_cols = glpk.glp_get_num_cols(self.lp)

        glpk.glp_add_cols(self.lp, len(names))

        for i, name in enumerate(names):
            glpk.glp_set_col_bnds(self.lp, num_cols + i + 1, glpk.GLP_FR, 0, 0)  # free variable (bounds -inf to inf)

            glpk.glp_set_col_name(self.lp, num_cols + i + 1, name)

    def add_rows_less_equal(self, rhs_vec):
        '''add rows to the LP with <= constraints

        rhs_vector is the right-hand-side values of the constriants
        '''

        if isinstance(rhs_vec, list):
            rhs_vec = np.array(rhs_vec, dtype=float)

        assert isinstance(rhs_vec, np.ndarray) and len(rhs_vec.shape) == 1, "expected 1-d right-hand-side vector"

        num_rows = glpk.glp_get_num_rows(self.lp)

        # create new row for each constraint
        glpk.glp_add_rows(self.lp, len(rhs_vec))

        for i, rhs in enumerate(rhs_vec):
            glpk.glp_set_row_bnds(self.lp, num_rows + i + 1, glpk.GLP_UP, 0, rhs)  # '<=' constraint

    def add_rows_equal_zero(self, num):
        '''add rows to the LP with == 0 constraints'''

        num_rows = glpk.glp_get_num_rows(self.lp)

        # create new row for each constraint
        glpk.glp_add_rows(self.lp, num)

        for i in range(num):
            glpk.glp_set_row_bnds(self.lp, num_rows + i + 1, glpk.GLP_FX, 0, 0)  # '== 0' constraints

    def set_constraints_csr(self, csr_mat, offset=None):
        '''set the constrains row by row to be equal to the passed-in csr matrix

        offset is an optional tuple (num_rows, num_cols) which tells you the top-left offset for the assignment
        '''

        assert isinstance(csr_mat, csr_matrix)

        if offset is None:
            offset = (0, 0)

        assert len(offset) == 2, "offset should be a 2-tuple (num_rows, num_cols)"

        # check that the matrix is in bounds
        lp_rows = glpk.glp_get_num_rows(self.lp)
        lp_cols = glpk.glp_get_num_cols(self.lp)

        if offset[0] < 0 or offset[1] < 0 or \
                            offset[0] + csr_mat.shape[0] > lp_rows or offset[1] + csr_mat.shape[1] > lp_cols:
            raise RuntimeError("Error: set constraints matrix out of bounds (offset was " + \
                "{}, matrix size was {}), but lp size was ({}, {})".format(
                    offset, csr_mat.shape, lp_rows, lp_cols))

        # actually set the constraints row by row
        indptr = csr_mat.indptr
        indices = csr_mat.indices
        data_list = csr_mat.data.tolist()

        for row in range(csr_mat.shape[0]):
            # we must copy the indices since glpk is offset by 1 :(
            count = int(indptr[row + 1] - indptr[row])
            indices_vec = glpk.intArray(count + 1)
            v_index = 1

            for index in range(indptr[row], indptr[row + 1]):
                indices_vec[v_index] = 1 + offset[1] + int(indices[index])
                v_index += 1

            data_row_list = data_list[indptr[row]:indptr[row+1]]
            data_ptr = glpk.as_doubleArray(data_row_list)

            glpk.glp_set_mat_row(self.lp, offset[0] + row + 1, count, indices_vec, data_ptr)

    def set_constraints_csc(self, csc_mat, offset=None):
        '''set the constrains column by column to be equal to the passed-in csc matrix

        offset is an optional tuple (num_rows, num_cols) which tells you the top-left offset for the assignment
        '''

        assert isinstance(csc_mat, csc_matrix)

        if offset is None:
            offset = (0, 0)

        assert len(offset) == 2, "offset should be a 2-tuple (num_rows, num_cols)"

        # check that the matrix is in bounds
        lp_rows = glpk.glp_get_num_rows(self.lp)
        lp_cols = glpk.glp_get_num_cols(self.lp)

        if offset[0] < 0 or offset[1] < 0 or \
                            offset[0] + csc_mat.shape[0] > lp_rows or offset[1] + csc_mat.shape[1] > lp_cols:
            raise RuntimeError(("Error: set constraints matrix out of bounds (offset was " + \
                "{}, matrix size was {}), but lp size was ({}, {})").format(
                    offset, csc_mat.shape, lp_rows, lp_cols))

        # actually set the constraints col by col
        indptr = csc_mat.indptr
        indices = csc_mat.indices
        data_list = csc_mat.data.tolist()

        for col in range(csc_mat.shape[1]):
            # we must copy the indices since glpk is offset by 1 :(
            count = int(indptr[col + 1] - indptr[col])

            indices_vec = glpk.intArray(count + 1)
            indices_vec_copy = [0] * (count + 1)
            v_index = 1

            for index in range(indptr[col], indptr[col + 1]):
                indices_vec[v_index] = 1 + offset[0] + int(indices[index])
                indices_vec_copy[v_index] = 1 + offset[0] + int(indices[index])
                v_index += 1

            data_row_list = data_list[indptr[col]:indptr[col+1]]
            data_ptr = glpk.as_doubleArray(data_row_list)

            glpk.glp_set_mat_col(self.lp, offset[1] + col + 1, count, indices_vec, data_ptr)

    def set_minimize_direction(self, direction_vec, is_csr=False):
        '''set the direction for the optimization in terms of the current-time variables
        '''

        # set the previous objective columns to zero
        for i in self.obj_cols:
            glpk.glp_set_obj_coef(self.lp, i, 0)

        self.obj_cols = []

        if is_csr:
            assert isinstance(direction_vec, csr_matrix)
            assert direction_vec.shape[0] == 1
            assert direction_vec.shape[1] <= self.dims, "dirLen({}) > dims({})".format(len(direction_vec), self.dims)

            data, inds, indptr = direction_vec.data, direction_vec.indices, direction_vec.indptr
            
            for n in range(indptr[1]):
                col = int(1 + self.cur_vars_offset + inds[n])
                self.obj_cols.append(col)

                glpk.glp_set_obj_coef(self.lp, col, data[n])

        else: # non-csr
            if not isinstance(direction_vec, np.ndarray):
                direction_vec = np.array(direction_vec, dtype=float)

            assert len(direction_vec.shape) == 1
            assert len(direction_vec) <= self.dims, "dirLen({}) > dims({})".format(len(direction_vec), self.dims)

            for i, direction in enumerate(direction_vec):
                col = int(1 + self.cur_vars_offset + i)
                self.obj_cols.append(col)
                glpk.glp_set_obj_coef(self.lp, col, direction)

    def reset_lp(self):
        'reset all the column and row statuses of the LP'

        # set the status of all columns to GLP_NF and all rows are GLP_BS
        rows = glpk.glp_get_num_rows(self.lp)
        cols = glpk.glp_get_num_cols(self.lp)

        for r in range(rows):
            glpk.glp_set_row_stat(self.lp, r + 1, glpk.GLP_BS)

        for c in range(cols):
            glpk.glp_set_col_stat(self.lp, c + 1, glpk.GLP_NF)

    def minimize(self, direction_vec=None, columns=None, fail_on_unsat=True):
        '''minimize the lp

        if direction_vec is not None, this will first assign the optimization direction
        if columns is not None, will only return the requested columns (default= all columns)

        returns None if UNSAT, otherwise the optimization result. Use columns=[] if you're not interested in the result
        '''

        if direction_vec is not None:
            self.set_minimize_direction(direction_vec)

        # setup lp params
        params = glpk.glp_smcp()
        glpk.glp_init_smcp(params)
        params.msg_lev = glpk.GLP_MSG_OFF

        simplex_res = glpk.glp_simplex(self.lp, params)

        if simplex_res != 0:
            # sometimes the previous solution is singular wrt. current constraints.
            # for example, if the previous solution is on an orthogonal subspace to the current solution after
            # changing the basis matrix. Try resetting the solution and resolving.
            self.reset_lp()

            simplex_res = glpk.glp_simplex(self.lp, params)

        # process simplex result
        rv = self.process_simplex_result(simplex_res, columns)

        if rv is None and fail_on_unsat:
            raise RuntimeError("minimize returned UNSAT and fail_on_unsafe was True")

        return rv

    def process_simplex_result(self, simplex_res, columns):
        '''process the result of a glp_simplex call

        returns None on UNSAT, otherwise the optimization result with the requested columns
        if columns is None, will return full result
        '''

        rv = None

        if simplex_res == glpk.GLP_ENOPFS:  # no primal feasible w/ presolver
            rv = None
        elif simplex_res != 0: # simplex failed, report the error
            codes = [glpk.GLP_EBADB, glpk.GLP_ESING, glpk.GLP_ECOND, glpk.GLP_EBOUND, glpk.GLP_EFAIL, glpk.GLP_EOBJLL,
                     glpk.GLP_EOBJUL, glpk.GLP_EITLIM, glpk.GLP_ETMLIM, glpk.GLP_ENOPFS, glpk.GLP_ENODFS]

            msgs = [ \
                "Unable to start the search, because the initial basis specified " + \
                "in the problem object is invalid—the number of basic (auxiliary " + \
                "and structural) variables is not the same as the number of rows " + \
                "in the problem object.", 

                "Unable to start the search, because the basis matrix corresponding " + \
                "to the initial basis is singular within the working " + \
                "precision.",

                "Unable to start the search, because the basis matrix corresponding " + \
                "to the initial basis is ill-conditioned, i.e. its " + \
                "condition number is too large.",

                "Unable to start the search, because some double-bounded " + \
                "(auxiliary or structural) variables have incorrect bounds.",

                "The search was prematurely terminated due to the solver " + \
                "failure.",

                "The search was prematurely terminated, because the objective " + \
                "function being maximized has reached its lower " + \
                "limit and continues decreasing (the dual simplex only).",

                "The search was prematurely terminated, because the objective " + \
                "function being minimized has reached its upper " + \
                "limit and continues increasing (the dual simplex only).",

                "The search was prematurely terminated, because the simplex " + \
                "iteration limit has been exceeded.",

                "The search was prematurely terminated, because the time " + \
                "limit has been exceeded.",

                "The LP problem instance has no primal feasible solution " + \
                "(only if the LP presolver is used).",

                "The LP problem instance has no dual feasible solution " + \
                "(only if the LP presolver is used).",
                ]

            for code, message in zip(codes, msgs):
                if simplex_res == code:
                    raise RuntimeError("glp_simplex returned nonzero status ({}): {}".format(code, message))

            raise RuntimeError("glp_simplex returned nonzero status ({}): Unknown Error".format(simplex_res))
        else:
            status = glpk.glp_get_status(self.lp)

            if status == glpk.GLP_NOFEAS: # infeasible
                rv = None
            elif status == glpk.GLP_OPT: # optimal
                lp_cols = glpk.glp_get_num_cols(self.lp)
                
                if columns is None:
                    rv = np.zeros(lp_cols)
                else:
                    rv = np.zeros(len(columns))

                # copy the output vars
                rv_len = len(rv)
                
                for i in range(rv_len):
                    col = i if columns is None else columns[i]

                    assert 0 <= col < lp_cols, "out of bounds column requested in LP solution: {}".format(col)

                    rv[i] = glpk.glp_get_col_prim(self.lp, int(col + 1))

            else: # neither infeasible nor optimal (for example, unbounded)
                codes = [glpk.GLP_OPT, glpk.GLP_FEAS, glpk.GLP_INFEAS, glpk.GLP_NOFEAS, glpk.GLP_UNBND, glpk.GLP_UNDEF]
                msgs = ["solution is optimal",
                        "solution is feasible",
                        "solution is infeasible",
                        "problem has no feasible solution",
                        "problem has unbounded solution",
                        "solution is undefined"]

                for code, message in zip(codes, msgs):
                    if status == code:
                        raise RuntimeError("LP status after solving in minimize() was '{}': {}".format(message, code))

                raise RuntimeError("LP status after solving in minimize() was <Unknown>: {}".format(status))

        return rv

    def flip_constraint(self, row_index):
        '''flip a constraint from >= to <= or vis-versa

        returns True if the constraint is now a '<=' constraint
        '''

        rows = glpk.glp_get_num_rows(self.lp)

        assert 0 <= row_index < rows, "Invalid row ({}) passed to flip_constraint() (lp has {})".format(
            row_index, rows)

        row_type = glpk.glp_get_row_type(self.lp, row_index + 1)

        if row_type == glpk.GLP_UP:
            val = glpk.glp_get_row_ub(self.lp, row_index + 1)
            glpk.glp_set_row_bnds(self.lp, row_index + 1, glpk.GLP_LO, val, 0)
            rv = False
        elif row_type == glpk.GLP_LO:
            val = glpk.glp_get_row_lb(self.lp, row_index + 1)
            glpk.glp_set_row_bnds(self.lp, row_index + 1, glpk.GLP_UP, 0, val)
            rv = True
        else:
            raise RuntimeError("Invalid constraint type {} in row {} in flipConstraint()\n".format(row_type, row_index))

        return rv

    def del_constraint(self, row_index):
        '''delete a constraint from the lp'''

        rows = glpk.glp_get_num_rows(self.lp)

        assert 0 <= row_index < rows, "Invalid row ({}) passed to del_constraint() (lp has {})".format(
            row_index, rows)

        nrs = 1
        rows = glpk.intArray(2)
        rows[1] = row_index + 1

        glpk.glp_del_rows(self.lp, nrs, rows)

    def set_constraint_rhs(self, row_index, rhs):
        '''change an existing constraint's right hand side'''

        rows = glpk.glp_get_num_rows(self.lp)

        assert 0 <= row_index < rows, "Invalid row ({}) in set_constraint_rhs() (lp has {})".format(
            row_index, rows)

        row_type = glpk.glp_get_row_type(self.lp, row_index + 1)

        if row_type == glpk.GLP_UP:
            glpk.glp_set_row_bnds(self.lp, row_index + 1, glpk.GLP_UP, 0, rhs)
        elif row_type == glpk.GLP_LO:
            glpk.glp_set_row_bnds(self.lp, row_index + 1, glpk.GLP_LO, rhs, 0)
        elif row_type == glpk.GLP_FX:
            glpk.glp_set_row_bnds(self.lp, row_index + 1, glpk.GLP_FX, rhs, rhs)
        else:
            raise RuntimeError("Invalid constraint type {} in row {} in set_constraint_rhs()".format(
                row_type, row_index))

    def get_types(self):
        '''get the constraint types. These are swiglpk.GLP_FX, swiglpk.GLP_UP, or swiglpk.GLP_LO'''

        lp_rows = glpk.glp_get_num_rows(self.lp)
        rv = np.zeros(lp_rows, dtype=int)

        for row in range(lp_rows):
            rv[row] = glpk.glp_get_row_type(self.lp, row + 1)

        return rv

    def get_dense_constraints(self, x, y, w, h):
        'get a subconstraint matrix from the lpi as a dense matrix'

        rv = np.zeros((h, w))

        lp_rows = glpk.glp_get_num_rows(self.lp)
        lp_cols = glpk.glp_get_num_cols(self.lp)

        assert x >= 0 and w >= 0 and x + w <= lp_cols, "invalid x range requested"
        assert y >= 0 and h >= 0 and y + h <= lp_rows, "invalid y range requested"

        inds_row = glpk.intArray(lp_cols + 1)
        vals_row = glpk.doubleArray(lp_cols + 1)

        for row in range(y + 1, y + h + 1):
            row_offset = row - (y + 1)
            got_len = glpk.glp_get_mat_row(self.lp, row, inds_row, vals_row)

            for i in range(1, got_len+1):
                if inds_row[i] > x and inds_row[i] <= x + w:
                    col_offset = inds_row[i] - (x + 1)
                    rv[row_offset, col_offset] = vals_row[i]
                    
        return rv

    def get_names(self):
        '''get the symbolic names of each column'''

        cols = glpk.glp_get_num_cols(self.lp)
        rv = []

        for col in range(cols):
            rv.append(glpk.glp_get_col_name(self.lp, col + 1))

        return rv

    def get_rhs(self):
        '''get the rhs vector of the constraints'''

        lp_rows = glpk.glp_get_num_rows(self.lp)
        rv = np.zeros(lp_rows, dtype=float)

        for row in range(lp_rows):
            row_type = glpk.glp_get_row_type(self.lp, row + 1)

            if row_type in [glpk.GLP_FX, glpk.GLP_UP]:
                rv[row] = glpk.glp_get_row_ub(self.lp, row + 1)
            elif row_type == glpk.GLP_LO:
                rv[row] = glpk.glp_get_row_ub(self.lp, row + 1)
            else:
                raise RuntimeError("Error: Unsupported type ({}) in getRhs() in row {}".format(row_type, row))

        return rv

    def get_full_constraints(self):
        '''get the LP matrix as a csr_matrix
        '''

        lp_rows = glpk.glp_get_num_rows(self.lp)
        lp_cols = glpk.glp_get_num_cols(self.lp)
        nnz = glpk.glp_get_num_nz(self.lp)

        data = np.zeros((nnz,), dtype=float)
        inds = np.zeros((nnz,), dtype=np.int32)
        indptr = np.zeros((lp_rows+1,), dtype=np.int32)

        inds_row = glpk.intArray(lp_cols + 1)
        vals_row = glpk.doubleArray(lp_cols + 1)
        data_index = 0
        indptr[0] = 0

        for row in range(1, lp_rows + 1):
            got_len = glpk.glp_get_mat_row(self.lp, row, inds_row, vals_row)

            for i in range(1, got_len + 1):
                data[data_index] = vals_row[i]
                inds[data_index] = inds_row[i] - 1
                data_index += 1

            indptr[row] = data_index

        csr_mat = csr_matrix((data, inds, indptr), shape=(lp_rows, lp_cols), dtype=float)
        csr_mat.check_format()

        return csr_mat

    def get_row(self, row):
        '''get a row of the LP matrix as a csr_matrix
        '''

        lp_rows = glpk.glp_get_num_rows(self.lp)
        lp_cols = glpk.glp_get_num_cols(self.lp)

        assert 0 <= row < lp_rows

        inds_row = glpk.intArray(lp_cols + 1)
        vals_row = glpk.doubleArray(lp_cols + 1)

        got_len = glpk.glp_get_mat_row(self.lp, row+1, inds_row, vals_row)

        data = np.zeros((got_len,), dtype=float)
        inds = np.zeros((got_len,), dtype=np.int32)
        data_index = 0

        for i in range(1, got_len + 1):
            data[data_index] = vals_row[i]
            inds[data_index] = inds_row[i] - 1
            data_index += 1

        indptr = [0, data_index]
        csr_mat = csr_matrix((data, inds, indptr), shape=(1, lp_cols), dtype=float)
        csr_mat.check_format()

        return csr_mat

    def get_num_rows(self):
        'get the number of rows in the lp'

        return glpk.glp_get_num_rows(self.lp)

    def get_num_cols(self):
        'get the number of columns in the lp'

        return glpk.glp_get_num_cols(self.lp)

    def get_iterations(self):
        'get the number of LP iterations performed so far'

        return glpk.glp_get_it_cnt(self.lp)
