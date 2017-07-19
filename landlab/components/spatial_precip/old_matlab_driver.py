# %----------------------------------------------------------------------------
# %STOchastic Rainfall Model (STORM). A rainstorm generator in this case based on empirical data (Walnut Gulch, AZ)
#
# %Code name: WG_storms_v3_01  %this version allows for simulations that are much longer than the input series in order to compare the distributions of storm characteristics to the original.
# %It also includes the 'mean gauge approach' to determine when a simulation year stops. This involves summing storm totals at each gauge for each year until the mean for all gauges exceeds the
# %selected annual total precip value. It also allows for fuzzy selection of intensity at the storm center based on a fixed value of duration and
# %incorporates orographic effects, wherein there are separate intensity-duration curves derived for three intervals of basin elevation (1200-1350m, 1351-1500m, 1501-1650m)
# %Current version also includes interarrival times between storms, allowing for output to drive other model frameworks (rainfall-ruonff, water balance,LEMs)
# %This version will also include output at each grid location, rather than only at gauge locations.
# %Author: Michael Singer 2017
# %Date created: 2015-6
# %----------------------------------------------------------------------------

import numpy as np
import os
import inspect
from six.moves import range
from matplotlib.pyplot import figure
from scipy.stats import genextreme
from landlab import RasterModelGrid, CLOSED_BOUNDARY


class PrecipitationDistribution(Component):

    def __init__(self, grid, mode='simulation', number_of_simulations=1,
                 number_of_years=1, buffer_width=5000, ptot_scenario='ptotC',
                 storminess_scenario='stormsC', save_outputs=None):
        """
        It's on the user to ensure the grid is big enough to permit the buffer.
        save_outputs : if not None, str path to save
        """
        self._grid = grid
        self._gauge_dist_km = np.zeros_like(Easting, dtype='float')
        self._rain_int_gauge = np.zeros_like(Easting, dtype='float')
        self._temp_dataslots = np.zeros_like(Easting, dtype='float')
        self._numsims = number_of_simulations
        self._numyrs = number_of_years
        assert ptot_scenario in ('ptotC', 'ptot+', 'ptot-', 'ptotT+', 'ptotT-')
        self._ptot_scenario = ptot_scenario
        assert storminess_scenario in ('stormsC', 'storms+', 'storms-',
                                       'stormsT+', 'stormsT-')
        self._storms_scenario = storms_scenario
        assert mode in ('simulation', 'validation')
        self._mode = mode
        self._buffer_width = buffer_width
        self._savedir = save_outputs

        self._max_numstorms = 1000
        # This is for initializing matrices. Trailing zeros are deleted from
        # the matrix at the end of the code.

    def simple_run(self):
        # what's the dir of this component?
        thisdir = os.path.dirname(inspect.getfile(PrecipitationDistribution))
        # unnecessary as related to output file gen & documentation?
        # t0 = time()
        # t1 = [datestr(floor(now)) '_' datestr(rem(now,1))];
        # t2=regexprep(t1,'[^\w'']',''); %for naming output directories and files by current date/time
        # mkdir('C:\bliss\sacbay\papers\WG_Rainfall_Model\model_output\',t2)

        # Initialize variables for annual rainfall total (mm/h) storm center location (RG1-RG85), etc.

        # This scalar specifies the fractional change in intensity per year
        # when storm_trend is applied in STORMINESS_SCENARIO
        ptot_scaling_factor = 0.07
        # This scalar specifies the fractional change in intensity per year
        # when storm_trend is applied in STORMINESS_SCENARIO
        storminess_scaling_factor = 0.01
        # This scalar specifies the value of fractional step change in
        # intensity when storms+ or storms- are applied in STORMINESS_SCENARIO
        storm_stepchange = 0.25

        # add variable for number of simulations of simyears
        simyears = self._numyrs  # number of years to simulate
        numcurves = 11  # number of intensity-duration curves (see below for curve equations)

        storm_scaling = 1.  # No storm scaling, as problem appears to be fixed with smaller grid spacing.
        #%storm_scaling = 1.15  # This scales the storm center intensity upward, so the values at each gauge are realistic once the gradient is applied.

        # #### NOTE risk here that matlab & Python present mirrored GEV & EV dists
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Ptot_pdf % This is the pdf fitted to all available station precip data (normal dist). It will be sampled below.
        # #### This to be replaced by a Ptot_mu and Ptot_sigma
