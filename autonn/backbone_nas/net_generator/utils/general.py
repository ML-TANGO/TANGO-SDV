# References:
# [1] YOLOv5 🚀 by Ultralytics, GPL-3.0 license
'''
utils from yolo code
'''

import contextlib
import logging
import math
import os
import platform
import signal
import socket
import threading
import time
from itertools import repeat
from multiprocessing.pool import ThreadPool
from pathlib import Path
from zipfile import ZipFile

import cv2
import numpy as np
import pandas as pd
import pkg_resources as pkg
import torch
import torchvision
import yaml

from .metrics import box_iou

# Path on Current abs. dir.
PATHA = os.path.dirname(os.path.abspath(__file__))
# Path on backboneNAS
BASEPATH = Path(PATHA).parent

RANK = int(os.environ.get('RANK', -1))

# Settings
DATASETS_DIR = BASEPATH
# number of YOLOv5 multiprocessing threads
NUM_THREADS = min(8, max(1, os.cpu_count() - 1))
AUTOINSTALL = str(os.environ.get('YOLOv5_AUTOINSTALL', True)
                  ).lower() == 'true'  # global auto-install mode
VERBOSE = str(os.environ.get('YOLOv5_VERBOSE', True)
              ).lower() == 'true'  # global verbose mode
FONT = 'Arial.ttf'  # https://ultralytics.com/assets/Arial.ttf

torch.set_printoptions(linewidth=320, precision=5, profile='long')
# format short g, %precision=5
np.set_printoptions(linewidth=320, formatter={'float_kind': '{:11.5g}'.format})
pd.options.display.max_columns = 10
# prevent OpenCV from multithreading (incompatible with PyTorch DataLoader)
cv2.setNumThreads(0)
os.environ['NUMEXPR_MAX_THREADS'] = str(NUM_THREADS)  # NumExpr max threads
# OpenMP max threads (PyTorch and SciPy)
os.environ['OMP_NUM_THREADS'] = str(NUM_THREADS)


def emojis(_str=''):
    '''
    Return platform-dependent emoji-safe version of string
    '''
    return (_str.encode().decode('ascii', 'ignore')
            if platform.system() == 'Windows' else _str)


def xyxy2xywh(_x):
    '''
    Convert nx4 boxes from [x1, y1, x2, y2]
    to [x, y, w, h] where xy1=top-left, xy2=bottom-right
    '''
    _y = _x.clone() if isinstance(_x, torch.Tensor) else np.copy(_x)
    _y[:, 0] = (_x[:, 0] + _x[:, 2]) / 2  # x center
    _y[:, 1] = (_x[:, 1] + _x[:, 3]) / 2  # y center
    _y[:, 2] = _x[:, 2] - _x[:, 0]  # width
    _y[:, 3] = _x[:, 3] - _x[:, 1]  # height
    return _y


def xywh2xyxy(_x):
    '''
    Convert nx4 boxes from [x, y, w, h] to [x1, y1, x2, y2]
    where xy1=top-left, xy2=bottom-right
    '''
    _y = _x.clone() if isinstance(_x, torch.Tensor) else np.copy(_x)
    _y[:, 0] = _x[:, 0] - _x[:, 2] / 2  # top left x
    _y[:, 1] = _x[:, 1] - _x[:, 3] / 2  # top left y
    _y[:, 2] = _x[:, 0] + _x[:, 2] / 2  # bottom right x
    _y[:, 3] = _x[:, 1] + _x[:, 3] / 2  # bottom right y
    return _y


def xywhn2xyxy(_x, _w=640, _h=640, padw=0, padh=0):
    '''
    Convert nx4 boxes from [x, y, w, h] normalized
    to [x1, y1, x2, y2] where xy1=top-left, xy2=bottom-right
    '''
    _y = _x.clone() if isinstance(_x, torch.Tensor) else np.copy(_x)
    _y[:, 0] = _w * (_x[:, 0] - _x[:, 2] / 2) + padw  # top left x
    _y[:, 1] = _h * (_x[:, 1] - _x[:, 3] / 2) + padh  # top left y
    _y[:, 2] = _w * (_x[:, 0] + _x[:, 2] / 2) + padw  # bottom right x
    _y[:, 3] = _h * (_x[:, 1] + _x[:, 3] / 2) + padh  # bottom right y
    return _y


