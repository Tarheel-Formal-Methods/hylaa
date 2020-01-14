Installation Instructions
=========================

This version of Hylaa runs in `python3` and requires a few other libraries that you can install with `pip3`, the python package manager. You must also set your `PYTHONPATH` environment variable so that it knows where the hylaa source is located. There is a `Dockerfile` in this repository which is used as part of our continuous integration framework that has step by step commands for installing the necessary packages and dependencies. This serves as the installation documentation, as it's always up to date.

Required Python Packages
========================
- sympy
- swiglpk
- termcolor
- numpy