###### NOTE right now we ignore all poss scenarios, i.e., use the C cases
        Ptot_pdf_norm = {'sigma': 63.9894, 'mu': 207.489,
                         'trunc_interval': (1., 460.)}
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Duration_pdf % This is the pdf fitted to all available station duration data (GEV dist). It will be sampled below.
        # #### matlab's GEV is (shape_param, scale(sigma), pos(mu))
        Duration_pdf_GEV = {'shape': 0.570252, 'sigma': 35.7389, 'mu': 34.1409,
                            'trunc_interval': (1., 1040.)}
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Area_pdf % This is the pdf fitted to all available station area data (EV dist). It will be sampled below.
        # #### matlab's EV is (mu, sigma)
        Area_pdf_EV = {'shape': 0., 'sigma': 2.83876e+07, 'mu': 1.22419e+08,
                       'trunc_interval': (5.e+06, 3.e+08)}
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Int_arr_pdf % This is the pdf fitted to all available station area data (GEV dist). It will be sampled below.
        Int_arr_pdf_GEV = {'shape': 0.807971, 'sigma': 9.49574, 'mu': 10.6108,
                           'trunc_interval': (0., 120.)}
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Recess_pdf % This is the pdf of storm gradient recession coefficiencts from Morin et al, 2005 (normal dist). It will be sampled below.
        Recess_pdf_norm = ('sigma': 0.08, 'mu': 0.25,
                           'trunc_interval': (0.15, 0.67))

        opennodes = mg.status_at_node != CLOSED_BOUNDARY
        if self._mode == 'validation':
            Easting = np.loadtxt(os.path.join(thisdir, 'Easting.csv'))  # This is the Longitudinal data for each gauge.
            Northing = np.loadtxt(os.path.join(thisdir, 'Northing.csv'))  # This is the Latitudinal data for each gauge. It will be sampled below.
            gauges = np.loadtxt(os.path.join(thisdir, 'gauges.csv'))  # This is the list of gauge numbers. It will be sampled below.
            gauge_elev = np.loadtxt(os.path.join(thisdir, 'gauge_elev.csv'))
            numgauges = gauges.size
        else:
            X1 = self.grid.node_x
            Y1 = self.grid.node_y
            Xin = X1[opennodes]
            Yin = Y1[opennodes]
            Zz = self.grid.at_node['topographic__elevation'][opennodes]
            numgauges = length(Xin)  # number of rain gauges in the basin. NOTE: In this version this produces output on a grid, rather than at real gauge locations.

        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\X % This is the Longitudinal data for each grid point. It will be sampled below to determine storm center location.
        X = np.loadtxt(os.path.join(thisdir, 'X.csv'))
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Y % This is the Latitudinal data for each grid point. It will be sampled below to determine storm center location.
        Y = np.loadtxt(os.path.join(thisdir, 'Y.csv'))
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Storm_depth_data % This is the storm depth data for use in model evaluation.
        Storm_depth_data = np.loadtxt(os.path.join(thisdir,
                                                   'Storm_depth_data.csv'))
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Intensity_data % This is the intensity data for use in model evaluation.
        Intensity_data = np.loadtxt(os.path.join(thisdir,
                                                 'Intensity_data.csv'))
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Duration_data % This is the duration data for use in model evaluation.
        Duration_data = np.loadtxt(os.path.join(thisdir,
                                                'Duration_data.csv'))
        # These three are in mm and hr
        # # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Gauge_GR1 % This is the lowest elevation gauge grouping used for orography (1200-1350m).
        # # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Gauge_GR2 % This is the middle elevation gauge grouping used for orography (1351-1500m).
        # # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\Gauge_GR3 % This is the highest elevation gauge grouping used for orography (1501-1650m).
        # Gauge_GR1 = np.loadtxt(os.path.join(thisdir, 'Gauge_GR1.csv'))
        # Gauge_GR2 = np.loadtxt(os.path.join(thisdir, 'Gauge_GR2.csv'))
        # Gauge_GR3 = np.loadtxt(os.path.join(thisdir, 'Gauge_GR3.csv'))
        # load C:\bliss\sacbay\papers\WG_Rainfall_Model\model_input\fuzz % This is a vector of fuzzy tolerace values for intensity selection.
        fuzz = np.loadtxt(os.path.join(thisdir, 'fuzz.csv'))
        fuzz = fuzz.astype(float)
        ET_monthly_day = np.loadtxt(os.path.join(thisdir,
                                                 'ET_monthly_day.txt'))
        ET_monthly_night = np.loadtxt(os.path.join(thisdir,
                                                   'ET_monthly_night.txt'))
        # This are matrices of averaged day/nighttime values of ET grouped as
        # one column per month.

        # now build a buffered target area of nodes:
        target_area_nodes = self.grid.zeros('node', dtype=bool)
        # which are within buffer_width of the perimeter? Try to do this
        # in a memory efficient fashion.
        # True catchment edges must have link statuses that are CLOSED:
        closed_links = self.grid.status_at_link == CLOSED_BOUNDARY
        # one of their end nodes must be not CLOSED:
        edge_link_head_open = self.grid.status_at_node[
            self.grid.node_at_link_head][closed_links] != CLOSED_BOUNDARY
        head_open_node_IDs = self.grid.node_at_link_head[closed_links][
            edge_link_head_open]
        tail_open_node_IDs = self.grid.node_at_link_tail[closed_links][
            np.logical_not(edge_link_head_open)]
        # Together, this is a list of the IDs of all the nodes on the catchment
        # perimeter. So:
        for node_list in (head_open_node_IDs, tail_open_node_IDs):
            for edgenode in node_list:
                edgenode_x = self.grid.x_at_node[edgenode]
                edgenode_y = self.grid.y_at_node[edgenode]
                dists_to_edgenode = self.grid.calc_distances_of_nodes_to_point(
                    (edgenode_x, edgenode_y))
                target_area_nodes[
                    dists_to_edgenode <= self._buffer_width] = True
        # finish off by stamping the core nodes over the top:
        target_area_nodes[opennodes] = True

        Xxin = self.grid.x_at_node[target_area_nodes]
        Yyin = self.grid.y_at_node[target_area_nodes]

