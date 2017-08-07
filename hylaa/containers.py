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

        self.counter_example_filename = 'counterexample.py' # the counter-example filename to create on errors
        self.simulation = SimulationSettings(step)

        self.freeze_attrs()

class SimulationSettings(Freezable):
    'simulation settings container'

    # simulation mode (matrix-exp)
    MATRIX_EXP = 0 # matrix exp every step
    EXP_MULT = 1 # first step matrix exp, remaining steps matrix-vector multiplication
    KRYLOV_KRYPY = 2 # krylov method using Krypy Packet
    KRYLOV_CUSP = 3 # krylov method using CUSP Packet and GPU, computation can be done in host memory/device memory

    # krylov method setting
    KRYLOV_H_MULT = 0 # use matrix multiplication for computing exp(Hm*t), used by default
    KRYLOV_H_EXP = 1  # use matrix exponential for computing exp(Hm*t)

    # choose host or device memory for executing Arnoldi algorithm using CUSP
    KRYLOV_CUSP_HOST = 0
    KRYLOV_CUSP_DEVICE = 1 
    
    # guard optimization mode
    GUARD_DECOMPOSED = 0
    GUARD_FULL_LP = 1

    def __init__(self, step):
        self.step = step
        self.sim_mode = SimulationSettings.EXP_MULT
        self.guard_mode = SimulationSettings.GUARD_DECOMPOSED
        self.krylov_compute_exp_Ht = SimulationSettings.KRYLOV_H_MULT
        self.krylov_numIter = None   # user-set number of iteration for Arnoldi algorithm
        self.krylov_cusp_memory = None # user set the memory for executing Arnoldi algorithm

        self.check_answer = False # double-check the expm answer at each step (slow!)

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
        self.plot_mode = PlotSettings.PLOT_FULL

        self.xdim_dir = 0 # plotting x dimension direction
        self.ydim_dir = 1 # plotting y dimension direction

        self.plot_size = (12, 8) # inches
        self.label = LabelSettings() # plot title, axis labels, font sizes, ect.

        self.num_angles = 512 # how many evenly-spaced angles to put into plot_vecs

        self.extra_lines = None # extra lines to draw on the plot. list of lists of x,y pairs
        self.min_frame_time = 0.025 # max 40 fps. This allows multiple frames to be drawn at once if they're fast.

        self.extend_plot_range_ratio = 0.1 # extend plot axis range 10% at a time
        self.anim_delay_interval = 0 # milliseconds, extra delay between frames

        self.filename = None # used with PLOT_VIDEO AND PLOT_IMAGE

        self.video = None # instance of VideoSettings

        self.grid = True
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
        self.time = None

        self.freeze_attrs()