def clip_coords(boxes, shape):
    '''
    Clip bounding xyxy bounding boxes to image shape (height, width)
    '''
    if isinstance(boxes, torch.Tensor):  # faster individually
        boxes[:, 0].clamp_(0, shape[1])  # x1
        boxes[:, 1].clamp_(0, shape[0])  # y1
        boxes[:, 2].clamp_(0, shape[1])  # x2
        boxes[:, 3].clamp_(0, shape[0])  # y2
    else:  # np.array (faster grouped)
        boxes[:, [0, 2]] = boxes[:, [0, 2]].clip(0, shape[1])  # x1, x2
        boxes[:, [1, 3]] = boxes[:, [1, 3]].clip(0, shape[0])  # y1, y2


def xyxy2xywhn(_x, _w=640, _h=640, clip=False, eps=0.0):
    '''
    Convert nx4 boxes from [x1, y1, x2, y2] to [x, y, w, h]
    normalized where xy1=top-left, xy2=bottom-right
    '''
    if clip:
        clip_coords(_x, (_h - eps, _w - eps))  # warning: inplace clip
    _y = _x.clone() if isinstance(_x, torch.Tensor) else np.copy(_x)
    _y[:, 0] = ((_x[:, 0] + _x[:, 2]) / 2) / _w  # x center
    _y[:, 1] = ((_x[:, 1] + _x[:, 3]) / 2) / _h  # y center
    _y[:, 2] = (_x[:, 2] - _x[:, 0]) / _w  # width
    _y[:, 3] = (_x[:, 3] - _x[:, 1]) / _h  # height
    return _y


def xyn2xy(_x, _w=640, _h=640, padw=0, padh=0):
    '''
    Convert normalized segments into pixel segments, shape (n,2)
    '''
    _y = _x.clone() if isinstance(_x, torch.Tensor) else np.copy(_x)
    _y[:, 0] = _w * _x[:, 0] + padw  # top left x
    _y[:, 1] = _h * _x[:, 1] + padh  # top left y
    return _y


def segment2box(segment, width=640, height=640):
    '''
    Convert 1 segment label to 1 box label,
    applying inside-image constraint,
    i.e. (xy1, xy2, ...) to (xyxy)
    '''
    _x, _y = segment.T  # segment xy
    inside = (_x >= 0) & (_y >= 0) & (_x <= width) & (_y <= height)
    _x, _y, = _x[inside], _y[inside]
    # xyxy
    return (np.array([_x.min(), _y.min(), _x.max(), _y.max()])
            if any(_x) else np.zeros((1, 4)))


def segments2boxes(segments):
    '''
    Convert segment labels to box labels,
    i.e. (cls, xy1, xy2, ...) to (cls, xywh)
    '''
    boxes = []
    for _s in segments:
        _x, _y = _s.T  # segment xy
        boxes.append([_x.min(), _y.min(), _x.max(), _y.max()])  # cls, xyxy
    return xyxy2xywh(np.array(boxes))  # cls, xywh


def resample_segments(segments, _n=1000):
    '''
    Up-sample an (n,2) segment
    '''
    for i, _s in enumerate(segments):
        _x = np.linspace(0, len(_s) - 1, _n)
        _xp = np.arange(len(_s))
        segments[i] = np.concatenate(
            [np.interp(_x, _xp, _s[:, i])
             for i in range(2)]).reshape(2, -1).T  # segment xy
    return segments


def is_writeable(dirt, test=False):
    '''
    Return True if directory has write permissions,
    test opening a file with write permissions if test=True
    '''
    if not test:
        return os.access(dirt, os.R_OK)  # possible issues on Windows
    file = Path(dirt) / 'tmp.txt'
    try:
        with open(file, 'w'):  # open file with write permissions
            pass
        file.unlink()  # remove file
        return True
    except OSError:
        return False


