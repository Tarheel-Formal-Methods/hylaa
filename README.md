# Hylaa #

<p align="center"> <img src="hylaa_logo_small.png" alt="Hylaa Logo"/> </p>

Hylaa (**HY**brid **L**inear **A**utomata **A**nalyzer) is a verification tool for system models with linear ODEs, time-varying inputs, and possibly hybrid dynamics. 

This is the hybrid branch of Hylaa, where we're working on a new analysis method for hybrid automata.

The latest version of Hylaa is always available on our github repository at https://github.com/stanleybak/hylaa . A website for Hylaa is maintained at http://stanleybak.com/hylaa .

The code was mostly written by Stanley Bak (http://stanleybak.com) with input from Parasara Sridhar Duggirala (http://engr.uconn.edu/~psd). Work on this branch was also done by Dung Hoang Tran. 

Hylaa is released under the GPL v3 license (see the LICENSE file). Earlier versions have been approved for public release (DISTRIBUTION A: Approved for public release; distribution unlimited #88ABW-2016-5976, 22 NOV 2016).

### Installation ###

Hylaa is mostly written in Python, with a few C++ parts (linear programming solving, multithreaded matrix multiplication). You'll need to get a few required libraries, compiles the C++ portions as shared libraries, and then setup the evnironment variables. Then, to run a model you simply do 'python modelname.py'. 

These instructions are made for an Ubuntu system. Other systems may work but you'll need to adapt the instructions accordinly

# Install Packages #

sudo apt-get update
sudo apt-get install python-numpy python-scipy python-matplotlib python-psutil python-pip make
sudo pip install --upgrade pip numpy scipy

# Compile GLPK Interface as Shared Library #

This a custom C++ interface to GLPK for use in Hylaa that you need to compile. See hylaa/glpk-interface/README for details on how to do this. Essentially, you need to get glpk-4.60 (which may be newer than what comes with Ubuntu), and then run make (the Makefile is in that folder). This will produce hylaa_glpk.so.

# Compile Fast Matrix Multiplication as Shared Library #

Go to hylaa/fast_mult and run make. This should produce fast_mult.so.

# Setup PYTHONPATH Environment Variable #

A Hylaa model is given in python code, which imports the hylaa classes, creates a model definition and settings objects, and then calls a function with these objects. The hylaa folder contains the python package. You should add the parent folder of the hylaa folder to your PYTHONPATH environment variable. On Linux, this can be done by updating your ~/.profile or ~/.bashrc to include:

export PYTHONPATH="${PYTHONPATH}:/path/to/parent/of/hylaa/folder"

After you do this, you may need to restart the terminal (for ~/.bashrc) or log out and log back in (for ~/.profile), or otherwise ensure the environment variable is updated (do echo $PYTHONPATH to see if it includes the correct folder). Once this is done, you should be able to run the example models.

# Video export (optional #
For .mp4 (and other format) video export, ffmpeg is used. Make sure you can run the command ffmpeg from a terminal for this to work.

### Getting Started + Example ###

The easiest way to get started with Hylaa is to run some of the examples. Models in Hylaa are defined in python code (more on the input format in the next section), and the tool is executed using python as well.

Go to `examples/harmonic_oscillator` and run `ha.py` from the command line (`python ha.py`). This should create `plot.png` in the same folder, which will be an 2-d plot of the reachable set.  

The dynamics in Hylaa are given as x' = **A**x, where **A** is the sparse dynamics matrix. Initial states and unsafe states are given as conjunctions of linear constraints in an initial and output space. If you want to provide these using the normal state variables, just use the identity matrix as the initial and output spaces... although this may impact efficiency in high dimensions.

You can see the 4-d system in the timed harmonic oscialltor case and the error states defined in the `define_ha` function in ha.py. Try changing the dynamics slightly and re-running the script to see the effect.

Computation settings are given in the `define_settings` function. To switch from plotting a static image to a live plot during the computation, for example, change `plot_settings.plot_mode` to be `PlotSettings.PLOT_FULL`. Lots of settings exist in Hylaa (plotting mode, verification options, ect.). The default settings are generally okay, as long as you provide the time bound and time step size. If you want to do more advanced things such as select between cpu and gpu, or fix the number of arnoldi iterations rather that auto-tune it, or select the auto-tuning relative error threshold, the settings is the way to do that. All of them, as well as comments describing them can be found in `hylaa/settings.py`.

The easiest way to use Hylaa on your example is to copy an example from the examples folder and edit that. Notice that it's python code that creates the sparse A matrix. This means you can create the model programatically using loops (as we do in the heat system) or by loading the dynamics from a .mat file (as we do for MNA5).

