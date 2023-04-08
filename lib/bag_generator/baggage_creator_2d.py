#!/usr/bin/env python

# -----------------------------------------------------------------------------
"""
baggage_creator_2d.py: Module for generating 2D baggage simulations using
                       shape grammar.
"""
# -----------------------------------------------------------------------------

__author__    = "Ankit Manerikar"
__copyright__ = "Copyright (C) 2023, Robot Vision Lab"
__date__      = "6th April, 2023"
__credits__   = ["Ankit Manerikar", "Fangda Li"]
__license__   = "Public Domain"
__version__   = "2.0.0"
__maintainer__= ["Ankit Manerikar", "Fangda Li"]
__email__     = ["amanerik@purdue.edu", "li1208@purdue.edu"]
__status__    = "Prototype"

# -----------------------------------------------------------------------------

from copy import deepcopy as ccfunc

from lib.forward_model.mu_database_handler import *

from lib.bag_generator.shape_list_handle import *
from skimage.morphology import *
from skimage.draw import *
from skimage.measure import label
import skimage.transform as sktr
from numpy import *
import random as rdm
from tabulate import tabulate

import scipy.ndimage as sptx
from tqdm import tqdm

import warnings
warnings.filterwarnings('ignore')

"""
-------------------------------------------------------------------------------
Module Description:
-------------------
This is the 2D equivalent of the 3D Virtual baggage creator in 
baggage_creator_3d.py. The placement logic and objects created in this mode are
the same as its 3D counterpart. The baggage creator a set of independent 2D 
slices of the virtual bags - the number of slices is equal to specified 
z-width. The type of objects spawned for each slice are the same but are 
shuffled and moved around for each slice to create a new configuration for 
every slice. 

** ----------------------------------------------------------------------------
This eliminates any sample overlap in simulated data when using the data for
training 2D datasets.
-----------------------------------------------------------------------------**

-------------------------------------------------------------------------------
"""

# =============================================================================