def is_ascii(_s=''):
    '''
    Is string composed of all ASCII (no UTF) characters?
    (note str().isascii() introduced in python 3.7)
    '''
    _s = str(_s)  # convert list, tuple, None, etc. to str
    return len(_s.encode().decode('ascii', 'ignore')) == len(_s)


def make_divisible(_x, divisor):
    '''
    Returns nearest x divisible by divisor
    '''
    if isinstance(divisor, torch.Tensor):
        divisor = int(divisor.max())  # to int
    return math.ceil(_x / divisor) * divisor


def set_logging(name=None, verbose=VERBOSE):
    '''
    Sets level and returns logger
    '''
    # rank in world for Multi-GPU trainings
    rank = int(os.environ.get('RANK', -1))
    level = logging.INFO if verbose and rank in {-1, 0} else logging.WARNING
    log = logging.getLogger(name)
    log.setLevel(level)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.setLevel(level)
    log.addHandler(handler)


set_logging()  # run before defining LOGGER
# define globally (used in train.py, val.py, detect.py, etc.)
LOGGER = logging.getLogger("yolov5")


def intersect_dicts(_da, _db, exclude=()):
    '''
    Dictionary intersection of matching keys and shapes,
    omitting 'exclude' keys, using da values
    '''
    return {k: v for k, v in _da.items()
            if ((k in _db and
                 not any(x in k for x in exclude) and
                 v.shape == _db[k].shape))}


# def colorstr(*input):
#     '''
#     Colors a string https://en.wikipedia.org/wiki/ANSI_escape_code,
#     i.e.  colorstr('blue', 'hello world')
#     '''
#     *args, string = input if len(input) > 1 else ('blue', 'bold', input[0])
#     colors = {
#         'black': '\033[30m',  # basic colors
#         'red': '\033[31m',
#         'green': '\033[32m',
#         'yellow': '\033[33m',
#         'blue': '\033[34m',
#         'magenta': '\033[35m',
#         'cyan': '\033[36m',
#         'white': '\033[37m',
#         'bright_black': '\033[90m',  # bright colors
#         'bright_red': '\033[91m',
#         'bright_green': '\033[92m',
#         'bright_yellow': '\033[93m',
#         'bright_blue': '\033[94m',
#         'bright_magenta': '\033[95m',
#         'bright_cyan': '\033[96m',
#         'bright_white': '\033[97m',
#         'end': '\033[0m',  # misc
#         'bold': '\033[1m',
#         'underline': '\033[4m'}
#     return ''.join(colors[x] for x in args) + f'{string}' + colors['end']


# def print_args(args: Optional[dict] = None, show_file=True, show_fcn=False):
#     '''
#     Print function arguments (optional args dict)
#     '''
#     _x = inspect.currentframe().f_back  # previous frame
#     file, _, fcn, _, _ = inspect.getframeinfo(_x)
#     if args is None:  # get args automatically
#         args, _, _, frm = inspect.getargvalues(_x)
#         args = {k: v for k, v in frm.items() if k in args}
#     _s = (f'{Path(file).stem}: ' if show_file else '') + \
#         (f'{fcn}: ' if show_fcn else '')
#     LOGGER.info(colorstr(_s) + ', '.join(
#       f'{k}={v}' for k, v in args.items()))


def user_config_dir(dirt='Ultralytics', env_var='YOLOV5_CONFIG_DIR'):
    '''
    Return path of user configuration directory.
    Prefer environment variable if exists.
    Make dir if required.
    '''
    env = os.getenv(env_var)
    if env:
        path = Path(env)  # use environment variable
    else:
        cfg = {'Windows': 'AppData/Roaming', 'Linux': '.config',
               'Darwin': 'Library/Application Support'}  # 3 OS dirs
        # OS-specific config dir
        path = Path.home() / cfg.get(platform.system(), '')
        path = (path if is_writeable(path) else Path('/tmp')) / \
            dirt  # GCP and AWS lambda fix, only /tmp is writeable
    path.mkdir(exist_ok=True)  # make if required
    return path


CONFIG_DIR = user_config_dir()  # Ultralytics settings dir