# NOTE this is overly specific
        # These are elevation ranges for the 3 orographic groups
        OroGrp1 = np.arange(int(np.round(Zz.min())), 1350)
        OroGrp2 = np.arange(1350, 1500)
        OroGrp3 = np.arange(1500, int(np.round(Zz.max())))


        # lambda_, kappa, and C are parameters of the intensity-duration curves
        # of the form: intensity =
        # lambda*exp(-0.508*duration)+kappa*exp(-0.008*duration)+C
        lambda_ = [642.2, 578.0, 513.8, 449.5, 385.3, 321.1, 256.9, 192.7,
                   128.4, 64.1, 21.0]
        kappa = [93.1, 83.8, 74.5, 65.2, 55.9, 46.6, 37.2, 27.9, 18.6, 9.3,
                 0.9]
        C = [4.5, 4., 3.5, 3., 2.5, 2., 1.5, 1., 0.5, 0.25, 0.05]

        # Unlike MS's original implementation, we get our ET rates from the
        # generator fn, below

        Storm_matrix = np.zeros((self._max_numstorms*simyears, 12))
        Ptot_ann_global = np.zeros(simyears)
# NOTE we're trying to avoid needing to use Gauge_matrix_... structures

        Intensity_local_all = 0  # initialize all variables (concatenated matrices of generated output)
        #%Intensity_local_all = zeros(85*simyears,1); %initialize local_all variables (concatenated vector of generated output at each gauge location)
        Storm_totals_all = 0
        Duration_local_all = 0
        Gauges_hit_all = 0

        storm_count = 0
        master_storm_count = 0
        storm_trend = 0

        for syear in range(simyears):
            calendar_time = 0  # tracks simulation time per year in hours
            storm_trend += storminess_scaling_factor
            Ptotal = 0
            # sample from normal distribution and saves global value of Ptot
            # (that must be equalled or exceeded) for each year
            Ptot_ann_global[year] = np.random.normal(
                loc=Ptot_pdf_norm['mu'], scale=Ptot_pdf_norm['sigma'])
        #    clear Storm_total_local_year
            ann_cum_Ptot_gauge = np.zeros(numgauges)
            for storm inrange(5000):
                # clear cx cy r mask_name aa bb cc dd* North_hit North East East_hit self._rain_int_gauge intensity_val duration_val recess_val Ptotal* gdist center_val* int_dur_curve_num*
                self._rain_int_gauge.fill(0.)
                # sample uniformly from storm center matrix from grid with 10 m
                # spacings covering basin:
                # NOTE DEJH believes this should be a true random spatial
                # sample in a next iteration
                center_val_X = np.random.choice(X)
                center_val_Y = np.random.choice(Y)
                North = center_val_Y
                East = center_val_X

                area_val = genextreme.rvs(c=Area_pdf_EV['shape'],
                                          loc=Area_pdf_EV['mu'],
                                          scale=Area_pdf_EV['sigma'])
                # ^Samples from distribution of storm areas
                Storm_matrix[master_storm_count, 0] = master_storm_count
                Storm_matrix[master_storm_count, 1] = area_val
                # value of coord should be set to storm center selected
                # (same below)
                cx = East
                cy = North
                Storm_matrix[master_storm_count, 8] = cx
                Storm_matrix[master_storm_count, 9] = cy
                Storm_matrix[master_storm_count, 10] = year
                r = sqrt(area_val/pi)  # value here should be selected based on
                # area above in meters to match the UTM values in North and
                # East vectors.
                # Determine which gauges are hit by Euclidean geometry:
                gdist = (Easting-cx)**2 + (Northing-cy)**2
                mask_name = (gdist <= r**2)  # this is defacto Mike's aa
                gauges_hit = gauges[mask_name]
                num_gauges_hit = gauges_hit.size
                # this routine below allows for orography in precip by first
                # determining the closest gauge and then determining its
                # orographic grouping
                cc = np.argmin(gdist)
                closest_gauge = gauges[cc]  # this will be compared against
                # orographic gauge groupings to determine the appropriate set
                # of intensity-duration curves
                ######
                Storm_matrix[master_storm_count, 5] = num_gauges_hit
                # %gauges_hit_all(:,year) = [gauges_hit_all(:,year); gauges_hit];
                # this is weird sloppy matlab syntax, I believe replaced
                # correctly, below
                ## Gauges_hit_all = [Gauges_hit_all, gauges_hit]
                Gauges_hit_all.append(gauges_hit)
                North_hit = Northing[mask_name]
                East_hit = Easting[mask_name]