class Object2D(object):
    """
    ---------------------------------------------------------------------------
    Class Description:
    Class for generating 2D objects to be spawned in the virtual bag.
    The class reads in a dictionary of object parameters
    (see shape_list_handle.py ) and the initial 3D pose of the object
    (specifically, for the object's bounding box).

    Once initialized, the class creates a binary 3D image as per the object
    shape, dimensions and orientation which is then used by the virtual bag
    generator to place the object within the bag. Remember that when being
    placed in a bag, the initial pose changes as per the placement of the
    object. The Object2D can be used to spawn:

    1) Ellipse
    2) Trapeze
    4) Rectangles
    5) Deformable Sheets
    6) Custom Rigid Objects
    7) Liquid-filled Containers

    The main purpose of this class is to be able to manipulate the objects
    while using the module BaggageImage2D().

    Method:

    __init__                        - Constructor
    apply_liquid_container_rule     - filled the object with liquid upto
                                      specified level
    create_ellipse                  - create a 2D ellipse object
    create_rect                     - create a 2D rectangle object
    create_trapezoid                - create a 2D trapezoid object
    create_sheet                    - create a 3D deformable sheet object
    create_custom_object            - create a 3D custom shape object specified
                                      by a binary mask or an external file

    Attributes:

    obj_dict                        - SL dictionary for the object
    data                            - 2D binary image mask for the object
    shape                           - type of primitive shape
                                      {'E', 'C', 'Y', 'B', 'S', 'M'}

    axes                            - dimensions of the principal axes
    dim                             - dimension of the bounding box
    theta                           - orientation of the object
    pose                            - image location of the object centroid
    curve_pts                       - (for sheet object), location of the
                                      mesh points in the sheet

    label                           - object label
    lqd_flag                        - set to True if it contains liquids
    lqd_label                       - label for liquid
                                      (= None if lqd_flag=False)
    lqd_level                       - level to which liquid is filled
                                      (= None if lqd_flag=False)
    lqd_material                    - material for the liquid
                                      (= None if lqd_flag=False)
    cntr_thickness                  - container thickness
                                      (= None if lqd_flag=False)
    ---------------------------------------------------------------------------
    """

    def __init__(self,
                 obj_dict,
                 obj_pose
                 ):
        """
        -----------------------------------------------------------------------
        Constructor for the 2D Object function. Once initialized, the SL
        dictionary fed in as the argument is converted into Object2D instance

        :param obj_dict:        SL dictionary defining the object's shape,
                                dimension and orientation - see
                                ShapeListHandle for details
        :param obj_pose:        initial pose of the object in the bag.
        -----------------------------------------------------------------------
        """

        self.shape    = obj_dict['shape']
        self.label    = obj_dict['label']
        self.obj_dict = obj_dict.copy()

        # For Ellipsoid -------------------------------------------------------
        if self.shape == 'E':
            self.pose = obj_pose
            self.axes  = tuple(obj_dict['geom']['axes'])
            self.theta = tuple(obj_dict['geom']['rot'])
            self.create_ellipse()

        # For Cuboid ----------------------------------------------------------
        if self.shape == 'B':
            self.pose = obj_pose
            self.dim = obj_dict['geom']['dim'].astype(int)
            self.theta = tuple(obj_dict['geom']['rot'])
            self.create_rectanguloid()

        # For Cone ------------------------------------------------------------
        if self.shape in ['C', 'Y']:
            self.pose = obj_pose
            center1 = tuple(obj_dict['geom']['base'])
            center2 = tuple(obj_dict['geom']['apex'])
            if self.shape=='C':
                radius1, radius2 = int(obj_dict['geom']['radius1']), \
                                   int(obj_dict['geom']['radius2'])
            elif self.shape=='Y':
                radius1, radius2 = int(obj_dict['geom']['radius']), \
                                   int(obj_dict['geom']['radius'])
            self.create_trapezoid(center1, center2, radius1, radius2)

        # For Sheet -----------------------------------------------------------
        if self.shape == 'S':
            self.pose = obj_pose
            self.dim = obj_dict['geom']['dim'].astype(int)
            self.theta = tuple(obj_dict['geom']['rot'])
            self.create_sheet()

        # For Custom ----------------------------------------------------------
        if self.shape == 'M':
            self.pose = obj_pose
            self.dim = obj_dict['geom']['dim']
            self.theta = tuple(obj_dict['geom']['rot'])
            self.scale = obj_dict['geom']['scale']
            self.data = obj_dict['geom']['mask']
            self.src = obj_dict['geom']['src']
            self.create_custom_object()

        # ---------------------------------------------------------------------

        self.lqd_flag = obj_dict['lqd_flag']

        if self.lqd_flag:
            self.cntr_thickness = obj_dict['lqd_param']['cntr_thickness']
            self.lqd_level      = obj_dict['lqd_param']['lqd_level']
            self.lqd_label      = obj_dict['lqd_param']['lqd_label']
            self.lqd_material   = obj_dict['lqd_param']['lqd_material']

        self.data = self.label*self.data
        self.init_pose = obj_pose
    # -------------------------------------------------------------------------

    def apply_liquid_container_rule(self):
        """
        -----------------------------------------------------------------------
        Function to implement the liquid container rule for the shape grammar
        to spawn a liquid-filled container object in the baggage image.

        :return:
        -----------------------------------------------------------------------
        """
        try:
            bin_data = self.data.copy()//self.label
            erode_elem = disk(self.cntr_thickness)
            eroded_img = binary_erosion(bin_data, selem=erode_elem)
            e_row, temp1 = np.where(eroded_img)
            e_fill = int((1 - self.lqd_level) * (e_row.max() - e_row.min()))
            e_fill_img = eroded_img.copy()
            e_fill_img[:e_fill, :] = 0

            self.data[np.where(eroded_img)] = -1
            self.data[np.where(e_fill_img)] = self.lqd_label
        except:
            pass
    # -------------------------------------------------------------------------

    def create_ellipse(self):
        """
        ------------------------------------------------------------------------
        Generate a 2D ellipse.

        :return bin_image: 2D binary image output
        ------------------------------------------------------------------------
        """

        axes  = array(self.axes).astype(int)
        theta = self.theta

        e_r, e_c =  ellipse(max(axes[0], axes[1])+1,
                            max(axes[0], axes[1])+1,
                            axes[0], axes[1],
                            rotation=theta[0],
                            shape=(2*max(axes[0], axes[1])+1,
                                   2*max(axes[0], axes[1])+1))

        # max_axes = max(e_pix.shape)
        mask = zeros((2*max(axes[0], axes[1])+1,
                      2*max(axes[0], axes[1])+1)
                     )
        mask[e_r, e_c] = 1

        ellip_coord = np.where(mask)
        ellip_dim   = ellip_coord[0].max()-ellip_coord[0].min()+1, \
                      ellip_coord[1].max()-ellip_coord[1].min()+1

        bin_image = mask[ellip_coord[0].min():
                         ellip_coord[0].min()+ellip_dim[0]+1,
                         ellip_coord[1].min():
                         ellip_coord[1].min()+ellip_dim[1]+1]

        self.data = bin_image.astype(bool)
        self.dim = array(bin_image.shape)
    # -------------------------------------------------------------------------

    def create_rectanguloid(self):
        """
        -----------------------------------------------------------------------
        Generate a 2D rectanguloid.

        :return bin_image: 3D binary image output
        -----------------------------------------------------------------------
        """

        dim = self.dim
        theta = self.theta

        max_dim = sqrt(dim[0]**2+dim[1]**2)
        max_dim = 2*int(max_dim//2) + 1
        mask = zeros((max_dim, max_dim))
        start_pt = (max_dim-1)//2 - dim[0]//2+1, \
                   (max_dim-1)//2 - dim[1]//2+1

        mask[start_pt[0]:start_pt[0] + dim[0]+1,
             start_pt[1]:start_pt[1] + dim[1]+1] = 1

        mask = sptx.rotate(mask, theta[0], axes=(1,0), order=0)

        box_coord = np.where(mask)
        box_dim   = box_coord[0].max()-box_coord[0].min()+1, \
                    box_coord[1].max()-box_coord[1].min()+1

        bin_image = mask[box_coord[0].min():
                         box_coord[0].min()+box_dim[0]+1,
                         box_coord[1].min():
                         box_coord[1].min()+box_dim[1]+1]

        self.data = bin_image.astype(bool)
        self.dim = array(bin_image.shape)
    # --------------------------------------------------------------------------

    def create_trapezoid(self, center1, center2, radius1, radius2):
        """
        ------------------------------------------------------------------------
        Generate a 2D trapezoid.

        :param center1:  center of first disc
        :param center2:  center of last disc
        :param radius1:   radius of 1st disc
        :param radius2:   radius of last disc
        :return: bin_image: 3D binary image output
        ------------------------------------------------------------------------
        """

        max_dim = max(radius1, radius2)
        min_dim = min(radius1, radius2)

        polygon_coord_r = [
            max_dim - min_dim,
            max_dim + min_dim,
            max_dim*2+1,
            0
        ]

        polygon_coord_c = [
            0, 0,
            max_dim*2+1, max_dim*2+1
        ]

        p_r, p_c = polygon(polygon_coord_r,
                           polygon_coord_c,
                           shape=(max_dim*2+1, max_dim*2+1))

        mask = zeros((max_dim*2+1, max_dim*2+1))
        mask[p_r, p_c] = 1

        rho = np.arctan((center2[1] - center1[1]) / (center2[0] - center1[0]))

        mask = sptx.rotate(mask, np.deg2rad(rho), axes=(1, 0), order=0)

        box_coord = np.where(mask==1)
        box_dim   = box_coord[0].max()-box_coord[0].min()+1, \
                    box_coord[1].max()-box_coord[1].min()+1

        bin_image = mask[box_coord[0].min():
                         box_coord[0].min()+box_dim[0]+1,
                         box_coord[1].min():
                         box_coord[1].min()+box_dim[1]+1]

        self.obj_dict['geom']['base'] = array([center1])
        self.obj_dict['geom']['apex'] = array([center2])

        self.data = bin_image.astype(bool)
        self.dim = array(bin_image.shape)
    # --------------------------------------------------------------------------

    def create_sheet(self):
        """
        ------------------------------------------------------------------------
        Generate a 2D Sheet Object.

        :return: bin_image: 2D binary image output
        ------------------------------------------------------------------------
        """

        # dimension of the sheet
        dim = self.dim
        # orientation of the sheet
        theta = self.theta

        # initialize empty volume with maximum dimension
        max_dim = int(dim[1]) + 10
        mask = zeros((max_dim, max_dim))

        # Assign starting point for defining the sheet
        start_pt = mask.shape[0]//2, 5

        mask[mask.shape[0]//2, 5:-5] = 1

        mask = sptx.rotate(mask, theta[0], axes=(1, 0), order=1, reshape=False)

        # Generate curve pts ---------------------------------------------------

        cpt_mask = zeros((max_dim, max_dim))
        cpt_mask[max_dim//2, 5:-5] = 1
        cpt_mask = sptx.rotate(cpt_mask, theta[0], axes=(1, 0), order=1,
                               reshape=False)
        pts_coords = np.where(cpt_mask>0)

        curve_pt = array([[pts_coords[0][0],
                             pts_coords[1][0]],
                            [pts_coords[0][-1],
                             pts_coords[1][-1]]
                            ])

        self.curve_pts = curve_pt.copy()

        # ---------------------------------------------------------------------

        r_min, r_max = self.curve_pts[:, 0].min(), self.curve_pts[:, 0].max()
        c_min, c_max = self.curve_pts[:, 1].min(), self.curve_pts[:, 1].max()

        self.curve_pts[:,0] -= r_min
        self.curve_pts[:,1] -= c_min

        # ---------------------------------------------------------------------

        bin_image = mask[r_min:r_max+1, c_min:c_max+1].copy()

        self.data = bin_image.astype(bool)
        self.dim  = array(bin_image.shape)
        self.axes = dim
    # -------------------------------------------------------------------------

    def create_custom_object(self):
        """
        -----------------------------------------------------------------------
        Create an Object from custom shape predefined through a binary mask.

        :return bin_image: 2D binary image output
        -----------------------------------------------------------------------
        """

        dims = self.data.shape

        theta = self.theta

        mask = self.data[:,:,dims[2]//2]

        if mask.max()<1:
            mask = zeros_like(self.data[:,:,dims[2]//2])

            r = 1

            while mask.max()<1 and sum(mask)<50:

                mask = self.data[:,:, r]
                if r == dims[2]:
                    mask = mask + 1
                r += 1

        scale = self.scale

        mask = sptx.rotate(mask, theta[0], axes=(1,0), order=0)
        mask = sktr.rescale(mask, scale, preserve_range=True)

        mask[mask>0] = 1
        mask[mask<0.5] = 0

        if mask.max()<1: mask = mask + 1

        box_coord = mask.nonzero()
        box_dim   = box_coord[0].max()-box_coord[0].min()+1, \
                    box_coord[1].max()-box_coord[1].min()+1

        bin_image = mask[box_coord[0].min():
                         box_coord[0].min()+box_dim[0]+1,
                         box_coord[1].min():
                         box_coord[1].min()+box_dim[1]+1]

        self.data = bin_image.astype(bool)
        self.dim = array(bin_image.shape)
    # -------------------------------------------------------------------------

# =============================================================================
# Class Ends
# =============================================================================


class BaggageImage2D(object):

    """
    ---------------------------------------------------------------------------
    Class Description:

    This class implements the placement logic for objects in the virtual bag.
    The placement of objects is done with the following rules:

    1) Liquid Container Rule
    2) Sheet Rule
    3) Gravity Rule
    4) Overlap Rule

    For details about each of these rules, check the Module Description.
    The rules above are implemented in the order of decreasing priority, hence
    the liquid-container / sheet rule are checked for last while overlap and
    gravity are checked for first. The baggage image with the placed objects is
    generated by running the function self.create_baggage_image() by feeding
    in a list of Object3D instance for the objects (not a shape list). To
    facilitate randomized generation of baggage images with similar objects
    and materials, the method self.create_random_object_list() can be used
    with option for the list of object materials, list of liquid materials,
    whether sheet or liquid object be spawned in the image and the limiting
    dimensions of the materials.

    Methods:

    __init__()                              - Constructor
    create_random_object_list()             - create a randomized list of
                                              Object3D instances
    create_baggage_image()                  - Create a 3D baggage from a list
                                              of Object3D instances

    _add_object()                           - place a single Object3D object in
                                              the image
    _get_overlap()                          - check for overlap with other
                                              objects
    _adjust_for_boundaries()                - adjust objects so that they are
                                              within the bag boundaries
    _run_shape_grammar_overlap()            - create baggage image without the
                                              gravity rule (the object will
                                              then float in the bag without
                                              settling down.)
    _run_shape_grammar_overlap_and_gravity()- create image with all the rules

    _run_midpoint_recursion()               - run the midpoint recursion
                                              algorithm to deform the spawn sheet
    _generate_sheet_curve()                 - generate sheet from its mesh points
    _get_2d_plane()                         - create 2D plane for sheet mesh
                                              points to check for overlap
    _inflate_sheet()                        - adjust sheet thickness to the
                                              specified value

    _place_object_in_bag()                  - draw the object in the final
                                              baggage image.

    Attributes:

    bag_dict                                - dictionary containing bag
                                              specifications
    bag_b_img                               - 2D cross section image for bag
    table_dict                              - dictionary containing table
                                              specifications
    table_img                               - 2D cross section image for table
    tray_dict                               - dictionary containing tray
                                              specifications
    tray_img                                - 2D cross section image for tray

    bb_label                                - bag label (=3)
    bb_size                                 - bounding box size of the bag (=165)
    bb_thickness                            - thickness of the bag (=3)
    boundary                                - img showing bag boundary only
    data                                    - 3D baggage image
    end_label                               - highest label values for solid
                                              object within the bag
    full_bag_vol                            - baggage image with tray and table
    lqd_count                               - highest label values for liquid
                                              object within the bag
    max_dim                                 - maximum possible dimension of an object
    min_dim                                 - minimum possible dimension of an object
    prior_image                             - prior image if any is fed to the class
    sim_dir                                 - simulation directory for saving data
    ---------------------------------------------------------------------------
    """

    def __init__(self,
                 img_vol=(664, 664, 350),
                 sim_dir=os.path.join(EXAMPLE_DIR, 'baggage_samples'),
                 logfile=None,
                 gantry_dia=None,
                 prior_image=None,
                 template=2,
                 debug=False):
        """
        -----------------------------------------------------------------------
        Constructor.

        :param bag_size:        - size of the volume within which the objects
                                  are to be spawned
        :param img_vol:         - image dimensions in the baage image is to be
                                  placed
        :param boundary:        - bounding bag specifications (width, thickness)
        :param sim_dir:         - simulation directory for saving data
        :param prior_image:     - prior image to be placed in the baggage
                                  image before spawning any objects.
        :return
        -----------------------------------------------------------------------
        """

        self.slh = ShapeListHandle()
        self.mu_handler = MuDatabaseHandler()

        os.makedirs(sim_dir, exist_ok=True)
        if gantry_dia is None:           gantry_dia = self.img_vol[0]

        self.sim_dir, self.img_vol, self.prior_image, self.bb_label = \
            sim_dir, img_vol, prior_image, 3

        self.debug = debug

        self.img_ctr, boundary, self.bg_sf_list, full_bag_img, \
        self.gantry_cavity, bag_b, bag_mask = self.slh.get_bag_background(
                                                    self.img_vol,
                                                    gantry_dia,
                                                    template=template
                                                    )

        self.bb_h, self.bb_t = boundary[0], boundary[1]
        self.size = max(2*self.bb_h+2*self.bb_t, self.img_vol[2])
        v_bag = np.zeros((self.size, self.size, self.size))

        # add boundary to image -----------------------------------------------

        # boundary params

        bag_bound = v_bag.copy()
        self.bag_mask = None

        # Create boundary in image - this is used to check for overlap
        if bag_b is None:
            bag_bound[self.size // 2 - self.bb_h - self.bb_t:
                      self.size // 2 + self.bb_h + self.bb_t,
            self.size // 2 - self.bb_h - self.bb_t:
            self.size // 2 + self.bb_h + self.bb_t,
            self.size // 2 - self.bb_h - self.bb_t:
            self.size // 2 + self.bb_h + self.bb_t] = 1

            bag_bound[self.size // 2 - self.bb_h: self.size // 2 + self.bb_h,
            self.size // 2 - self.bb_h: self.size // 2 + self.bb_h,
            self.size // 2 - self.bb_h: self.size // 2 + self.bb_h] = 0
        else:

            self.bag_mask = bag_mask.copy()
            nz = bag_mask.nonzero()
            self.bbox = nz[0].min(), nz[0].max(), nz[1].min(), nz[1].max()
            self.extents = self.bbox[1]-self.bbox[0], self.bbox[3]-self.bbox[2]

            bag_bound[self.size // 2 - self.bb_h - self.bb_t:
                      self.size // 2 + self.bb_h + self.bb_t,
                      self.size // 2 - self.bb_h - self.bb_t:
                      self.size // 2 + self.bb_h + self.bb_t,
                      self.size // 2 - self.bb_h - self.bb_t:
                      self.size // 2 + self.bb_h + self.bb_t] = \
            bag_b[self.img_ctr[0] - self.bb_h - self.bb_t:
                  self.img_ctr[0] + self.bb_h + self.bb_t,
                  self.img_ctr[1] - self.bb_h - self.bb_t:
                  self.img_ctr[1] + self.bb_h + self.bb_t][:,:, newaxis]*\
                ones((2*(self.bb_h+self.bb_t),
                      2*(self.bb_h+self.bb_t),
                      2*(self.bb_h+self.bb_t)))

        if prior_image is not None:
            nz = prior_image.nonzero()
            bag_bound[nz] = 1

        v_bag += self.bb_label * bag_bound
        self.boundary = bag_bound  # boundary of bag for checking overlap
        self.ws_bag = v_bag  # virtual bag wherein objects are placed

        # final bag as output - use this for further processing
        self.virtual_bag = full_bag_img[:, :, newaxis] * np.ones(self.img_vol)

        if logfile is None: logfile = os.path.join(sim_dir,
                                                   'virtual_bag_creator.log')
        self.logger = get_logger('BAG_CREATOR', logfile)

        self.logger.info("="*80)
        self.logger.info("3D Virtual Bag Creator")
        self.logger.info("-"*40+'\n')

        header = ["3D Baggage Image Creator", '']

        print_table = []
        print_table.append(['Initialization Time',
                            time.strftime('%m-%d-%Y %H:%M:%S', time.localtime())
                            ])
        print_table.append(['Image size', self.size])
        print_table.append(['Boundary Size', self.bb_h])
        print_table.append(['Boundary Thickness', self.bb_t])

        self.logger.info('\n'+tabulate(print_table, header, tablefmt='psql'))
        self.logger.info('\n')

        # self.logger.info("="*80
        # self.logger.info("3D Baggage Image Creator"
        # self.logger.info("-"*40,'\n'

        header = ["3D Baggage Image Creator", '']

        print_table = []
        print_table.append(['Initialization Time',
                            time.strftime('%m-%d-%Y %H:%M:%S', time.localtime())
                            ])
        print_table.append(['Image size', self.size])
        print_table.append(['Boundary Size', self.bb_h])
        print_table.append(['Boundary Thickness', self.bb_t])

        self.logger.info('\n'+tabulate(print_table, header, tablefmt='psql'))
        self.logger.info('\n')
    # -------------------------------------------------------------------------

    def create_random_object_list(self,
                                  material_list,
                                  liquid_list,
                                  material_pdf,
                                  liquid_pdf,
                                  lqd_prob=0.2,
                                  sheet_prob=0.2,
                                  dim_range=(5,150),
                                  number_of_objects=5,
                                  spawn_sheets=True,
                                  spawn_liquids=True,
                                  sheet_dim_list=range(2,7),
                                  custom_objects=None,
                                  custom_obj_prob=0.0,
                                  metal_dict={'metal_amt': None, 'metal_size': None},
                                  target_dict={'num_range': None, 'is_liquid': False}
                                  ):

        """
        -----------------------------------------------------------------------
        Function to generate a list of randomly shaped objects.

        :param material_list:       list of materials (see MuDatabaseHandle for
                                    options)
        :param liquid_list:         list of liquid materials
        :param material_pdf:        probability distribution for selection of
                                    materials
        :param liquid_pdf:          probability distribution for selection of
                                    liquids
        :param lqd_prob:            probalbilty of spawning liquid ocntianers
        :param lqd_prob:            probalbilty of spawning sheets
        :param min_dim:             min dimension for shape
        :param max_dim:             max dimension for shape
        :param number_of_objects:   no. of objects to create -
                                    either a fixed or list of numbers
        :param spawn_sheets:        set to True if sheet objects  are to be
                                    spawned
        :param spawn_liquids:       set to True if liquid objects are to be
                                    spawned
        :param sheet_dim_list:      allowed thicknesses for sheet objects
        :param custom_objects:      list of custom objects if any are to be
                                    added
        :param metal_dict:          dictionary with two keys:
                                    'metal_amt':    number of metal pixels
                                    'metal_size':   min and max dimensions for metals
        :param target_dict:         'num_range': min and max number of targets allowed.

        :return:                    list of 3D objects
        -----------------------------------------------------------------------
        """

        # record min and max dimensions
        self.min_dim, self.max_dim  = dim_range
        min_dim, max_dim = dim_range

        non_metal_list = [x for x in material_list
                          if x not in self.mu_handler.metals]

        target_list = [x for x in non_metal_list
                       if x in self.mu_handler.curr_targets_list]
        lqd_target_list = [x for x in liquid_list
                           if x in self.mu_handler.curr_targets_list]
        lqd_non_target_list = [x for x in liquid_list
                               if x not in self.mu_handler.curr_targets_list]

        non_target_list = [x for x in non_metal_list
                           if x not in self.mu_handler.curr_targets_list]
        non_target_list_m = [x for x in material_list
                             if x not in self.mu_handler.curr_targets_list]
        target_counter = 0

        # Calculate pose range
        obj_list = []
        diff_dim = max_dim-min_dim
        pose_range = (self.size // 2 - self.bb_h,
                      self.size // 2 + self.bb_h - min_dim*2)

        pose_diff = pose_range[1] - pose_range[0]
        self.pose_range = pose_range
        self.pose_diff = pose_diff

        number_of_objects = random.choice(number_of_objects) \
                            if not isscalar(number_of_objects) \
                            else number_of_objects

        custom_obj_prob = 0.0 if custom_objects is None else custom_obj_prob

        orig_metal_amt = metal_dict['metal_amt']

        # calculate starting and ending label and as well as starting
        # label for liquids
        self.start_label = self.bb_label + 1
        self.end_label = self.start_label + number_of_objects
        self.lqd_count = self.end_label

        # iterate for the number of objects specified
        for i in range(self.start_label, self.end_label):

            # select material for the object
            c_mat = np.random.choice(material_list, p=material_pdf)

            # if sheets are to be spawned, include the option in
            # selecting shape

            # =====================================================
            if c_mat in self.mu_handler.metals and \
                    (metal_dict['metal_size'] is not None):
                min_dim = metal_dict['metal_size'][0]
                max_dim = metal_dict['metal_size'][1]
                diff_dim = max_dim-min_dim

            else:
                min_dim = self.min_dim
                max_dim = self.max_dim
                diff_dim = max_dim-min_dim

            # =================================================================
            if spawn_sheets:
                cshape = np.random.choice(['E', 'B', 'Y','C', 'S', 'M'],
                                          p=[0.35*(1-sheet_prob-custom_obj_prob),
                                             0.25*(1-sheet_prob-custom_obj_prob),
                                             0.20*(1-sheet_prob-custom_obj_prob),
                                             0.20*(1-sheet_prob-custom_obj_prob),
                                             sheet_prob,
                                             custom_obj_prob])
            else:
                cshape = np.random.choice(['E', 'B', 'Y', 'C', 'M'],
                                          p=[0.25 * (1  - custom_obj_prob),
                                             0.25 * (1  - custom_obj_prob),
                                             0.25 * (1  - custom_obj_prob),
                                             0.25 * (1  - custom_obj_prob),
                                             custom_obj_prob]
                                          )
            # =================================================================

            # =================================================================
            # select geometric parameters for the object
            c_geom = dict()

            if cshape=='E':
                c_geom['center'] = array([0, 0, 0])
                c_geom['axes']   = np.random.rand(3)*diff_dim + min_dim
                c_geom['rot']    = np.random.rand(3)*90

            elif cshape=='B':
                c_geom['center'] = array([0, 0, 0])
                c_geom['dim']    = np.random.rand(3)*diff_dim + min_dim
                c_geom['rot']    = np.random.rand(3)*90

            elif cshape=='Y':
                c_geom['base']   = np.random.rand(3)*diff_dim + min_dim
                c_geom['apex']   = np.random.rand(3)*diff_dim + min_dim + max_dim
                c_geom['radius'] = np.random.rand()*diff_dim//2 + min_dim

            elif cshape=='C':
                c_geom['base']    = np.random.rand(3)*diff_dim + min_dim
                c_geom['apex']    = np.random.rand(3)*diff_dim + min_dim + min_dim
                c_geom['radius1'] = np.random.rand()*diff_dim//2 + min_dim
                c_geom['radius2'] = np.random.rand()*diff_dim//2 + min_dim

            elif cshape=='S':
                c_geom['center'] = array([0, 0, 0])
                c_geom['dim']    = np.random.rand(3)*max_dim*0.5 + max_dim
                c_geom['dim'][0] = np.random.choice(sheet_dim_list)
                c_geom['rot']    = np.random.rand(3)*90

            elif cshape=='M':
                c_geom['center'] = array([0, 0, 0])
                c_geom['dim']    = np.random.rand(3)*diff_dim + min_dim
                c_geom['rot']    = np.random.rand(3)*90
                c_geom['scale']  = np.random.rand()*1.0 + 0.5
                c_geom['src']    = np.random.choice(custom_objects)
                c_geom['mask']   = read_fits_data(c_geom['src'])
            # =================================================================

            # if liquids are to be spawned randomly choose an object to be liquid
            # filled container
            liquid_option = random.choice([True, False],
                                          p =[lqd_prob, 1 - lqd_prob]) \
                            and cshape!='S' and cshape!='M' \
                            and spawn_liquids

            # assign random pose at the top of the bag (as if falling into the bag)
            c_pose = array([
                int(pose_range[0] + max_dim),
                int(np.random.rand() * pose_diff + pose_range[0]),
                int(np.random.rand() * pose_diff + pose_range[0])
            ])

            # =================================================================
            # if liquid_option is True, select liquid parameters
            if liquid_option:

                lqd_param = dict(
                    lqd_level=random.random()*0.5+0.4,
                    lqd_material=random.choice(liquid_list, p=liquid_pdf),
                    cntr_thickness=random.choice(sheet_dim_list),
                    lqd_label=self.lqd_count
                )
                self.lqd_count += 1

                if lqd_param['lqd_material'] in lqd_target_list:
                    if target_dict['num_range'] is not None \
                        and target_counter==target_dict['num_range'][1]:
                        lqd_param['lqd_material'] = random.choice(lqd_non_target_list)
                    else:
                        target_counter += 1

                if c_mat in target_list:
                    c_mat = np.random.choice(non_target_list_m)

                # Create SL dictionary for the object with liquid
                obj_dict = self.slh.create_sim_object(
                    geom=c_geom,
                    shape=cshape,
                    obj_material=c_mat,
                    label=i,
                    lqd_flag=True,
                    lqd_param=lqd_param
                )
            else:

                # Create SL dictionary for the object without liquid
                obj_dict = self.slh.create_sim_object(
                    geom=c_geom,
                    shape=cshape,
                    obj_material=c_mat,
                    label=i,
                )
            # =================================================================

            # =================================================================
            # Create an Object3D instance for the current SL dictionary
            curr_obj = Object2D(
                obj_dict=obj_dict,
                obj_pose=c_pose
            )
            # =================================================================

            # =================================================================
            def change_object_material(material_type='nonmetal',
                                       contains_liquid=False):
                """
                ---------------------------------------------------------------
                Change the object material for the SL dictionary and Object3D
                instance. (the material is always non-metallic)

                :param is_target: spawn a target object
                :return:
                ---------------------------------------------------------------
                """

                # self.logger.info("Changing object material to >> ",

                metal_free_list = [x for x in material_list
                                   if x not in self.mu_handler.metals]

                if material_type=='nonmetal':
                    curr_mat = np.random.choice(non_target_list)
                elif material_type=='target' and not contains_liquid:
                    curr_mat = np.random.choice(target_list)
                elif material_type=='nontarget':
                    curr_mat = np.random.choice(non_target_list)
                else:
                    curr_mat = np.random.choice(non_target_list)

                # self.logger.info( curr_mat, ">> ",

                if contains_liquid:

                    if target_dict['is_liquid']:
                        lqd_material = random.choice(lqd_target_list)
                    else:
                        lqd_material = random.choice(lqd_non_target_list)

                    lqd_param = dict(
                        lqd_level=random.random() * 0.5 + 0.4,
                        lqd_material=lqd_material,
                        cntr_thickness=random.choice(sheet_dim_list),
                        lqd_label=self.lqd_count
                    )
                    self.lqd_count += 1

                    if curr_mat in target_list:
                        curr_mat = np.random.choice(non_target_list_m)

                    # Create SL dictionary for the object with liquid
                    obj_dict = self.slh.create_sim_object(
                        geom=c_geom,
                        shape=cshape,
                        obj_material=curr_mat,
                        label=i,
                        lqd_flag=True,
                        lqd_param=lqd_param
                    )
                else:
                    obj_dict = self.slh.create_sim_object(
                        geom=c_geom,
                        shape=cshape,
                        obj_material=curr_mat,
                        label=i,
                    )

                # Create an Object3D instance for the current SL dictionary
                curr_obj = Object2D(
                    obj_dict=obj_dict,
                    obj_pose=c_pose
                )

                return obj_dict, curr_obj
            # =================================================================

            # =================================================================
            # Adjusting for too many targets
            if target_dict['num_range'] is not None and \
                    target_counter==target_dict['num_range'][1] \
                          and c_mat in target_list:
                obj_dict, curr_obj = change_object_material('nontarget',
                                                    target_dict['is_liquid'])
            # =================================================================

            # =================================================================
            # Adjusting for Metal Objects

            if orig_metal_amt is not None and c_mat in self.mu_handler.metals:

                obj_amt = count_nonzero(curr_obj.data)
                adj_scale = 0.8
                bin_data = (curr_obj.data>0)

                if orig_metal_amt<=2.25e2:
                    self.logger.info("Metal Voxels Exhausted. "
                                     "Changed material")
                    obj_dict, curr_obj = change_object_material()

                elif orig_metal_amt >= obj_amt:
                    orig_metal_amt -= obj_amt
                    self.logger.info("Metal Pixels Not Exhausted >> "
                                     "Remaining Metal Amt: %i"%orig_metal_amt)

                else:
                    if curr_obj.obj_dict['lqd_flag']:
                        obj_dict, curr_obj = change_object_material()

                    else:
                        cnt = 0
                        while  orig_metal_amt < obj_amt and cnt < 5:
                            bin_data = sktr.rescale(bin_data>0, adj_scale)
                            obj_amt  = count_nonzero(bin_data)
                            cnt +=1

                        if 2.25e2 > obj_amt:
                            obj_dict, curr_obj = change_object_material()

                        else:
                            orig_metal_amt -= obj_amt
                            self.logger.info(f"Remaining Metal Amt %i"%orig_metal_amt)

                            bounds = np.where(bin_data>0)

                            bin_data = bin_data[
                                bounds[0].max()-bounds[0].min(),
                                bounds[1].max()-bounds[1].min()
                            ]

                            bin_data = curr_obj.label*bin_data
                            curr_obj.label = bin_data

                obj_list.append(curr_obj)
            # =================================================================

            # =================================================================
            # Default action
            # Append to the object list

            else:
                obj_list.append(curr_obj)
            # =================================================================

            if curr_obj.obj_dict['material'] in target_list:
                target_counter += 1
        # =====================================================================
        # Adjusting for less than minimum number of targets

        # =================================================================
        def change_object_material(material_type='nonmetal',
                                   contains_liquid=False):
            """
            ---------------------------------------------------------------
            Change the object material for the SL odictionary and Object3D
            instance. (the material is always non-metallic)

            :param is_target: spawn a target object
            :return:
            ---------------------------------------------------------------
            """

            metal_free_list = [x for x in material_list
                               if x not in self.mu_handler.metals]

            if material_type=='nonmetal':
                curr_mat = np.random.choice(non_target_list)
            elif material_type=='target' and not contains_liquid:
                curr_mat = np.random.choice(target_list)
            elif material_type=='nontarget':
                curr_mat = np.random.choice(non_target_list)
            else:
                curr_mat = np.random.choice(non_target_list)

            if contains_liquid:

                if target_dict['is_liquid']:
                    lqd_material = random.choice(lqd_target_list)
                else:
                    lqd_material = random.choice(lqd_non_target_list)

                lqd_param = dict(
                    lqd_level=random.random() * 0.5 + 0.4,
                    lqd_material=lqd_material,
                    cntr_thickness=random.choice(sheet_dim_list),
                    lqd_label=self.lqd_count
                )
                self.lqd_count += 1

                if curr_mat in target_list:
                    curr_mat = np.random.choice(non_target_list_m)

                # Create SL dictionary for the object with liquid
                obj_dict = self.slh.create_sim_object(
                    geom=c_geom,
                    shape=cshape,
                    obj_material=curr_mat,
                    label=i,
                    lqd_flag=True,
                    lqd_param=lqd_param
                )
            else:
                obj_dict = self.slh.create_sim_object(
                    geom=c_geom,
                    shape=cshape,
                    obj_material=curr_mat,
                    label=i,
                )

            # Create an Object3D instance for the current SL dictionary
            curr_obj = Object2D(
                obj_dict=obj_dict,
                obj_pose=c_pose
            )

            # self.logger.info("New Object3D() created"
            return obj_dict, curr_obj
        # =================================================================

        if target_dict['num_range'] is not None \
            and target_counter<target_dict['num_range'][0]:

            while target_counter<target_dict['num_range'][0]:

                if spawn_sheets:
                    cshape = np.random.choice(['E', 'B', 'Y','C', 'S', 'M'],
                                              p=[0.25*(1-sheet_prob-custom_obj_prob),
                                                 0.25*(1-sheet_prob-custom_obj_prob),
                                                 0.25*(1-sheet_prob-custom_obj_prob),
                                                 0.25*(1-sheet_prob-custom_obj_prob),
                                                 sheet_prob,
                                                 custom_obj_prob])
                else:
                    cshape = np.random.choice(['E', 'B', 'Y', 'C', 'M'],
                                              p=[0.25 * (1  - custom_obj_prob),
                                                 0.25 * (1  - custom_obj_prob),
                                                 0.25 * (1  - custom_obj_prob),
                                                 0.25 * (1  - custom_obj_prob),
                                                 custom_obj_prob]
                                              )

                # select geometric parameters for the object
                c_geom = dict()

                if cshape=='E':
                    c_geom['center'] = array([0, 0, 0])
                    c_geom['axes']   = np.random.rand(3)*diff_dim + min_dim
                    c_geom['rot']    = np.random.rand(3)*90

                elif cshape=='B':
                    c_geom['center'] = array([0, 0, 0])
                    c_geom['dim']    = np.random.rand(3)*diff_dim + min_dim
                    c_geom['rot']    = np.random.rand(3)*90

                elif cshape=='Y':
                    c_geom['base']   = np.random.rand(3)*diff_dim + min_dim
                    c_geom['apex']   = np.random.rand(3)*diff_dim + min_dim + max_dim
                    c_geom['radius'] = np.random.rand()*diff_dim//2 + min_dim

                elif cshape=='C':
                    c_geom['base']    = np.random.rand(3)*diff_dim + min_dim
                    c_geom['apex']    = np.random.rand(3)*diff_dim + min_dim + min_dim
                    c_geom['radius1'] = np.random.rand()*diff_dim//2 + min_dim
                    c_geom['radius2'] = np.random.rand()*diff_dim//2 + min_dim

                elif cshape=='S':
                    c_geom['center'] = array([0, 0, 0])
                    c_geom['dim']    = np.random.rand(3)*max_dim*0.5 + max_dim
                    c_geom['dim'][0] = np.random.choice(sheet_dim_list)
                    c_geom['rot']    = np.random.rand(3)*90

                elif cshape=='M':
                    c_geom['center'] = array([0, 0, 0])
                    c_geom['dim']    = np.random.rand(3)*diff_dim + min_dim
                    c_geom['rot']    = np.random.rand(3)*90
                    c_geom['scale']  = np.random.rand()*1.0 + 0.5
                    c_geom['src']    = np.random.choice(custom_objects)
                    c_geom['mask']   = read_fits_data(c_geom['src'])

                obj_dict, curr_obj = change_object_material(
                                        'target',
                                         target_dict['is_liquid']
                                    )
                obj_list.append(curr_obj)

                target_counter += 1
                self.logger.info("Number of targets: %i"%target_counter)
        # =====================================================================

        rdm.shuffle(obj_list)

        return obj_list
    # -------------------------------------------------------------------------

    def create_baggage_image(self,
                             obj_list,
                             with_shape_grammar=True,
                             save_data=True):
        """
        -----------------------------------------------------------------------
        Create a 3D Baggage image using shape grammar and from the input list
        of 3D objects.

        :param obj_list:            list of 3D objects
        :param with_shape_grammar:  set to True to include shape grammar
        :param save_data:           set to true if the baggage data or shape
                                    file are to be saved
        :return:
        -----------------------------------------------------------------------
        """

        self.logger.info("\nCreating Baggage from Object List ...")
        self.logger.info("="*80)

        self.slice_no = 0

        slice_iter = tqdm(range(self.virtual_bag.shape[2]))

        for slice_no in slice_iter:
            current_obj_list = [ccfunc(x) for x in obj_list]

            for x in current_obj_list:
                x.pose = array([
                int(self.pose_range[0] + self.max_dim),
                int(np.random.rand() * self.pose_diff + self.pose_range[0]),
                int(np.random.rand() * self.pose_diff + self.pose_range[0])
            ])

            rdm.shuffle(current_obj_list)

            slice_iter.set_description("Slice: %i"%(slice_no+1))

            for k, bag_obj in enumerate(current_obj_list):

                self.slice_no = slice_no
                t0 = time.time()

                if with_shape_grammar:
                    self.add_object(bag_obj,
                                    with_overlap_rule=False,
                                    with_gravity_rule=True)
                else:
                    self.add_object(bag_obj,
                                    with_overlap_rule=False,
                                    with_gravity_rule=False)

            for k, bag_obj in enumerate(current_obj_list):
                if bag_obj.lqd_flag:
                    bag_obj.apply_liquid_container_rule()
                    self.place_object_in_bag(bag_obj)

        self.logger.info("=" * 40)

        if self.prior_image is not None:
            nz = self.prior_image.nonzero()
            self.ws_bag[nz] =self.prior_image[nz]

        self.ws_bag[self.ws_bag<0] = 0

        if self.bag_mask is None:
            self.virtual_bag[
            self.img_ctr[0]-self.bb_h:self.img_ctr[0]+self.bb_h,
            self.img_ctr[1]-self.bb_h:self.img_ctr[1]+self.bb_h,
            self.img_ctr[2]-self.bb_h:self.img_ctr[2]+self.bb_h
            ] = self.ws_bag[
            self.size//2-self.bb_h:self.size//2+self.bb_h,
            self.size//2-self.bb_h:self.size//2+self.bb_h,
            self.size//2-self.bb_h:self.size//2+self.bb_h
            ]
        else:
            shifted_img = zeros_like(self.virtual_bag)
            shifted_img[
                self.img_ctr[0]-self.bb_h:self.img_ctr[0]+self.bb_h,
                self.img_ctr[1]-self.bb_h:self.img_ctr[1]+self.bb_h,
                self.img_ctr[2]-self.bb_h:self.img_ctr[2]+self.bb_h
                ] = self.ws_bag[
                self.size//2-self.bb_h:self.size//2+self.bb_h,
                self.size//2-self.bb_h:self.size//2+self.bb_h,
                self.size//2-self.bb_h:self.size//2+self.bb_h
                ]
            shifted_img = shifted_img*self.bag_mask[:,:,newaxis]

            self.virtual_bag[self.bag_mask.nonzero()] = \
                shifted_img[self.bag_mask.nonzero()]

        self.virtual_bag = self.virtual_bag*self.gantry_cavity[:,:,newaxis]

        param_file = self.bg_sf_list

        for bag_obj in obj_list:

            if bag_obj.shape in ['E', 'B', 'S', 'M']:

                curr_obj = bag_obj.obj_dict.copy()
                curr_obj['geom']['center'] = array([
                self.img_ctr[0]-self.size//2 + bag_obj.pose[0] + bag_obj.dim[0] // 2,
                self.img_ctr[1]-self.size//2 + bag_obj.pose[1] + bag_obj.dim[1] // 2
                ])

            elif bag_obj.shape in ['Y', 'C']:
                curr_obj = bag_obj.obj_dict.copy()
                curr_obj['geom']['base'] = array(list(self.img_ctr)) -self.size//2 \
                                           + bag_obj.pose + curr_obj['geom']['base']
                curr_obj['geom']['apex'] = array(list(self.img_ctr)) -self.size//2 \
                                           + bag_obj.pose + curr_obj['geom']['apex']
            else:
                raise AttributeError("bag_obj - Shape not recognized!")

            param_file.append(curr_obj)

        self.param_file = param_file

        param_dict = dict()
        param_dict['obj_list'] = param_file

        if save_data:
            save_fits_data(os.path.join(self.sim_dir,
                                        'virtual_bag.fits.gz'),
                           self.virtual_bag)
            self.logger.info("3D Baggage Image saved in virtual_bag.fits.gz")

            with open(os.path.join(self.sim_dir, 'ml_metadata.pyc'), 'wb') as f:
                pickle.dump(param_dict, f)
                f.close()
            self.logger.info("Object Parameters saved in ml_metadata.pyc")
    # -------------------------------------------------------------------------

    def add_object(self,
                   bag_obj,
                   with_overlap_rule=True,
                   with_gravity_rule=True):
        """
        -------------------------------------------------------------------------
        Function to add the 3D object to the baggage image.

        :param bag_obj:             input 3D object
        :param with_overlap_rule:   set to true to include overlap rule
        :param with_gravity_rule:   set to true to include overlap+gravity rule
        :return:
        -------------------------------------------------------------------------
        """

        if with_gravity_rule:
            self.run_shape_grammar_overlap_and_gravity(bag_obj)
        elif with_overlap_rule:
            self.run_shape_grammar_overlap(bag_obj)
        else:
            self.ws_bag[bag_obj.pose[0]: bag_obj.pose[0] + bag_obj.dim[0]//2,
                      bag_obj.pose[1]: bag_obj.pose[1] + bag_obj.dim[1]//2,
                      self.slice_no] \
                = bag_obj.data
    # -------------------------------------------------------------------------

    def get_overlap(self, bag_obj):
        """
        -----------------------------------------------------------------------
        Function to determine between the 3D object and baggage image.

        :param bag_obj: input 3D object.
        :return: out_flag: set to True if there is overlap
                 obj_int:  3D binary mask showing overlap
        -----------------------------------------------------------------------
        """

        bag_data = self.ws_bag[:,:,self.slice_no].copy()
        bag_data[np.where(self.boundary[:,:,self.slice_no])]=0

        obj_loc = bag_data[
                  bag_obj.pose[0]: bag_obj.pose[0] + bag_obj.data.shape[0],
                  bag_obj.pose[1]: bag_obj.pose[1] + bag_obj.data.shape[1]]

        obj_int = bag_obj.data[:obj_loc.shape[0],
                               :obj_loc.shape[1]]*obj_loc.astype(bool)
        out_flag = np.any(obj_int.astype(bool))

        return out_flag, obj_int
    # -------------------------------------------------------------------------

    def _adjust_for_boundaries(self, bag_obj):
        """
        -----------------------------------------------------------------------
        Function to adjust object shape to fit within boundaries.

        :param bag_obj: input 3D object
        :return: bag_obj:      adjusted 3D object
        -----------------------------------------------------------------------
        """

        if self.bag_mask is None:
            lower_bound = self.size//2-self.bb_h, self.size//2-self.bb_h
            upper_bound = self.size//2+self.bb_h, self.size//2+self.bb_h
        else:
            lower_bound = self.size//2-self.extents[0]//2, self.size//2-self.extents[1]//2
            upper_bound = self.size//2+self.extents[0]//2, self.size//2+self.extents[1]//2

        # Adjust along x-axis -------------------------------------------------
        if bag_obj.pose[0] <= lower_bound[0]:
            pose_diff_0 = lower_bound[0] - bag_obj.pose[0]
            bag_obj.pose[0] = lower_bound[0]
            bag_obj.dim[0] -= pose_diff_0
            bag_obj.data = bag_obj.data[-bag_obj.dim[0]:, :]

        if bag_obj.pose[0]+bag_obj.dim[0] >= upper_bound[0]:
            pose_diff_0 = bag_obj.pose[0]+bag_obj.dim[0] - upper_bound[0]
            bag_obj.dim[0] -= pose_diff_0
            bag_obj.data = bag_obj.data[: bag_obj.dim[0], :]

        # Adjust along y-axis -------------------------------------------------
        if bag_obj.pose[1] <= lower_bound[1]:
            pose_diff_0 = lower_bound[1] - bag_obj.pose[1]
            bag_obj.pose[1] = lower_bound[1]
            bag_obj.dim[1] -= pose_diff_0
            bag_obj.data = bag_obj.data[:, -bag_obj.dim[1]:]

        if bag_obj.pose[1]+bag_obj.dim[1] >= upper_bound[1]:
            pose_diff_0 = bag_obj.pose[1]+bag_obj.dim[1] - upper_bound[1]
            bag_obj.dim[1] -= pose_diff_0
            bag_obj.data = bag_obj.data[:, : bag_obj.dim[1]]

        return bag_obj
    # -------------------------------------------------------------------------

    def run_shape_grammar_overlap(self,
                                  bag_obj,
                                  fix_obj=True,
                                  row_shift=True,
                                  col_shift=True,
                                  z_shift=False):
        """
        -----------------------------------------------------------------------
        Implement the overlap rule for shape grammar.

        :param bag_obj:   Input 3D object
        :param fix_obj:   Place object in bag after executing rule
        :param row_shift: Set to true to shift along rows (x-axis)
        :param col_shift: Set to true to shift along columns (y-axis)
        :param z_shift:   Set to true to shift along slices (z-axis)
        :return:
        -----------------------------------------------------------------------
        """

        # getting OVERLAP_FLAG
        OVERLAP_FLAG, obj_int = self.get_overlap(bag_obj)

        # if there is positive overlap ----------------------------------------

        if OVERLAP_FLAG:
            ol_ctr = 0
            pose_list = [bag_obj.pose]

            while OVERLAP_FLAG: # ---------------------------------------------

                # Getting bounding box values -----------------------

                # Adjusting for multiple segments
                obj_int_bin = obj_int.astype(bool)
                obj_int_bin = label(obj_int_bin)

                # Choose segment with max overlap
                pix_cnt = [obj_int_bin[obj_int_bin==x].sum()//x
                           for x in range(1,obj_int_bin.max()+1)]
                max_ind = np.argmax(pix_cnt)+1

                # Clear all other segments
                obj_int_bin[obj_int_bin!=max_ind] = 0
                obj_int_bin = obj_int_bin.astype(bool)

                # Get bounding box coordinates
                vrows, vcols = np.where(obj_int_bin)

                bbox_rows = vrows.min(), vrows.max()
                bbox_cols = vcols.min(), vcols.max()

                bbox_dim  = vrows.max()   - vrows.min(), \
                            vcols.max()   - vcols.min()

                max_o_dim = obj_int_bin.shape[0]-1, \
                            obj_int_bin.shape[1]-1

                if row_shift:
                    if bbox_rows[0]==0 and bbox_rows[1]==max_o_dim[0]:
                        pass
                    elif bbox_rows[1]==max_o_dim[0]:
                        bag_obj.pose[0] -= bbox_dim[0]+1
                    elif bbox_rows[0]==0:
                        bag_obj.pose[0] += bbox_dim[0]+1
                    else:
                        pass

                if col_shift:
                    if bbox_cols[0]==0 and bbox_cols[1]==max_o_dim[1]:
                        pass
                    elif bbox_cols[1]==max_o_dim[1]:
                        bag_obj.pose[1] -= bbox_dim[1]+1
                    elif bbox_cols[0]==0:
                        bag_obj.pose[1] += bbox_dim[1]+1
                    else:
                        pass

                ground_y = self.size // 2 + self.bb_h
                GROUND_FLAG = ((bag_obj.pose[0] + bag_obj.dim[0]) >= ground_y)
                if GROUND_FLAG: break

                pose_list.append(bag_obj.pose)

                if ol_ctr>=2:
                    prev_pose = pose_list[-2]
                    osc_cond  = (bag_obj.pose[0]==prev_pose[0]) and \
                                (bag_obj.pose[1]==prev_pose[1])

                    # self.logger.info("++LAT_OSC++",
                    if osc_cond:
                        bag_obj.pose[0] -= bbox_dim[0]+1
                        col_shift = False
                        row_shift = False
                        self.LATERAL_OSC_FLAG = True

                ol_ctr += 1
                OVERLAP_FLAG, obj_int = self.get_overlap(bag_obj)

                if ol_ctr==10: break

        if fix_obj: self.place_object_in_bag(bag_obj)
        else:       return bag_obj
    # -------------------------------------------------------------------------

    def run_midpoint_recursion(self, simplex_pts):
        """
        -----------------------------------------------------------------------
        Run algorithm to recursively shift midpoints till the sheet curve does
        not overlap other objects.

        :param simplex_pts:   initial point set
        :return: point set with added points after deformation
        -----------------------------------------------------------------------
        """
        simplex_pts = simplex_pts.astype(int)
        line_pts = line(simplex_pts[0, 0],
                        simplex_pts[0, 1],
                        simplex_pts[1, 0],
                        simplex_pts[1, 1])

        line_overlap = np.any(self.ws_bag[:,:, self.slice_no][line_pts])

        if line_overlap:
            # get midpoint
            mid_pt = np.average(simplex_pts, axis=0).astype(int)

            row_zeros_mid_pt = np.where(self.ws_bag[:, mid_pt[1],
                                        self.slice_no]==0)[0]
            row_ind = np.copy(row_zeros_mid_pt)

            row_zeros_mid_pt -= mid_pt[0]
            mid_pt = array([row_ind[argmin(abs(row_zeros_mid_pt))],
                            mid_pt[1]])

            check_mid_pt =    array_equal(mid_pt, simplex_pts[0, :]) \
                           or array_equal(mid_pt, simplex_pts[1, :])

            if check_mid_pt:
                # self.logger.info("Deformed >>",
                return simplex_pts

            pt_set_1 = vstack((simplex_pts[0, :], mid_pt))
            pt_set_2 = vstack((simplex_pts[1, :], mid_pt))

            pt_list_1 = self.run_midpoint_recursion(pt_set_1)
            pt_list_2 = self.run_midpoint_recursion(pt_set_2)

            data = dstack((pt_list_1, pt_list_2))

            return data

        else:
            return simplex_pts
    # -------------------------------------------------------------------------

    def generate_sheet_curve(self, bag_obj):
        """
        -----------------------------------------------------------------------
        Generate the sheet curve.

        :param bag_obj:     The input baggage object
        :return: generate the sheet mask from its mesh points
        -----------------------------------------------------------------------
        """
        curve_pts = bag_obj.curve_pts.copy()

        # get curve pt coordinates in baggage volume frame
        curve_pts[:, 0] = curve_pts[:, 0] + int(bag_obj.pose[0])
        curve_pts[:, 1] = curve_pts[:, 1] + int(bag_obj.pose[1])
        curve_pts = np.clip(curve_pts, 0, 2*self.bb_h-1)

        # adjust endpoints so that they don't overlap
        for c_pt_no in range(2):
            if self.ws_bag[:,:, self.slice_no][tuple(curve_pts[c_pt_no, :])]>0:
                free_pt_ind = np.where(self.ws_bag[:,
                                                 curve_pts[c_pt_no, 1],
                                                 self.slice_no]==0)[0]
                free_pt = free_pt_ind.copy()
                free_pt -= curve_pts[c_pt_no, 0]
                curve_pts[c_pt_no,:] = \
                    array([free_pt_ind[argmin(abs(free_pt))],
                           curve_pts[c_pt_no, 1]])

        mid_pt = np.average(curve_pts, axis=0)

        simplex_1 = vstack((curve_pts[0, :], mid_pt))
        simplex_2 = vstack((curve_pts[1, :], mid_pt))

        # run midpoint recusion algo so to obtain curve points
        fin_curve_pts_1 = self.run_midpoint_recursion(simplex_1)
        fin_curve_pts_2 = self.run_midpoint_recursion(simplex_2)

        fin_curve_pts = dstack((fin_curve_pts_1,
                                fin_curve_pts_2))

        # minimum and maximum values of the curve points
        cpt_row_min, \
        cpt_row_max = fin_curve_pts[:, 0].min(), fin_curve_pts[:, 0].max()
        cpt_col_min, \
        cpt_col_max = fin_curve_pts[:, 1].min(), fin_curve_pts[:, 1].max()

        # transform curve pts to object coordinates
        fin_curve_pts[:, 0] -= cpt_row_min
        fin_curve_pts[:, 1] -= cpt_col_min

        # Get new pose
        bag_obj.pose[0] = int(cpt_row_min)
        bag_obj.pose[1] = int(cpt_col_min)

        # draw the curve
        bin_data = zeros((int(cpt_row_max-cpt_row_min+1),
                          int(cpt_col_max-cpt_col_min+1)))

        fin_curve_pts = fin_curve_pts.astype(int)

        for k in range(fin_curve_pts.shape[2]):
            end_pts = fin_curve_pts[:,:,k]
            b_pts = line(end_pts[0, 0],
                         end_pts[0, 1],
                         end_pts[1, 0],
                         end_pts[1, 1])
            bin_data[b_pts] = 1

        bag_obj.data = bin_data
        return bag_obj
    # -------------------------------------------------------------------------

    def get_2d_plane(self, pt_triad):
        """
        -----------------------------------------------------------------------
        Calculate 3D plane for a simplex to check for overlap for sheet
        objects.

        :param pt_triad:    the tuple of points containing the simplex
        :return: set of points making up the triplane
        -----------------------------------------------------------------------
        """
        a = pt_triad[0, :]
        b = pt_triad[1, :]
        c = pt_triad[2, :]

        ab_vect = b-a
        ac_vect = c-a
        norm_vect = cross(ab_vect, ac_vect)

        a0, a1, a2 = norm_vect[0], norm_vect[1], norm_vect[2]
        a3 = -(a0*a[0] + a1*a[1] + a2*a[2])

        poly_grid = polygon(pt_triad[:,1], pt_triad[:,2])
        z_val = -(1/a0)*(a1*poly_grid[0] + a2*poly_grid[1] + a3)
        z_val = z_val.astype(int)
        triplane = z_val, poly_grid[0], poly_grid[1]

        return triplane
    # -------------------------------------------------------------------------

    def inflate_sheet(self, bag_obj):
        """
        -----------------------------------------------------------------------
        Adjust sheet thickness according to the specified value

        :param bag_obj: input sheet object
        :return:
        -----------------------------------------------------------------------
        """
        bag_obj.data =  binary_dilation(bag_obj.data.astype(bool),
                                               disk(bag_obj.axes[0]))
        OVERLAP_FLAG, overlap_vol = self.get_overlap(bag_obj)
        bag_obj.data[np.where(overlap_vol)] = 0

        bag_obj.data = bag_obj.data.astype(bool)*bag_obj.label

        return bag_obj
    # -------------------------------------------------------------------------

    def run_shape_grammar_overlap_and_gravity(self,
                                              bag_obj,
                                              z_inc=50):
        """
        -----------------------------------------------------------------------
        Create baggage grammar with all the four rules in place.

        :param bag_obj:     current input 2D object
        :param z_inc:       incremental value for downward translation
        :return:
        -----------------------------------------------------------------------
        """

        # ground value for x-coordinate
        if self.bag_mask is None:
            ground_y = self.size//2+self.bb_h
        else:
            ground_y = self.size//2+self.extents[0]//2

        self.MULTI_OBJ_COLLIDE = False      # flag checking
                                            # for multi. object collision

        ol_ctr   = 0
        drop_ctr = 0        # counter for number of downward translation of
                            # the object towards the bottom of the bag

        while drop_ctr < 50:
            # flag checking for oscillation due to overlap of current object
            # with two different objects
            osc_cond = False

            # flag checking for only lateral oscillations
            self.LATERAL_OSC_FLAG = False

            # Move object downward by a fixed increment gien by z_inc
            drop_ctr += 1
            prev_pose = bag_obj.pose.copy()
            bag_obj.pose[0] += z_inc

            # Different Action for sheet objects ==============================
            if bag_obj.shape=='S':

                # Check if curve pts have moved beyond ground level
                x_dist = bag_obj.pose[0]+bag_obj.curve_pts[:, 0]
                SHEET_GROUND_FLAG = np.any(x_dist>=ground_y)

                # check if any of the curve pts are overlapping
                try:
                    COLL_FLAG = self.ws_bag[:,:, self.slice_no][
                                    tuple(bag_obj.curve_pts[0, :])] > 0 \
                                or self.ws_bag[:,:, self.slice_no][
                                    tuple(bag_obj.curve_pts[1,:])]>0
                except:
                    pass

                if SHEET_GROUND_FLAG or COLL_FLAG:
                    ground_diff = max(x_dist-ground_y)
                    if ground_diff <= 0: ground_diff = 0

                    if x_dist[0]>ground_y:    bag_obj.curve_pts[0, 0] -= ground_diff
                    if x_dist[1]>ground_y:    bag_obj.curve_pts[1, 0] -= ground_diff

                    bag_obj = self.generate_sheet_curve(bag_obj)
                    bag_obj = self.inflate_sheet(bag_obj)
                    self.place_object_in_bag(bag_obj)
                    break
                else:
                    pass
                # Sheet Object Action ends ====================================

            else:
                GROUND_FLAG = ((bag_obj.pose[0]+bag_obj.dim[0])>=ground_y)
                OVERLAP_FLAG, temp = self.get_overlap(bag_obj)

                if GROUND_FLAG:
                    g_diff = bag_obj.pose[0] + bag_obj.dim[0] - ground_y
                    bag_obj.pose[0] -= g_diff
                    OVERLAP_FLAG, temp = self.get_overlap(bag_obj)

                    if OVERLAP_FLAG:
                        bag_obj = self.run_shape_grammar_overlap(bag_obj,
                                                                 row_shift=False,
                                                                 fix_obj=False)
                        self.place_object_in_bag(bag_obj) #TODO: remove

                    break

                if OVERLAP_FLAG:
                    self.LATERAL_OSC_FLAG = False
                    while OVERLAP_FLAG:
                        ol_ctr +=1
                        bag_obj = self.run_shape_grammar_overlap(bag_obj,
                                                                 fix_obj=False)
                        OVERLAP_FLAG, temp = self.get_overlap(bag_obj)

                        osc_cond = (bag_obj.pose[0]==prev_pose[0]) and \
                                   (bag_obj.pose[1]==prev_pose[1])
                        if ol_ctr>10:
                            ol_ctr = 0
                            OVERLAP_FLAG = False
                            break

                if osc_cond or self.LATERAL_OSC_FLAG:
                    break

        bag_obj = self._adjust_for_boundaries(bag_obj)
        self.place_object_in_bag(bag_obj)
    # -------------------------------------------------------------------------

    def place_object_in_bag(self, bag_obj):
        """
        -----------------------------------------------------------------------
        Function to add the 2D bag object to 2D baggae image with posiiton
        and orientation.

        :param bag_obj:     current input 3D object
        :return:
        -----------------------------------------------------------------------
        """
        bag_obj.pose = bag_obj.pose.astype(int)
        s_shape = self.ws_bag[bag_obj.pose[0]:
                            bag_obj.pose[0] + bag_obj.data.shape[0],
                            bag_obj.pose[1]:
                            bag_obj.pose[1] + bag_obj.data.shape[1],
                            self.slice_no].shape

        b_data = bag_obj.data[:s_shape[0], :s_shape[1]].copy()
        nz = np.where(b_data)
        self.ws_bag[bag_obj.pose[0]:
                  bag_obj.pose[0] + bag_obj.data.shape[0],
                  bag_obj.pose[1]:
                  bag_obj.pose[1] + bag_obj.data.shape[1],
                  self.slice_no][nz] = b_data[nz]
    # -------------------------------------------------------------------------

# =============================================================================
# Class Ends
# =============================================================================