def check_font(font=FONT, progress=False):
    '''
    Download font to CONFIG_DIR if necessary
    '''
    font = Path(font)
    file = CONFIG_DIR / font.name
    if not font.exists() and not file.exists():
        url = "https://ultralytics.com/assets/" + font.name
        LOGGER.info('Downloading %s to %s...', url, file)
        torch.hub.download_url_to_file(url, str(file), progress=progress)


def check_suffix(file='yolov5s.pt', suffix=('.pt',), msg=''):
    '''
    Check file(s) for acceptable suffix
    '''
    if file and suffix:
        if isinstance(suffix, str):
            suffix = [suffix]
        for _f in file if isinstance(file, (list, tuple)) else [file]:
            _s = Path(_f).suffix.lower()  # file suffix
            if _s:
                assert _s in suffix, f"{msg}{_f} acceptable suffix is {suffix}"


def check_dataset(data, autodownload=True):
    '''
    Download and/or unzip dataset if not found locally
    # Usage: https://github.com/ultralytics/yolov5/\
    # releases/download/v1.0/coco128_with_yaml.zip
    '''
    # Download (optional)
    extract_dir = ''
    # i.e. gs://bucket/dir/coco128.zip
    if isinstance(data, (str, Path)) and str(data).endswith('.zip'):
        download(data, dirt=DATASETS_DIR, unzip=True,
                 delete=False, curl=False, threads=1)
        data = next((DATASETS_DIR / Path(data).stem).rglob('*.yaml'))
        extract_dir, autodownload = data.parent, False

    # Read yaml (optional)
    if isinstance(data, (str, Path)):
        with open(data, errors='ignore') as _f:
            data = yaml.safe_load(_f)  # dictionary

    # Resolve paths
    # optional 'path' default to '.'
    path = Path(extract_dir or data.get('path') or '')
    # if not path.is_absolute():
    #    path = (ROOT / path).resolve()
    for k in 'train', 'val', 'test':
        if data.get(k):  # prepend path
            data[k] = (str(path / data[k])
                       if isinstance(data[k], str)
                       else [str(path / x) for x in data[k]])

    # Parse yaml
    assert 'nc' in data, "Dataset 'nc' key missing."
    if 'names' not in data:
        # assign class names if missing
        data['names'] = [f'class{i}' for i in range(data['nc'])]
    _, val, _, _s = (data.get(x)
                     for x in ('train', 'val', 'test', 'download'))
    if val:
        val = val if isinstance(val, list) else [val]
        val = [Path(x).resolve()
               for x in val]  # val path
        if not all(x.exists() for x in val):
            LOGGER.info(emojis('\nDataset not found ⚠, missing paths %s' % [
                str(x) for x in val if not x.exists()]))
            if not _s or not autodownload:
                raise Exception(emojis('Dataset not found ❌'))
            _t = time.time()
            # unzip directory i.e. '../'
            root = path.parent if 'path' in data else '..'
            if _s.startswith('http') and _s.endswith('.zip'):  # URL
                _f = Path(_s).name  # filename
                LOGGER.info('Downloading %s to %s...', _s, _f)
                torch.hub.download_url_to_file(_s, _f)
                Path(root).mkdir(parents=True, exist_ok=True)  # create root
                ZipFile(_f).extractall(path=root)  # unzip
                Path(_f).unlink()  # remove zip
                _r = None  # success
            elif _s.startswith('bash '):  # bash script
                LOGGER.info('Running %s ...', _s)
                _r = os.system(_s)
            else:  # python script
                # _r = exec(_s, {'yaml': data})  # return None
                _r = None
            _dt = f'({round(time.time() - _t, 1)}s)'
            _s = f"success ✅ {_dt}, saved to {str(root)}" if _r in (
                0, None) else f"failure {_dt} ❌"
            LOGGER.info(emojis(f"Dataset download {_s}"))
    check_font('Arial.ttf'
               if is_ascii(data['names'])
               else 'Arial.Unicode.ttf',
               progress=True)  # download fonts
    return data  # dictionary


