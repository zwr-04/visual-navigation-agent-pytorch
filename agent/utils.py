import json
import math
import os
import re

import GPUtil


def find_restore_point(checkpoint_path, fail=True):
    checkpoint_path = os.path.abspath(checkpoint_path)

    # Find latest checkpoint
    restore_point = None
    if checkpoint_path.find('{checkpoint}') != -1:
        files = os.listdir(os.path.dirname(checkpoint_path))
        base_name = os.path.basename(checkpoint_path)
        regex = re.escape(base_name).replace(
            re.escape('{checkpoint}'), '(\d+)')
        points = [(fname, int(match.group(1))) for (fname, match) in (
            (fname, re.match(regex, fname),) for fname in files) if not match is None]
        if len(points) == 0:
            if fail:
                raise Exception('Restore point not found')
            else:
                return None

        (base_name, restore_point) = max(points, key=lambda x: x[1])
        return (base_name, restore_point)
    else:
        if not os.path.exists(checkpoint_path):
            if fail:
                raise Exception('Restore point not found')
            else:
                return None
        return (checkpoint_path, None)


def populate_config(config, mode='train', checkpoint=True):
    exp_path = config['exp']
    json_file = open(exp_path)
    json_dump = json.load(json_file)
    json_file.close()

    compute_param = json_dump['train_param']
    eval_param = json_dump['eval_param']

    config = {**config, **compute_param}
    config = {**config, **eval_param}

    base_path = os.path.dirname(exp_path) + '/'
    config['base_path'] = base_path
    config['log_path'] = base_path + 'logs'
    if checkpoint:
        config['checkpoint_path'] = base_path + 'checkpoints/{checkpoint}.pth'
    config['h5_file_path'] = json_dump['h5_file_path']
    config['total_step'] = int(json_dump['total_step'])

    if mode == 'train':
        config['task_list'] = json_dump['task_list']['train']
    else:
        config['task_list'] = json_dump['task_list']['eval']
    config['saving_period'] = int(json_dump['saving_period'])
    config['max_t'] = int(json_dump['max_t'])
    config['action_size'] = int(json_dump['action_size'])

    return config


def get_first_free_gpu(memory_needed):
    GPUs = GPUtil.getGPUs()
    # maxLoad = 2 Bypass maxLoad filter
    GPUs_available = GPUtil.getAvailability(
        GPUs, maxLoad=2, maxMemory=0.8, memoryFree=memory_needed)
    GPUs_available = [gpu for i, gpu in enumerate(
        GPUs) if (GPUs_available[i] == 1)]
    if not GPUs_available:
        return None
    GPUs_available.sort(key=lambda x: float('inf') if math.isnan(
        x.memoryUtil) else x.memoryUtil, reverse=True)
    return GPUs_available[0].id