# %                 if ~isempty(gauges_hit)
# %                     viscircles([cx cy],r); %draw a circle with a particular radius around each storm center location
# %                 end
                # This routine below determines to which orographic group the
                # closest gauge to the storm center belongs to, and censors the
                # number of curves accordingly
                # missing top curve in GR1, top and bottom curves for GR2, and
                # bottom curve for GR3
                if closest_gauge in Gauge_GR1:
                    # %int_dur_curve_num = (2:numcurves)'; % these were empirically determined based on data from WG (monsoon rainfall only)-lowest orographic group.
                    baa = 'a'
                elif closest_gauge in Gauge_GR2:
                    # %int_dur_curve_num = (2:numcurves-1)'; % these were empirically determined based on data from WG (monsoon rainfall only)-middle orographic group.
                    baa = 'b'
                elif closest_gauge in Gauge_GR3:
                    # %int_dur_curve_num = (1:numcurves-1)'; % these were empirically determined based on data from WG (monsoon rainfall only)-highest orographic group.
                    baa = 'c'
                else:
                    raise ValueError('closest_gauge not found in curve lists!')
                # int_dur_curve_num = np.arange(numcurves)
                duration_val = genextreme.rvs(c=Duration_pdf_GEV['shape'],
                                              loc=Duration_pdf_GEV['mu'],
                                              scale=Duration_pdf_GEV['sigma'])
                # round to nearest minute for consistency with measured data:
                duration_val = round(duration_val)
                # %Duration_global(storm,year) = duration_val;
                Storm_matrix[master_storm_count, 2] = duration_val
                # %Duration_all = [Duration_all; duration_val];

                # %         int_dur_curve_numy = int_dur_curve_num;
                # %         for poo = 1:100
                # %             int_dur_curve_numy = [int_dur_curve_numy;int_dur_curve_num]; %this just repeats the sequence many times to allow datasample to function better.
                # %         end
                # %         int_dur_curve_num = int_dur_curve_numy;

                # % original curve probs for 21-14-7%: [0.0718 0.0782 0.0845 0.0909 0.0909 0.0909 0.0909 0.0909 0.0973 0.1036 0.1100]
                # % original curve probs for 24-16-8%: [0.0691 0.0764 0.0836 0.0909 0.0909 0.0909 0.0909 0.0909 0.0982 0.1055 0.1127]
                # % original curve probs for 27-18-9%: [0.0664 0.0745 0.0827 0.0909 0.0909 0.0909 0.0909 0.0909 0.0991 0.1073 0.1155]
                # % original curve probs for 30-20-10%: [0.0636 0.0727 0.0819 0.0909 0.0909 0.0909 0.0909 0.0909 0.1001 0.1090 0.1182]

                # add weights to reflect reasonable probabilities that favor
                # lower curves:
                if baa == 'a':
                    wgts = [0.0318, 0.0759, 0.0851, 0.0941, 0.0941, 0.0941,
                            0.0941, 0.0941, 0.1033, 0.1121, 0.1213]
                elif baa == 'b':
                    wgts = [0.0478, 0.0778, 0.0869, 0.0959, 0.0959, 0.0959,
                            0.0959, 0.0959, 0.1051, 0.1141, 0.0888]
                else:
                    wgts = [0.0696, 0.0786, 0.0878, 0.0968, 0.0968, 0.0968,
                            0.0968, 0.0968, 0.1060, 0.1149, 0.0591]
                int_dur_curve_val = np.random.choice(numcurves, p=wgts)
                # %Curve_num_global(storm,year) = int_dur_curve_val;
                Storm_matrix[master_storm_count, 3] = int_dur_curve_val
                if int_dur_curve_val == 1:
                    intensity_val = (642.2*np.exp(-0.508*duration_val) +
                                     93.1*np.exp(-0.008*duration_val) + 4.5)
                elif int_dur_curve_val == 2:
                    intensity_val = (578.0*np.exp(-0.508*duration_val) +
                                     83.8*np.exp(-0.008*duration_val) + 4.)
                elif int_dur_curve_val == 3:
                    intensity_val = (513.8*exp(-0.508*duration_val) +
                                     74.5*exp(-0.008*duration_val) + 3.5)
                elif int_dur_curve_val == 4:
                    intensity_val = (449.5*exp(-0.508*duration_val) +
                                     65.2*exp(-0.008*duration_val) + 3.)
                elif int_dur_curve_val == 5:
                    intensity_val = (385.3*exp(-0.508*duration_val) +
                                     55.9*exp(-0.008*duration_val) + 2.5)
                elif int_dur_curve_val == 6:
                    intensity_val = (321.1*exp(-0.508*duration_val) +
                                     46.6*exp(-0.008*duration_val) + 2.)
                elif int_dur_curve_val == 7:
                    intensity_val = (256.9*exp(-0.508*duration_val) +
                                     37.2*exp(-0.008*duration_val) + 1.5)
                elif int_dur_curve_val == 8:
                    intensity_val = (192.7*exp(-0.508*duration_val) +
                                     27.9*exp(-0.008*duration_val) + 1.)
                elif int_dur_curve_val == 9:
                    intensity_val = (128.4*exp(-0.508*duration_val) +
                                     18.6*exp(-0.008*duration_val) + 0.5)
                elif int_dur_curve_val == 10:
                    intensity_val = (64.1*exp(-0.508*duration_val) +
                                     9.3*exp(-0.008*duration_val) + 0.25)
                elif int_dur_curve_val == 11:
                    intensity_val = (21.*exp(-0.508*duration_val) +
                                     0.9*exp(-0.008*duration_val) + 0.05)
                else:
                    raise ValueError('int_dur_curve_val not recognised!')
                # ...these curves are based on empirical data from WG.

                fuzz_int_val = np.random.choice(fuzz)
                intensity_val2 = intensity_val + fuzz_int_val
                # ^this allows for +/-5 mm/hr fuzzy tolerance around selected
                # intensity
