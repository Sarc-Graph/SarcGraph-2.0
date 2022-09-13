##################################################################
# Description:                                                   #
# This script contrains Python implementation of the SarcGraph   #
# Algorithm for sarcomere detection used for sarcomere detection #
# and tracking                                                   #
##################################################################
# Author: Saeed Mohammadzadeh                                    #
# Email: saeedmhz@bu.edu                                         #
##################################################################
import numpy as np
import pandas as pd
import trackpy as tp
import networkx as nx

import skvideo.io
import skimage.io
import skvideo.utils

from skimage.filters import laplace, gaussian, threshold_otsu
from skimage import measure
from sklearn.cluster import OPTICS
from sklearn.neighbors import NearestNeighbors
from scipy.spatial import distance_matrix
from pathlib import Path
from typing import List


class SarcGraph:
    """A class that contrain all the functions used for loading an image
    or a video data, applying zdisc segmentation and tracking, and detecting
    sarcomeres
    ----------
    output_dir : str
        Parent location for saving processed information
    input_type: str
        Specify if the input data is an 'image' or a 'video'
    """

    def __init__(self, output_dir=None, input_type="video"):
        if output_dir is None:
            raise ValueError("Output directory should be specified.")
        self.output_dir = output_dir
        self.input_type = input_type

    ###############################################################################
    #                                  Utilities                                  #
    ###############################################################################
    def data_loader(self, input_path: str) -> np.ndarray:
        """
        Inputs
        ----------
        input_path : str
            The address to the data file.
        Returns
        -------
            A numpy array containing all frames in the raw form
        """
        if self.input_type == "video":
            data = skvideo.io.vread(input_path)
            if data.shape[0] > 1:
                return data
        return skimage.io.imread(input_path)

    def _to_gray(self, data: np.ndarray) -> np.ndarray:
        """
        Inputs
        ----------
        data : np.ndarray
            A numpy array containing all frames in the raw form
        Returns
        -------
            A numpy array containing all frames in gray scale
        """
        data_gray = skvideo.utils.rgb2gray(data)
        if self.input_type == "video":
            if data_gray.shape[0] < 2:
                raise ValueError(
                    "Video is not loaded correctly!\
                    Try manually loading the video file."
                )
        return skvideo.utils.rgb2gray(data)

    def save_data(self, data: np.ndarray, data_name: str) -> None:
        """Saves provided information 'data'
        Inputs
        ----------
        data : np.ndarray
            data to be saved
        data_name: str
            saved file name
        """
        Path(f"./{self.output_dir}").mkdir(parents=True, exist_ok=True)
        if type(data) in [np.ndarray, list]:
            np.save(f"./{self.output_dir}/{data_name}.npy", data, allow_pickle=True)
        elif type(data) == pd.DataFrame:
            data.to_pickle(f"./{self.output_dir}/{data_name}.pkl")
        else:
            raise ValueError(
                "Data type cannot be saved. Only numpy.ndarray and pandas.DataFrame are\
                supported."
            )

    def filter_frames(self, frames: np.ndarray) -> np.ndarray:
        """Applies a laplacian and a gaussian filter on each frame for
        zdisc segmentation
        Inputs
        ----------
        data : np.ndarray
            A numpy array containing all frames in gray scale
        Returns
        -------
            A numpy array containing filtered frames in gray scale
        """
        if len(frames.shape) != 4 or frames.shape[-1] != 1:
            raise ValueError(
                f"Passed array ({frames.shape}) is not of the\
                correct shape (frames, dim_1, dim_2, channels=1)"
            )
        filtered_frames = np.zeros(frames.shape[:-1])
        for i, frame in enumerate(frames[:, :, :, 0]):
            laplacian = laplace(frame)
            filtered_frames[i] = gaussian(laplacian)
        return filtered_frames

    def zdiscs_info_to_pandas(self, zdiscs_all_frames: list) -> pd.DataFrame:
        """Create a pandas dataframe that captures zdiscs related information for all
        frames
        Inputs
        ----------
        zdiscs_all_frames :
            A list of numpy arrays containing zdiscs information for each frame
        Returns
        -------
            A Pandas DataFrame containing zdiscs information [frame number, center
            position, end points positions]
        """
        if self.input_type == "video" and len(zdiscs_all_frames) < 2:
            raise ValueError("Video is not loaded correctly.")
        data_frames = []
        for i, zdiscs_one_frame in enumerate(zdiscs_all_frames):
            if type(zdiscs_one_frame) != np.ndarray:
                raise TypeError("Input should be a list of numpy arrays.")
            if zdiscs_one_frame.shape[-1] != 6:
                raise ValueError(
                    "Enough information is not included in zdiscs_info_all"
                )
            frame_id = i * np.ones((len(zdiscs_one_frame), 1))
            zdiscs_info_frame_extended = np.hstack((frame_id, zdiscs_one_frame))
            data_frames.append(
                pd.DataFrame(
                    zdiscs_info_frame_extended,
                    columns=[
                        "frame",
                        "x",
                        "y",
                        "p1_x",
                        "p1_y",
                        "p2_x",
                        "p2_y",
                    ],
                )
            )
        return pd.concat(data_frames)

    ###############################################################################
    #                             Z-Disc Segmentation                             #
    ###############################################################################
    def process_input(
        self,
        input_path: str = None,
        input_file: np.ndarray = None,
        save_data: bool = False,
    ) -> np.ndarray:
        """Loads an input image or video into a numpy array,
        filters all frames and returns the array.
        Inputs
        ----------
        input_path : str
            The address of an image or video file
        input_file : np.ndarray
            Raw input image or video given as a 4 dimensional numpy array [number of
            frames, x resolution, y resolution, number of channels]
        save_data : bool
            Must be set to True to save info
        Returns
        -------
            A numpy array of all filtered frames
        """
        if input_file is None:
            raw_data = self.data_loader(input_path)
        else:
            raw_data = input_file
        raw_data_gray = self._to_gray(raw_data)
        filtered_data = self.filter_frames(raw_data_gray)
        if save_data:
            self.save_data(raw_data_gray, data_name="raw-frames")
            self.save_data(filtered_data, data_name="filtered-frames")
        return filtered_data

    def detect_contours(self, filtered_frames, save_data=False):
        """Detects zdiscs in each frame and returns 2d contours of all detected zdiscs
        Inputs
        ----------
        filtered_frames : np.ndarray
            A numpy array of all filtered frames
        save_data : bool
            Must be set to True to save info
        Returns
        -------
            A list of numpy object array of all detected zdiscs as 2d contours
        """
        length_checker = np.vectorize(len)
        valid_contours = []
        for i, frame in enumerate(filtered_frames):
            contour_thresh = threshold_otsu(frame)
            contours = measure.find_contours(frame, contour_thresh)
            contours_size = length_checker(contours)
            valid_contours.append(np.delete(contours, np.where(contours_size < 8)[0]))
        if save_data:
            self.save_data(data=valid_contours, data_name="contours")
        return valid_contours

    def process_contour(self, contour):
        """Extracts center of a zdisc as well as its two end points given its 2d contour
        ----------
        contour : np.ndarray
            A 2d contour of a detected zdisc
        Returns
        -------
            zdisc center, end point 1, end point 2
        """
        if len(contour) < 2:
            raise ValueError("A contour must have at least 2 points.")
        # coordinates of the center of a contour
        center_coords = np.mean(contour, axis=0)
        # find zdisc direction by matching furthest points on the contour
        dist_mat = distance_matrix(contour, contour)
        indices = np.unravel_index(dist_mat.argmax(), dist_mat.shape)
        # coordinates of the two points on the contour with maximum distance
        p1, p2 = contour[indices[0]], contour[indices[1]]
        return np.hstack((center_coords, p1, p2))

    def zdisc_segmentation(
        self,
        input_path: str = None,
        input_file: np.ndarray = None,
        save_data: bool = False,
    ):
        """Segment Z-Discs in a all frame of a video or in an image and return a pandas
        DataFrame containing [frame number, center position, end point 1, end point 2]
        for each zdisc.
        ----------
        input_path : str
            The address of an image or video file
        input_file : np.ndarray
            Input file as a numpy array [number of frames, x resolution, y resolution,
            channels]
        save_data : bool
            Must be set to True to save information throughout the segmentation process
        Returns
        -------
            A pandas DataFrame of each detected zdisc
        """
        if input_path is None and input_file is None:
            raise ValueError("Either input_path or input_file should be specified.")
        else:
            filtered_data = self.process_input(input_path, input_file, save_data)
        contours_all_frames = self.detect_contours(filtered_data, save_data)
        zdiscs_all_frames = []
        for contours_one_frame in contours_all_frames:
            zdiscs_one_frame = np.zeros((len(contours_one_frame), 6))
            for i, contour in enumerate(contours_one_frame):
                zdiscs_one_frame[i] = self.process_contour(contour)
            zdiscs_all_frames.append(zdiscs_one_frame)
        zdiscs_all_frames_dataframe = self.zdiscs_info_to_pandas(zdiscs_all_frames)
        if save_data:
            self.save_data(data=zdiscs_all_frames_dataframe, data_name="zdiscs-info")
        return zdiscs_all_frames_dataframe

    ###############################################################################
    #                               Z-disc Tracking                               #
    ###############################################################################
    def find_fully_tracked_zdiscs(self, tracked_zdiscs):

        num_frames = tracked_zdiscs.frame.max() + 1
        tracked_zdiscs_grouped = tracked_zdiscs.groupby("particle")["particle"]
        tracked_zdiscs["freq"] = tracked_zdiscs_grouped.transform("count")
        fully_tracked_zdiscs = tracked_zdiscs.loc[tracked_zdiscs.freq == num_frames]
        partially_tracked_zdiscs = tracked_zdiscs.loc[tracked_zdiscs.freq < num_frames]
        return num_frames, partially_tracked_zdiscs, fully_tracked_zdiscs

    # load all of tracked z-disc clusters and merge similar clusters of
    # partially tracked z-discs
    def merge_partially_tracked_zdiscs(
        self, tracked_zdiscs, partial_tracking_threshold
    ):
        (
            num_frames,
            partially_tracked_zdiscs,
            fully_tracked_zdiscs,
        ) = self.find_fully_tracked_zdiscs(tracked_zdiscs)

        partially_tracked_clusters = (
            partially_tracked_zdiscs[["x", "y", "particle"]]
            .groupby(by=["particle"])
            .mean()
        )

        # merge related clusters (neighbors)
        data = np.array(partially_tracked_clusters)
        optics_model = OPTICS(eps=1, min_samples=2)
        optics_result = optics_model.fit_predict(data)
        optics_clusters = np.unique(optics_result)

        all_merged_zdiscs = []
        for i, optics_cluster in enumerate(optics_clusters):
            if optics_cluster >= 0:
                index = np.where(optics_result == optics_cluster)[0]
                particles_in_cluster = partially_tracked_clusters.iloc[
                    index
                ].index.to_numpy()
                merged_zdiscs = (
                    partially_tracked_zdiscs.loc[
                        partially_tracked_zdiscs["particle"].isin(particles_in_cluster)
                    ]
                    .groupby("frame")
                    .mean()
                )
                if len(merged_zdiscs) > num_frames * partial_tracking_threshold:
                    merged_zdiscs.particle = -(i + 1)
                    merged_zdiscs.freq = len(merged_zdiscs)
                    all_merged_zdiscs.append(merged_zdiscs.reset_index())
        if all_merged_zdiscs:
            all_merged_zdiscs = pd.concat(all_merged_zdiscs)
            return pd.concat((fully_tracked_zdiscs, all_merged_zdiscs))
        else:
            return fully_tracked_zdiscs

    def zdisc_tracking(
        self, partial_tracking_threshold, input_path=None, zdiscs_info=None, tp_depth=4
    ):
        if input_path is None and zdiscs_info is None:
            raise ValueError(
                "Either input_path to the original video/image or a numpy array of\
                frame by frame zdiscs_info should be specified.."
            )
        elif zdiscs_info is None:
            zdiscs_info = self.zdisc_segmentation(input_path)

        zdiscs_info_dataframe = self.zdiscs_info_to_pandas(zdiscs_info)

        if self.input_type == "image":
            print("Cannot perform tracking on a single-frame image.")
            zdiscs_info_dataframe["particle"] = np.arange(len(zdiscs_info_dataframe))
            return zdiscs_info_dataframe

        # Run tracking --> using the trackpy package
        # http://soft-matter.github.io/trackpy/v0.3.0/tutorial/prediction.html
        t = tp.link_df(zdiscs_info_dataframe, tp_depth, memory=int(len(zdiscs_info)))
        tracked_zdiscs = tp.filter_stubs(t, int(len(zdiscs_info) * 0.10)).reset_index(
            drop=True
        )

        return self.merge_partially_tracked_zdiscs(
            tracked_zdiscs, partial_tracking_threshold
        )

    #################################################################################
    #                              Sarcomere Detection                              #
    #################################################################################
    # if input_type=='image' then zdisc_clusters are the zdiscs in the only available
    # frame.
    # if input_type=='video' then zdisc_clusters are the average location of a tracked
    # zdisc over all frames.
    def zdisc_clusters_to_graph(self, zdisc_clusters):
        # finding K(=3) nearest clusters to each cluster
        neigh = NearestNeighbors(n_neighbors=2)
        neigh.fit(zdisc_clusters[:, 0:2])
        nearestNeighbors = neigh.kneighbors(
            zdisc_clusters[:, 0:2], 4, return_distance=False
        )

        # create a graph with zdiscs as nodes and connections between a zdisc and its
        # neighbors as edges
        num_nodes = len(zdisc_clusters)
        G = nx.Graph()
        G.add_nodes_from(range(num_nodes))

        # add the position of each zdisc as a node attribute to the graph
        nodes_pos_dict = {
            i: zdisc_info[0:2] for i, zdisc_info in enumerate(zdisc_clusters)
        }
        nodes_particle_dict = {
            j: zdisc_info[-1] for j, zdisc_info in enumerate(zdisc_clusters)
        }

        nx.set_node_attributes(G, values=nodes_pos_dict, name="pos")
        nx.set_node_attributes(G, values=nodes_particle_dict, name="particle_id")

        # add a connection between each zdisc and its K(=3) nearest neighbors
        edges = []
        for node, neighbors in enumerate(nearestNeighbors[:, 1:]):
            for neighbor in neighbors:
                edges.append((node, neighbor))
        G.add_edges_from(edges)

        return G

    def score_cluster_connections(
        self, G, c_avg_length=1, c_angle=1, c_diff_length=1, l_avg=12.0
    ):
        # scoring edges of the graph
        edges_attr_dict = {}
        for node in range(G.number_of_nodes()):
            for neighbor in G.neighbors(node):
                score = 0
                for far_neighbor in G.neighbors(neighbor):
                    if far_neighbor in [node, neighbor]:
                        pass
                    else:
                        # calculate the scores
                        v1 = (
                            G.nodes[neighbor]["pos"] - G.nodes[node]["pos"]
                        )  # vector connecting node to neighbor
                        l1 = np.linalg.norm(v1)
                        v2 = (
                            G.nodes[far_neighbor]["pos"] - G.nodes[neighbor]["pos"]
                        )  # vector connecting neighbor to far_neighbor
                        l2 = np.linalg.norm(v2)

                        d_theta = np.arccos(np.dot(v1, v2) / (l1 * l2)) / (np.pi / 2)
                        d_l = np.abs(l2 - l1) / l1

                        angle_score = np.power(1 - d_theta, 2) if d_theta >= 1 else 0
                        diff_length_score = 1 / (1 + d_l)
                        avg_length_score = np.exp(-np.pi * (1 - l1 / l_avg) ** 2)

                        score = np.max(
                            (
                                score,
                                c_avg_length * avg_length_score
                                + c_diff_length * diff_length_score
                                + c_angle * angle_score,
                            )
                        )
                edges_attr_dict[(node, neighbor)] = score
        nx.set_edge_attributes(G, values=edges_attr_dict, name="score")
        return G

    def find_valid_cluster_connections(
        self, G, score_threshold=0.01, angle_threshold=1.2
    ):
        # graph pruning (visit all nodes):
        # for each node increase the validity of up to 2 most likely connections by 1
        nx.set_edge_attributes(G, values=0, name="validity")
        for node in range(G.number_of_nodes()):
            vectors = []
            scores = []
            neighbors = list(G.neighbors(node))
            for neighbor in neighbors:
                vectors.append(G.nodes[neighbor]["pos"] - G.nodes[node]["pos"])
                scores.append(G[node][neighbor]["score"])

            # sort by scores
            if np.max(scores) > score_threshold:
                sort_indices = np.argsort(scores)[::-1]
                best_vector = vectors[sort_indices[0]]
                G[node][neighbors[sort_indices[0]]]["validity"] += 1
                for idx in sort_indices[1:]:
                    s = scores[idx]
                    n = neighbors[idx]
                    v = vectors[idx]

                    l1 = np.linalg.norm(best_vector)
                    l2 = np.linalg.norm(v)
                    theta = np.arccos(np.dot(v, best_vector) / (l1 * l2)) / (np.pi / 2)

                    if theta > angle_threshold and s > score_threshold:
                        G[node][n]["validity"] += 1
                        break
        return G

    def detect_myofibrils(
        self, partial_tracking_threshold, input_path=None, fully_tracked_zdiscs=None
    ):
        if input_path is None and fully_tracked_zdiscs is None:
            raise ValueError(
                """Either input_path to the original video/image
            or trackpy results should be provided."""
            )
        elif fully_tracked_zdiscs is None:
            fully_tracked_zdiscs = self.zdisc_tracking(
                partial_tracking_threshold, input_path=input_path
            )

        fully_tracked_zdiscs_clusters = (
            fully_tracked_zdiscs.groupby("particle")
            .mean()
            .reset_index()[["x", "y", "particle"]]
            .to_numpy()
        )
        G = self.zdisc_clusters_to_graph(fully_tracked_zdiscs_clusters)
        G = self.score_cluster_connections(G)
        G = self.find_valid_cluster_connections(G)

        edges2remove = []
        for edge in G.edges():
            if G.edges[edge]["validity"] < 2:
                edges2remove.append(edge)
        G.remove_edges_from(edges2remove)

        myofibrils = [G.subgraph(c).copy() for c in nx.connected_components(G)]
        sarcs_zdiscs_ids = []
        for myofibril in myofibrils:
            for zdisc_1, zdisc_2 in myofibril.edges:
                sarcs_zdiscs_ids.append(
                    [
                        myofibril.nodes[zdisc_1]["particle_id"],
                        myofibril.nodes[zdisc_2]["particle_id"],
                    ]
                )
        sarcs_zdiscs_ids = np.array(sarcs_zdiscs_ids).astype(int)

        frame_num = np.max(fully_tracked_zdiscs.frame)
        sarc_num = len(sarcs_zdiscs_ids)
        sarc_info = np.zeros((5, sarc_num, frame_num))
        for i, sarc in enumerate(sarcs_zdiscs_ids):
            for frame in range(frame_num):
                zdisc_1_index = np.where(
                    np.logical_and(
                        fully_tracked_zdiscs.particle == sarc[0],
                        fully_tracked_zdiscs.frame == frame,
                    )
                )
                zdisc_1 = fully_tracked_zdiscs.iloc[zdisc_1_index]
                zdisc_2_index = np.where(
                    np.logical_and(
                        fully_tracked_zdiscs.particle == sarc[1],
                        fully_tracked_zdiscs.frame == frame,
                    )
                )
                zdisc_2 = fully_tracked_zdiscs.iloc[zdisc_2_index].replace("", np.nan)
                if zdisc_1.empty or zdisc_2.empty:
                    sarc_info[:, i, frame] = np.nan
                else:
                    sarc_info[0, i, frame] = np.mean(
                        zdisc_1.x.values + zdisc_2.x.values
                    )
                    sarc_info[1, i, frame] = np.mean(
                        zdisc_1.y.values + zdisc_2.y.values
                    )
                    sarc_info[2, i, frame] = np.linalg.norm(
                        zdisc_1[["x", "y"]].values - zdisc_2[["x", "y"]].values
                    )
                    zdisc_1_width = np.linalg.norm(
                        zdisc_1[["p1_x", "p1_y"]].values
                        - zdisc_1[["p2_x", "p2_y"]].values
                    )
                    zdisc_2_width = np.linalg.norm(
                        zdisc_2[["p1_x", "p1_y"]].values
                        - zdisc_2[["p2_x", "p2_y"]].values
                    )
                    sarc_info[3, i, frame] = np.mean(zdisc_1_width + zdisc_2_width)
                    sarc_angle = np.arctan2(
                        zdisc_2.y.values - zdisc_1.y.values,
                        zdisc_2.x.values - zdisc_1.x.values,
                    )
                    if sarc_angle < 0:
                        sarc_angle += np.pi
                    sarc_info[4, i, frame] = sarc_angle

        np.save(f"{self.output_dir}/sarcomeres-info.npy", sarc_info)

        return myofibrils  # , sarc_info
