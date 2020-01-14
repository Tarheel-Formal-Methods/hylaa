"""
.. module:: util
.. moduleauthor:: Stanley Bak

General python utilities, which aren't necessary specific to Hylaa's objects.
Methods/Classes in this one shouldn't require non-standard imports.
"""

import os
import sys

class Freezable():
    """
    An object whose attributes can be frozen (prevent new attributes from being created)
    """

    _frozen = False

    def freeze_attrs(self):
        """Prevents any new attributes from being created in the object"""
        self._frozen = True

    def __setattr__(self, key, value):
        if self._frozen and not hasattr(self, key):
            raise TypeError("{} does not contain attribute '{}' (object was frozen)".format(self, key))

        object.__setattr__(self, key, value)

def get_script_path(filename):
    """Returns the path of this script, pass in __file__ for the filename

       :param filename: name of script
       :returns: the real path of script
    """
    return os.path.dirname(os.path.realpath(filename))

def matrix_to_string(m):
    """Returns string representatiion of matrix

       :param m: matrix
       :returns: string representation of matrix
    """
    return "\n".join([", ".join([str(val) for val in row]) for row in m])

DID_PYTHON3_CHECK = False

if not DID_PYTHON3_CHECK:
    # check that we're using python 3
    if sys.version_info < (3, 0) :
        sys.stdout.write("Hylaa requires Python 3, but was run with Python {}.{}.\n".format(
            sys.version_info[0], sys.version_info[1]))
        sys.exit(1)