# NOTE DEJH believes this is pretty sketchy:
                # if intensity_val2 < 1.:  # cannot have zero or -ve intensity
                #     intensity_val = 1.
                # else:
                #     intensity_val = intensity_val2
                intensity_val = intensity_val2.clip(1.)
                intensity_val *= storm_scaling
                # This scales the storm center intensity upward, so the values
                # at each gauge are realistic once the gradient is applied.
                Storm_matrix[master_storm_count, 4] = intensity_val
                # %Intensity_global(storm,year) = intensity_val;
                # %Intensity_all = [Intensity_all; intensity_val]; %selected storm center intensities

                # area to determine which gauges are hit:

                recess_val = np.random.normal(
                    loc=Recess_pdf_norm['mu'], scale=Recess_pdf_norm['sigma'])
                # this pdf of recession coefficients determines how intensity
                # declines with distance from storm center (see below)
                Storm_matrix[master_storm_count, 6] = recess_val
                # determine cartesian distances to all hit gauges and
                # associated intensity values at each gauge hit by the storm
                # This is a data storage solution to avoid issues that can
                # arise with slicing grid areas with heavy tailed sizes
                self._gauge_dist_km[mask_name] = Easting[mask_name]
                self._gauge_dist_km[mask_name] -= cx
                np.square(self._gauge_dist_km[mask_name],
                          out=self._gauge_dist_km[mask_name])
                self._temp_dataslots[mask_name] = Northing[mask_name]
                self._temp_dataslots[mask_name] -= cy
                np.square(self._temp_dataslots[mask_name],
                          out=self._temp_dataslots[mask_name])
                self._gauge_dist_km[mask_name] += self._temp_dataslots[
                    mask_name]
                np.sqrt(self._gauge_dist_km[mask_name],
                        out=self._gauge_dist_km[mask_name])
                self._gauge_dist_km[mask_name] /= 1000.
                self._rain_int_gauge[mask_name] = self._gauge_dist_km[
                    mask_name]
                np.square(self._rain_int_gauge[mask_name],
                          out=self._rain_int_gauge[mask_name])
                self._rain_int_gauge[mask_name] *= -2. * recess_val**2
                np.exp(self._rain_int_gauge[mask_name],
                       out=self._rain_int_gauge[mask_name])
                self._rain_int_gauge[mask_name] *= intensity_val
                # calc of _rain_int_gauge follows Rodriguez-Iturbe et al.,
                # 1986; Morin et al., 2005 but sampled from a distribution
                self._temp_dataslots[mask_name] = self._rain_int_gauge[
                    mask_name]
                self._temp_dataslots[mask_name] *= duration_val / 60.
                ann_cum_Ptot_gauge[mask_name] += self._temp_dataslots[
                    mask_name]

                # for jj = 1:numgauges
                #     eval(['Gauge_matrix_',num2str(jj),'(master_storm_count,1) = year;']) %year
                #     eval(['Gauge_matrix_',num2str(jj),'(master_storm_count,2) = master_storm_count;']) %storm #
                #     eval(['Gauge_matrix_',num2str(jj),'(master_storm_count,3) = self._rain_int_gauge(jj);'])
                #     eval(['Gauge_matrix_',num2str(jj),'(master_storm_count,4) = duration_val;'])
                #     eval(['Gauge_matrix_',num2str(jj),'(master_storm_count,5) = self._rain_int_gauge(jj)*duration_val/60;']) %storm total
                #     eval(['Gauge_matrix_',num2str(jj),'(master_storm_count,6) = ann_cum_Ptot_gauge(jj);']) %ann cum total (Ptot)
                # end
                %FIX THIS PART
                Intensity_local_all = [Intensity_local_all,self._rain_int_gauge]; %#ok<AGROW> %collect into vector of all simulated intensities (at all gauges)
                dur_step(1:85) = duration_val;
                Duration_local_all = [Duration_local_all,dur_step]; %#ok<AGROW>
                Storm_total_local_year(storm,1:numgauges) = self._rain_int_gauge.*duration_val/60; %#ok<SAGROW> %collect storm total data for all gauges into rows by storm
                Storm_totals_all = [Storm_totals_all,self._rain_int_gauge.*duration_val/60]; %#ok<AGROW>
                Storm_matrix(master_storm_count,8) = intensity_val*duration_val/60;
                for k = 1:numgauges
                    Ptotal(k) = nansum(Storm_total_local_year(:,k)); %#ok<SAGROW> %sum the annual storm total at each gauge
                end
                %Ptotal_test = find((nanmean(Ptotal) + nanstd(Ptotal)/sqrt(85)) > Ptot_ann_global(year));    %once the mean of all gauges exceeds the selected annual storm total, a new simulation year begins
                Ptotal_test = find(nanmedian(Ptotal) > Ptot_ann_global(year));    %once the median of all gauges exceeds the selected annual storm total, a new simulation year beginsPtotal_test = find(Ptotal > Ptot_ann_global(year));    %once the first gauge exceeds the selected annual storm total, a new simulation year begins
                %Ptotal = Ptotal + duration_val(storm)/60*intensity_val(storm);
                if ~isempty(Ptotal_test)
                    %eval(['Ptotal_local_',num2str(year),'(1:numgauges) = Ptotal;'])
                    %Ptotal_local(year,1:numgauges) = Ptotal;
                    for l = 1:numgauges
                        Ptotal_local(year,l) = Ptotal(l); %#ok<SAGROW>
                    end
                    break %start a new simulation year
                end

                %local and concatenated vector output
                %concatenate data into single vectors
                %         a = find(Intensity_ave_local == 0);
                %         Intensity_ave_local(a) = NaN;


                %         a = find(intensity_val == 0); %FIX
                %         intensity_val(a) = NaN;
                %         a = find(duration_val == 0);
                %         duration_val(a) = NaN;
                %         a = find(area_val == 0);
                %         area_val(a) = NaN;
                %eval(['ann_gauges_',num2str(year),'(:,storm) = gauges_hit(:,storm);'])
                %         eval(['ann_intensity_',num2str(year),'(storm) = intensity_val;'])
                %         eval(['ann_duration_',num2str(year),'(storm) = duration_val./60;']) %convert duration values to hours.
                %         eval(['ann_area_',num2str(year),'(storm) = area_val;'])
                eval(['Storm_total_local_year_',num2str(year),'(storm,1:numgauges) = Storm_total_local_year(storm,1:numgauges);']) %collect all local annual storm totals for each gauge.
                int_arr_val = random(Int_arr_pdf,1,true); %Samples from distribution of interarrival times (hours). This can be used to develop STORM output for use in rainfall-runoff models or any water balance application.
                storm_count += 1
                master_storm_count += 1
            end %storm loop
        end %year loop
        %hold on
        %plot(Easting,Northing,'o')
        %grid on
        AA = find(Storm_matrix(:,9)>0); %gets rid of trailing zeros from initialized matrix
        Storm_matrix = Storm_matrix(AA,:);
        AB = find(Gauge_matrix_1(:,2)>0);
        for CC = 1:numgauges
            eval(['Gauge_matrix_',num2str(CC),' = Gauge_matrix_',num2str(CC),'(AB,:);'])
        end
        % for ii = 1:numgauges
        %     Storm_total_mean_local(ii) = nanmean(Storm_total_local(:,ii));
        %     Storm_total_med_local(ii) = nanmedian(Storm_total_local(:,ii));
        %     Storm_total_max_local(ii) = nanmax(Storm_total_local(:,ii));
        %     Storm_total_in_local(ii) = nanmin(Storm_total_local(:,ii));
        % end

        %concatenate data into single vectors
        % for jj = 1:simyears %years of data
        % Gauges_hit_all = horzcat(gauges_hit_all(1,:),gauges_hit_all(jj,:));
        % end

        %global output
        % a = find(Area_global == 0);
        % Area_global(a) = NaN;
        % a = find(Duration_global == 0);
        % Duration_global(a) = NaN;
        % a = find(Curve_num_global == 0);
        % Curve_num_global(a) = NaN;
        %a = find(Storm_center_global == 0);
        %Storm_center_global(a) = NaN;
        a = find(Gauges_hit_all == 0);
        Gauges_hit_all(a) = NaN;

        GZ = find(Intensity_local_all>0);
        Intensity_all = Intensity_local_all(GZ);
        Duration_all = Duration_local_all(GZ);
        Storm_totals_all = Storm_totals_all(GZ);
        Ptot_ann_global = Ptot_ann_global(2:length(Ptot_ann_global));
        Gauges_hit_all = Gauges_hit_all(2:length(Gauges_hit_all));

        eval(['save C:\bliss\sacbay\papers\WG_Rainfall_Model\model_output\',t2,'\Ptot_ann_',num2str(simyears),'y_global_',t2,' Ptot_ann_global'])
        eval(['save C:\bliss\sacbay\papers\WG_Rainfall_Model\model_output\',t2,'\Storm_matrix_',num2str(simyears),'y_',t2,' Storm_matrix'])
        eval(['save C:\bliss\sacbay\papers\WG_Rainfall_Model\model_output\',t2,'\Gauges_hit_',num2str(simyears),'y_all_',t2,' Gauges_hit_all'])
        eval(['save C:\bliss\sacbay\papers\WG_Rainfall_Model\model_output\',t2,'\Storm_totals_',num2str(simyears),'y_all_',t2,' Storm_totals_all'])
        eval(['save C:\bliss\sacbay\papers\WG_Rainfall_Model\model_output\',t2,'\Intensity_',num2str(simyears),'y_selected_',t2,' Intensity_all'])
        eval(['save C:\bliss\sacbay\papers\WG_Rainfall_Model\model_output\',t2,'\Duration_',num2str(simyears),'y_selected_',t2,' Duration_all'])

        for kk = 1:numgauges
            eval(['save C:\bliss\sacbay\papers\WG_Rainfall_Model\model_output\',t2,'\Gauge_matrix_',num2str(kk),'_y_',t2,' Gauge_matrix_',num2str(kk);])
        end

        boo = etime(clock,t0);
        runtime_seconds = boo %#ok<NOPTS>
        runtime_minutes = boo/60 %#ok<NOPTS>

    def _yield_ET_timeseries(ET_monthly_day, ET_monthly_night, startmonth=0,
                             endmonth=12):
        daysinmonth = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
        for yr in self._numyrs:
            ET_for_my_year = []
            for month in range(startmonth, endmonth):
                notnan = np.logical_not(np.isnan(ET_monthly_day[:, month]))
                ET_day = np.random.choice(ET_monthly_day[:, month][notnan],
                                          size=daysinmonth[month])
                ET_night = np.random.choice(ET_monthly_night[:, month][notnan],
                                            size=daysinmonth[month])
                interleaved = [val for pair in zip(ET_day, ET_night)
                               for val in pair]
                ET_for_my_year.extend(interleaved)
                yield ET_for_my_year