def download(url, dirt='.', unzip=True,
             delete=True, curl=False, threads=1, retry=3):
    '''
    Multi-threaded file download and unzip function,
    used in data.yaml for autodownload
    '''
    def download_one(url, dirt):
        '''Download 1 file'''
        success = True
        _f = dirt / Path(url).name  # filename
        if Path(url).is_file():  # exists in current path
            Path(url).rename(_f)  # move to dir
        elif not _f.exists():
            LOGGER.info('Downloading %s to %s...', url, _f)
            for i in range(retry + 1):
                if curl:
                    _s = 'sS' if threads > 1 else ''  # silent
                    # curl download with retry, continue
                    _r = os.system(
                        f'curl -{_s}L "{url}" -o "{_f}" --retry 9 -C -')
                    success = _r == 0
                else:
                    torch.hub.download_url_to_file(
                        url, _f, progress=threads == 1)  # torch download
                    success = _f.is_file()
                if success:
                    break
                if i < retry:
                    LOGGER.warning(
                        'Download failure, retrying %s/%s %s...',
                        i+1, retry, url)
                else:
                    LOGGER.warning('Failed to download %s...', url)

        if unzip and success and _f.suffix in ('.zip', '.gz'):
            LOGGER.info('Unzipping %s...', _f)
            if _f.suffix == '.zip':
                ZipFile(_f).extractall(path=dirt)  # unzip
            elif _f.suffix == '.gz':
                os.system(f'tar xfz {_f} --directory {_f.parent}')  # unzip
            if delete:
                _f.unlink()  # remove zip

    dirt = Path(dirt)
    dirt.mkdir(parents=True, exist_ok=True)  # make directory
    if threads > 1:
        pool = ThreadPool(threads)
        pool.imap(lambda x: download_one(*x),
                  zip(url, repeat(dirt)))  # multi-threaded
        pool.close()
        pool.join()
    else:
        for _u in [url] if isinstance(url, (str, Path)) else url:
            download_one(_u, dirt)

def check_img_size(imgsz, _s=32, floor=0):
    '''
    Verify image size is a multiple of stride s in each dimension
    '''
    if isinstance(imgsz, int):  # integer i.e. img_size=640
        new_size = max(make_divisible(imgsz, int(_s)), floor)
    else:  # list i.e. img_size=[640, 480]
        imgsz = list(imgsz)  # convert to list if tuple
        new_size = [max(make_divisible(x, int(_s)), floor) for x in imgsz]
    if new_size != imgsz:
        LOGGER.warning(
            'WARNING: --img-size %s must be \
                multiple of max stride %s, updating to %s',
            imgsz, _s, new_size)
    return new_size

def labels_to_class_weights(labels, _nc=80):
    '''
    Get class weights (inverse frequency) from training labels
    '''
    if labels[0] is None:  # no labels loaded
        return torch.Tensor()

    labels = np.concatenate(labels, 0)  # labels.shape = (866643, 5) for COCO
    classes = labels[:, 0].astype(np.int)  # labels = [class xywh]
    weights = np.bincount(classes, minlength=_nc)  # occurrences per class

    # replace empty bins with 1
    _weights = []
    for _w in weights:
        if _w == 0:
            _weights.append(1)
        else:
            _weights.append(_w)
    weights = np.array(_weights).astype(np.int)
    weights = 1 / weights  # number of targets per class
    weights /= weights.sum()  # normalize
    return torch.from_numpy(weights)


def scale_coords(img1_shape, coords, img0_shape, ratio_pad=None):
    '''
    Rescale coords (xyxy) from img1_shape to img0_shape
    '''
    if ratio_pad is None:  # calculate from img0_shape
        gain = min(img1_shape[0] / img0_shape[0],
                   img1_shape[1] / img0_shape[1])  # gain  = old / new
        pad = (img1_shape[1] - img0_shape[1] * gain) / \
            2, (img1_shape[0] - img0_shape[0] * gain) / 2  # wh padding
    else:
        gain = ratio_pad[0][0]
        pad = ratio_pad[1]

    coords[:, [0, 2]] -= pad[0]  # x padding
    coords[:, [1, 3]] -= pad[1]  # y padding
    coords[:, :4] /= gain
    clip_coords(coords, img0_shape)
    return coords


