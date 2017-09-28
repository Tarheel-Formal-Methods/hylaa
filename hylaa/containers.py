'''
Hylaa Containers File
Stanley Bak
September 2016
'''

import math

from hylaa.util import Freezable

class HylaaSettings(Freezable):
    'Settings for the computation'

    def __init__(self, step, max_time, plot_settings=None):
        if plot_settings is None:
            plot_settings = PlotSettings()

        assert isinstance(plot_settings, PlotSettings)

        self.step = step # simulation step size
        self.num_steps = int(math.ceil(max_time / step))

        self.plot = plot_settings

        self.print_output = True # print status and waiting list information to stdout
        self.skip_step_times = False # print the times at each step

        self.print_lp_on_error = False # upon reaching an error mode, print LP and exit (no counter-example)
        self.counter_example_filename = 'counterexample.py' # the counter-example filename to create on errors
        self.simulation = SimulationSettings(step)

        self.freeze_attrs()

class SimulationSettings(Freezable):
    'simulation settings container'

    # simulation mode (matrix-exp)
    MATRIX_EXP = 0 # matrix exp every step
    EXP_MULT = 1 # first step matrix exp, remaining steps matrix-vector multiplication
    KRYLOV = 2 # krylov method

    # guard optimization mode
    GUARD_DECOMPOSED = 0
    GUARD_FULL_LP = 1

    def __init__(self, step):
        self.step = step
        self.sim_mode = SimulationSettings.EXP_MULT
        self.guard_mode = SimulationSettings.GUARD_FULL_LP

        self.check_answer = False # double-check answer using MATRIX_EXP at each step (slow!)
        self.check_answer_abs_tol = 1e-6 # absolute tolerance when checking answer

        self.krylov_use_gpu = False # use GPU with krylov method? (False = CPU)
        self.krylov_profiling = False # print krylov profiling data?

        # accuracy settings. If you don't have enough accuracy, decrease rel error and increase samples
        self.krylov_rel_error = 1e-7 # desired relative error of projV * exmp(H * end_time)
        self.krylov_rel_error_samples = 9 # number of samples for checking rel_error
        self.krylov_use_odeint = True # use odeint instead of expm for computing expm(t*v)
        self.krylov_odeint_simtol = 1e-9 # if using odeint, use this simulation error tolerance for atol and rtol
        self.krylov_check_all_rel_error = None # amount for relative error check for all dimensions (None = skip)
        self.krylov_reject_zero_rel_error = True # if result is all zeros, force increasing arnoldi_iter
        self.krylov_force_arnoldi_iter = None # force a fixed arnoldi iteration count

        self.krylov_seperate_constant_vars = True # seperate constant initial variables optimization (krylov only)
        self.krylov_multithreaded_arnoldi_expm = False # use multiple threads to pipeline arnoldi and expm
        self.krylov_multithreaded_rel_error = False # use multiple threads to pipeline rel_error calculation

        # profiling setting, if assigned this will print the relative error at each arnoldi iteration to the given file 
        # and stedout for the first group of initial vectors, and then exit immediately
        self.krylov_print_rel_error_filename = None 

        self.freeze_attrs()

class PlotSettings(Freezable):
    'plot settings container'

    PLOT_NONE = 0 # don't plot (for performance measurement)
    PLOT_FULL = 1 # plot the computation video live
    PLOT_INTERACTIVE = 2 # step-by-step live plotting with buttons
    PLOT_IMAGE = 3 # save the image plot to a file
    PLOT_VIDEO = 4 # save animation to a video file
    PLOT_MATLAB = 5 # create a matlab script which visualizes the reachable region

    def __init__(self):
        self.plot_mode = PlotSettings.PLOT_NONE

        self.xdim_dir = 0 # plotting x dimension direction
        self.ydim_dir = 1 # plotting y dimension direction

        self.plot_size = (12, 8) # inches
        self.label = LabelSettings() # plot title, axis labels, font sizes, ect.

        self.num_angles = 512 # how many evenly-spaced angles to put into plot_vecs

        self.extra_lines = None # extra lines to draw on the plot. list of lists of x,y pairs
        self.extra_lines_color = 'gray' # color of extra lines
        self.extra_lines_width = 2 # width of extra lines
        self.reachable_poly_width = 2 # width of reachable polygon outlines

        self.min_frame_time = 0.025 # max 40 fps. This allows multiple frames to be drawn at once if they're fast.

        self.extend_plot_range_ratio = 0.1 # extend plot axis range 10% at a time
        self.anim_delay_interval = 0 # milliseconds, extra delay between frames

        self.filename = None # used with PLOT_VIDEO AND PLOT_IMAGE

        self.video = None # instance of VideoSettings

        self.grid = True
        self.grid_xtics = None # override default xtics value, for example np.linspace(0.0, 5.0, 1.0)
        self.grid_ytics = None # override default ytics value, for example np.linspace(0.0, 5.0, 1.0)

        self.plot_traces = True
        self.max_shown_polys = 512 # thin out the reachable set if we go over this number of polys (optimization)
        self.draw_stride = 1 # draw every 2nd poly, 4th, ect.

        # these are useful for testing / debugging
        self.skip_frames = 0 # number of frames to process before we start drawing
        self.skip_show_gui = False # should we skip showing the graphical interface

        self.freeze_attrs()

    def make_video(self, filename, frames=100, fps=20):
        'update the plot settings to produce a video'

        self.plot_mode = PlotSettings.PLOT_VIDEO

        # turn off artificial delays
        self.anim_delay_interval = 0 # no extra delay between frames
        self.min_frame_time = 0 # draw every frame

        self.filename = filename

        # this should make it look a little sharper, but it will take longer to plot
        self.num_angles = 1024

        # looks better (but takes longer to plot)
        self.extend_plot_range_ratio = 0.0

        video = VideoSettings()
        video.frames = frames
        video.fps = fps

        self.video = video

class VideoSettings(Freezable):
    'settings for video'

    def __init__(self):
        self.codec = 'libx264'
        self.frames = None # number of frames in the video, matplotlib maxes out at 100 frame if not set
        self.fps = 20 # number of frames per second

        self.freeze_attrs()

class LabelSettings(Freezable):
    'settings for labels such as plot title, plot font size, ect.'

    def __init__(self):
        self.x_label = None
        self.y_label = None
        self.title = None

        self.title_size = 32
        self.label_size = 24
        self.tick_label_size = 18
        self.axes_limits = None # fixed axes limits; a 4-tuple (xmin, xmax, ymin, ymax) or None for auto

        self.freeze_attrs()

    def big(self, size=30):
        'increase sizes of labels'

        self.title_size = size
        self.label_size = size
        self.tick_label_size = int(0.9 * size)

    def turn_off(self):
        'turn off plot labels'

        self.x_label = ''
        self.y_label = ''
        self.title = ''

class HylaaResult(Freezable):
    'Result, assigned to engine.result after computation'

    def __init__(self):
        self.timers = None # map of string (timer name) -> TimerData
        self.safe = True # was the verificaation result safe?

        self.arnoldi_iter = None # list of number of arnoldi iterations used (0 = fixed terms)

        self.freeze_attrs()
