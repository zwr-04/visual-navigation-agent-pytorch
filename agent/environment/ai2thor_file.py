# -*- coding: utf-8 -*-
import json
import random

import h5py
import numpy as np
from scipy import spatial

from agent.environment.environment import Environment


class THORDiscreteEnvironment(Environment):

    acts = ["MoveAhead", "RotateRight", "RotateLeft", "MoveBack",
            "LookUp", "LookDown", "MoveRight", "MoveLeft"]

    def __init__(self,
                 method: str,
                 reward: str,
                 scene_name='FloorPlan1',
                 n_feat_per_location=1,
                 history_length: int = 4,
                 terminal_state=0,
                 h5_file_path=None,
                 action_size: int = 4,
                 mask_size: int = 5,
                 **kwargs):
        """THORDiscreteEnvironment constructor, it represent a world where an agent evolves

        Keyword Arguments:
            scene_name {str} -- Name of the current world (default: {'bedroom_04'})
            resnet_trained {[type]} -- Resnet network used to compute features (default: {None})
            n_feat_per_location {int} -- Number of feature by position in the world (default: {1})
            history_length {int} -- Number of frame to stack so the network take in account previous observations (default: {4})
            terminal_state_id {int} -- Terminal position represented by an ID (default: {0})
            h5_file_path {[type]} -- Path to precomputed world (default: {None})
            input_queue {mp.Queue} -- Input queue to receive resnet features (default: {None})
            output_queue {mp.Queue} -- Output queue to ask for resnet features (default: {None})
            evt {mp.Event} -- Event to tell the GPUThread that there are new data to compute (default: {None})
        """
        super(THORDiscreteEnvironment, self).__init__()

        if h5_file_path is None:
            h5_file_path = f"/app/data/{scene_name}.h5"
        elif callable(h5_file_path):
            h5_file_path = h5_file_path(scene_name)

        self.scene = scene_name

        self.terminal_state = terminal_state

        self.h5_file = h5py.File(h5_file_path, 'r')

        self.n_feat_per_location = n_feat_per_location

        self.history_length = history_length

        self.locations = self.h5_file['location'][()]
        self.rotations = self.h5_file['rotation'][()]

        self.n_locations = self.locations.shape[0]

        self.transition_graph = self.h5_file['graph'][()]

        self.action_size = action_size

        self.method = method
        self.reward_fun = reward

        self.object_ids = json.loads(self.h5_file.attrs['object_ids'])
        object_feature = self.h5_file['object_feature']
        self.object_vector = self.h5_file['object_vector']

        self.bbox_area = 0
        self.max_bbox_area = 0

        self.time = 0

        # LAST instruction
        if self.method == 'word2vec':
            self.s_target = self.object_vector[self.object_ids[self.terminal_state['object']]]

        elif self.method == 'aop':
            self.s_target = object_feature[self.object_ids[self.terminal_state['object']]]

        elif self.method == 'target_driven':
            # LAST instruction
            terminal_id = None
            for i, loc in enumerate(self.locations):
                if np.array_equal(loc, list(self.terminal_state['position'].values())):
                    if np.array_equal(self.rotations[i], list(self.terminal_state['rotation'].values())):
                        terminal_id = i
                        break
            self.s_target = self._tiled_state(terminal_id)
        else:
            raise Exception('Please choose a method')

        self.mask_size = mask_size

    def reset(self):
        # randomize initial state
        k = random.randrange(self.n_locations)
        while True:
            # Assure that Z value is 0
            if self.rotations[k][2] == 0:
                break
            k = random.randrange(self.n_locations)
        # reset parameters
        self.current_state_id = k
        self.start_state_id = k
        self.s_t = self._tiled_state(self.current_state_id)
        self.collided = False
        self.terminal = False
        self.bbox_area = 0
        self.max_bbox_area = 0
        self.time = 0

    def step(self, action):
        assert not self.terminal, 'step() called in terminal state'
        k = self.current_state_id
        if self.transition_graph[k][action] != -1:
            self.current_state_id = self.transition_graph[k][action]
            agent_pos = self.locations[self.current_state_id]  # NDARRAY
            # Check only y value
            agent_rot = self.rotations[self.current_state_id][1]

            terminal_pos = list(
                self.terminal_state['position'].values())  # NDARRAY
            # Check only y value
            terminal_rot = self.terminal_state['rotation']['y']

            if np.array_equal(agent_pos, terminal_pos) and np.array_equal(agent_rot, terminal_rot):
                self.terminal = True
                self.collided = False
            else:
                self.terminal = False
                self.collided = False
        else:
            self.terminal = False
            self.collided = True

        self.s_t = np.append(self.s_t[:, 1:], self._get_state(
            self.current_state_id), axis=1)

        # Retrieve bounding box area of target object class
        self.bbox_area = self._get_max_bbox_area(
            self.boudingbox, self.terminal_state['object'])

        self.time = self.time + 1

    def _get_state(self, state_id):
        # read from hdf5 cache
        k = random.randrange(self.n_feat_per_location)
        return self.h5_file['resnet_feature'][state_id][k][:, np.newaxis]

    def _tiled_state(self, state_id):
        f = self._get_state(state_id)
        return np.tile(f, (1, self.history_length))

    def _get_max_bbox_area(self, bboxs, obj_class):
        area = 0
        for key, value in bboxs.items():
            keys = key.split('|')
            if keys[0] == obj_class:
                w = abs(value[0] - value[2])
                h = abs(value[1] + value[3])
                area = max(area, w * h)
        return area

    def _calculate_bbox_reward(self, bbox_area, max_bbox_area):
        if bbox_area > max_bbox_area:
            return bbox_area
        else:
            return 0

    def _downsample_bbox(self, input_shape, output_shape, input_bbox):
        h, w = input_shape
        out_h, out_w = output_shape
        # Between 0 and output_shape
        out_h = out_h
        out_w = out_w

        ratio_h = out_h / h
        ratio_w = out_w / w

        output = np.zeros(output_shape, dtype=np.float32)

        for i_bbox in input_bbox:
            bbox_xy, similarity = i_bbox
            x, y = bbox_xy
            out_x = int(x * ratio_w)
            out_y = int(y * ratio_h)
            output[out_x, out_y] = max(output[out_x, out_y], similarity)
        return output

    @property
    def reward(self):
        if self.reward_fun == 'bbox':
            reward_ = self._calculate_bbox_reward(
                self.bbox_area, self.max_bbox_area)

            if reward_ != 0:
                self.max_bbox_area = reward_
            return reward_

        elif self.reward_fun == 'step':
            return 10.0 if self.terminal else -0.01

    @property
    def is_terminal(self):
        return self.terminal or self.time >= 5e3

    @property
    def observation(self):
        return self.h5_file['observation'][self.current_state_id]

    @property
    def boudingbox(self):
        return json.loads(self.h5_file['bbox'][self.current_state_id])

    def render(self, mode):
        assert mode == 'resnet_features'
        return self.s_t

    def render_target(self, mode):
        if self.method == 'aop' or self.method == 'word2vec':
            assert mode == 'word_features'
            return self.s_target
        elif self.method == 'target_driven':
            assert mode == 'resnet_features'
            return self.s_target

    def render_mask_similarity(self):
        # Get shape of observation to downsample bbox location
        h, w, _ = np.shape(self.h5_file['observation'][0])

        bbox_location = []
        for key, value in self.boudingbox.items():
            keys = key.split('|')
            # Add bounding box if its the target object
            # if keys[0] == self.terminal_state['object']:
            # value[0] = start_x
            # value[2] = end_x
            x = value[0] + value[2]
            x = x/2

            # value[1] = start_y
            # value[3] = end_y
            y = value[1] + value[3]
            y = y/2

            curr_obj_id = self.object_ids[keys[0]]
            similarity = 1 - spatial.distance.cosine(
                self.s_target, self.object_vector[curr_obj_id])
            # for x in range(value[0], value[2], 1):
            #     for y in range(value[1], value[3], 1):
            bbox_location.append(((x, y), similarity))
        try:
            output = self._downsample_bbox(
                (h, w), (self.mask_size, self.mask_size), bbox_location)
        except IndexError as e:
            print((h, w), bbox_location)
            raise e
        return output[np.newaxis, np.newaxis, ...]

    def render_mask(self):
        # Get shape of observation to downsample bbox location
        h, w, _ = np.shape(self.h5_file['observation'][0])

        bbox_location = []
        for key, value in self.boudingbox.items():
            keys = key.split('|')
            if keys[0] == self.terminal_state['object']:
                # Add bounding box if its the target object
                # if keys[0] == self.terminal_state['object']:
                # value[0] = start_x
                # value[2] = end_x
                x = value[0] + value[2]
                x = x/2

                # value[1] = start_y
                # value[3] = end_y
                y = value[1] + value[3]
                y = y/2
                bbox_location.append(((x, y), 1))
        try:
            output = self._downsample_bbox(
                (h, w), (self.mask_size, self.mask_size), bbox_location)
        except IndexError as e:
            print((h, w), bbox_location)
            raise e
        return output

    @property
    def actions(self):
        return self.acts[: self.action_size]

    def stop(self):
        pass