def non_max_suppression(prediction,
                        conf_thres=0.25,
                        iou_thres=0.45,
                        classes=None,
                        agnostic=False,
                        multi_label=False,
                        labels=(),
                        max_det=300):
    """Non-Maximum Suppression (NMS) on inference results
    to reject overlapping bounding boxes
    Returns:
         list of detections, on (n,6) tensor per image [xyxy, conf, cls]
    """

    _bs = prediction.shape[0]  # batch size
    _nc = prediction.shape[2] - 5  # number of classes
    _xc = prediction[..., 4] > conf_thres  # candidates

    # Checks
    assert 0 <= conf_thres <= 1, f'Invalid Confidence threshold \
        {conf_thres}, valid values are between 0.0 and 1.0'
    assert 0 <= iou_thres <= 1, f'Invalid IoU \
        {iou_thres}, valid values are between 0.0 and 1.0'

    # Settings
    # min_wh = 2  # (pixels) minimum box width and height
    max_wh = 7680  # (pixels) maximum box width and height
    max_nms = 30000  # maximum number of boxes into torchvision.ops.nms()
    time_limit = 0.3 + 0.03 * _bs  # seconds to quit after
    redundant = True  # require redundant detections
    multi_label &= _nc > 1  # multiple labels per box (adds 0.5ms/img)
    merge = False  # use merge-NMS

    _t = time.time()
    output = [torch.zeros((0, 6), device=prediction.device)] * _bs
    for _xi, _x in enumerate(prediction):  # image index, image inference
        # Apply constraints
        # x[((x[..., 2:4] < min_wh) | \
        # (x[..., 2:4] > max_wh)).any(1), 4] = 0  # width-height
        _x = _x[_xc[_xi]]  # confidence

        # Cat apriori labels if autolabelling
        if labels and labels[_xi]:
            _lb = labels[_xi]
            _v = torch.zeros((len(_lb), _nc + 5), device=_x.device)
            _v[:, :4] = _lb[:, 1:5]  # box
            _v[:, 4] = 1.0  # conf
            _v[range(len(_lb)), _lb[:, 0].long() + 5] = 1.0  # cls
            _x = torch.cat((_x, _v), 0)

        # If none remain process next image
        if not _x.shape[0]:
            continue

        # Compute conf
        _x[:, 5:] *= _x[:, 4:5]  # conf = obj_conf * cls_conf

        # Box (center x, center y, width, height) to (x1, y1, x2, y2)
        box = xywh2xyxy(_x[:, :4])

        # Detections matrix nx6 (xyxy, conf, cls)
        if multi_label:
            _i, _j = (_x[:, 5:] > conf_thres).nonzero(as_tuple=False).T
            _x = torch.cat((box[_i], _x[_i, _j + 5, None],
                            _j[:, None].float()), 1)
        else:  # best class only
            conf, _j = _x[:, 5:].max(1, keepdim=True)
            _x = torch.cat((box, conf, _j.float()), 1)[
                conf.view(-1) > conf_thres]

        # Filter by class
        if classes is not None:
            _x = _x[
                (_x[:, 5:6] == torch.Tensor(classes,
                                            device=_x.device)).any(1)]
            print('ch4', _x)

        # Apply finite constraint
        # if not torch.isfinite(x).all():
        #     x = x[torch.isfinite(x).all(1)]

        # Check shape
        _n = _x.shape[0]  # number of boxes
        if not _n:  # no boxes
            continue
        if _n > max_nms:  # excess boxes
            # sort by confidence
            _x = _x[_x[:, 4].argsort(descending=True)[:max_nms]]

        # Batched NMS
        _c = _x[:, 5:6] * (0 if agnostic else max_wh)  # classes
        # boxes (offset by class), scores
        boxes, scores = _x[:, :4] + _c, _x[:, 4]
        _i = torchvision.ops.nms(boxes, scores, iou_thres)  # NMS
        if _i.shape[0] > max_det:  # limit detections
            _i = _i[:max_det]
        # Merge NMS (boxes merged using weighted mean)
        if merge and (1 < _n < 3E3):
            # update boxes as boxes(i,4) = weights(i,n) * boxes(n,4)
            iou = box_iou(boxes[_i], boxes) > iou_thres  # iou matrix
            weights = iou * scores[None]  # box weights
            _x[_i, :4] = torch.mm(weights, _x[:, :4]).float(
            ) / weights.sum(1, keepdim=True)  # merged boxes
            if redundant:
                _i = _i[iou.sum(1) > 1]  # require redundancy

        output[_xi] = _x[_i]
        if (time.time() - _t) > time_limit:
            LOGGER.warning(
                'WARNING: NMS time limit %.3fs exceeded',
                time_limit)
            break  # time limit exceeded

    return output


