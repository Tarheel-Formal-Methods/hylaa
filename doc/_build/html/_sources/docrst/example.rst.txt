Getting Started + Examples
==========================

The easiest way to get started with Hylaa is to run some of the examples. Once installed and setup, Hylaa models are just python source files you directly with `python3` in a terminal.

Go to `examples/harmonic_oscillator` and run `ha.py` from the command line (`python ha.py`). This should create `plot.png` in the same folder, which will be an 2-d plot of the reachable set.

The dynamics in this example are given as x' = **A** x, where **A** is the (potentially sparse) dynamics matrix. This is defined in the `define_ha` function in the `ha.py` source file.

Initial states and unsafe states are given as conjunctions of linear constraints. These are defined in the `make_init` function.

Finally, computation settings are given in the `define_settings` function. There are lots of settings that can be adjusted, which can be found in `hylaa/settings.py`, including comments describing what each one does.

The easiest way to use Hylaa on your example is to copy an example from the examples folder and edit that. Notice that models are python code, which means you can
create the model programatically using loops or by loading the dynamics from a .mat file.