def increment_path(path, exist_ok=False, sep='', mkdir=False):
    '''
    Increment file or directory path,
    i.e. runs/exp --> runs/exp{sep}2, runs/exp{sep}3, ... etc.
    '''
    path = Path(path)  # os-agnostic
    if path.exists() and not exist_ok:
        path, suffix = (path.with_suffix(
            ''), path.suffix) if path.is_file() else (path, '')

        # Method 1
        for _n in range(2, 9999):
            _p = f'{path}{sep}{_n}{suffix}'  # increment path
            if not os.path.exists(_p):  #
                break
        path = Path(_p)

        # Method 2 (deprecated)
        # dirs = glob.glob(f"{path}{sep}*")  # similar paths
        # matches = [re.search(rf"{path.stem}{sep}(\d+)", d) for d in dirs]
        # i = [int(m.groups()[0]) for m in matches if m]  # indices
        # n = max(i) + 1 if i else 2  # increment number
        # path = Path(f"{path}{sep}{n}{suffix}")  # increment path

    if mkdir:
        path.mkdir(parents=True, exist_ok=True)  # make directory

    return path


class Timeout(contextlib.ContextDecorator):
    '''
    Usage: @Timeout(seconds) decorator or
    'with Timeout(seconds):' context manager
    '''
    def __init__(self, seconds, *, timeout_msg='',
                 suppress_timeout_errors=True):
        """
        __init__
        """
        self.seconds = int(seconds)
        self.timeout_message = timeout_msg
        self.suppress = bool(suppress_timeout_errors)

    def _timeout_handler(self, signum, frame):
        """
        _timeout_handler
        """
        raise TimeoutError(self.timeout_message)

    def __enter__(self):
        """
        __enter__
        """
        if platform.system() != 'Windows':  # not supported on Windows
            # Set handler for SIGALRM
            signal.signal(signal.SIGALRM, self._timeout_handler)
            # start countdown for SIGALRM to be raised
            signal.alarm(self.seconds)

    def __exit__(self, exc_type, exc_val, exc_tb):
        """
        __exit__
        """
        if platform.system() != 'Windows':
            signal.alarm(0)  # Cancel SIGALRM if it's scheduled
            # Suppress TimeoutError
            if self.suppress and exc_type is TimeoutError:
                return True
        return None


def check_version(current='0.0.0', minimum='0.0.0',
                  name='version ', pinned=False,
                  hard=False, verbose=False):
    '''
    Check version vs. required version
    '''
    current, minimum = (pkg.parse_version(x) for x in (current, minimum))
    result = (current == minimum) if pinned else (current >= minimum)  # bool
    # string
    _s = f'{name}{minimum} required by YOLOv5, \
        but {name}{current} is currently installed'
    if hard:
        assert result, _s  # assert min requirements met
    if verbose and not result:
        LOGGER.warning(_s)
    return result


def check_python(minimum='3.7.0'):
    '''
    Check current python version vs. required python version
    '''
    check_version(platform.python_version(),
                  minimum, name='Python ', hard=True)


def threaded(func):
    '''
    Multi-threads a target function and returns thread.
    Usage: @threaded decorator
    '''
    def wrapper(*args, **kwargs):
        '''wrapper'''
        thread = threading.Thread(
            target=func, args=args, kwargs=kwargs, daemon=True)
        thread.start()
        return thread

    return wrapper
