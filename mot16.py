#!/usr/bin/env python

"""Prepare MOT16 dataset for evaluation
"""

import os
import copy
import argparse
import configparser

from glob import glob
from os.path import join, basename, splitext
from subprocess import run
from multiprocessing import Pool

import pandas as pd
import numpy as np

import chainer
from chainercv.utils import read_image

from flow import get_flow, draw_flow
from annotate import pick_bbox, draw_bboxes
from draw import draw_none
from vis import open_video

def convert_seq(path):
    conf = seqinfo(path)

    fps = conf['frameRate'][0]
    name = conf['name'][0]
    ext = conf['imExt'][0]
    run(f"ffmpeg -r {fps} -i {path}/img1/%06d{ext} {path}/{name}.mp4",
        shell=True)

def gtinfo(path):
    """
    1 Frame number
        Indicate at which frame the object is present
    2 Identity number
        Each pedestrian trajectory is identified by a unique ID
        (-1 for detections)
    3 Bounding box left
        Coordinate of the top-left corner of the pedestrian bounding box
    4 Bounding box top
        Coordinate of the top-left corner of the pedestrian bounding box
    5 Bounding box width
        Width in pixels of the pedestrian bounding box
    6 Bounding box height
        Height in pixels of the pedestrian bounding box
    7 Confidence score
        DET: Indicates how confident the detector is that
             this instance is a pedestrian.
        GT: It acts as a flag whether the entry is
            to be considered (1) or ignored (0).
    8 Class
        GT: Indicates the type of object annotated
    9 Visibility
        GT: Visibility ratio, a number between 0 and 1
            that says how much of that object is visible.
            Can be due to occlusion and due to image border cropping.
    """

    det = pd.read_csv(join(path, "gt", "gt.txt"),
                      names=("frame", "identity",
                             "left", "top", "width", "height",
                             "score", "class", "visibility"))

    return det

def detinfo(path, poi=False):
    """
    Note that all values including the bounding box are 1-based,
    i.e. the top left corner corresponds to (1, 1).
    """
    if poi:
        csv_path = join("MOT16_det_feat", basename(path)+"_det.txt")
    else:
        csv_path = join(path, "det", "det.txt")

    det = pd.read_csv(csv_path, usecols=range(7),
                      names=("frame", "identity",
                             "left", "top", "width", "height", "score"))

    return det

def seqinfo(path):
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(join(path, "seqinfo.ini"))
    return pd.DataFrame(dict(config["Sequence"]), index=[0])

def pick_mot16_bboxes(path):
    det = detinfo(path)
    det_frames = det["frame"].unique()
    bboxes = [pd.DataFrame() for _ in np.arange(np.max(det_frames))]

    for frame in det_frames:
        det_entry = det.query(f"frame == {frame}").reset_index()
        left = (det_entry["left"]).astype(np.int)
        top = (det_entry["top"]).astype(np.int)
        right = (det_entry["left"] + det_entry["width"]).astype(np.int)
        bot = (det_entry["top"] + det_entry["height"]).astype(np.int)
        bboxes[frame-1] = pd.DataFrame({
            "name": "",
            "prob": det_entry["score"],
            "left": left, "top": top, "right": right, "bot": bot
        })

    return pd.Series(bboxes)

class MOT16Dataset(chainer.dataset.DatasetMixin):
    class_map = (
        "Pedestrian",
        "Person on vehicle",
        "Car",
        "Bicycle",
        "Motorbike",
        "Non motorized vehicle",
        "Static person",
        "Distractor",
        "Occluder",
        "Occluder on the ground",
        "Occluder full",
        "Reflection",
    )

    color_map = (
        ( -1,  -1,  -1),
        ( 64,   0,   0),
        (  0,  64,   0),
        (  0,   0,  64),
        ( 64,  64,   0),
        ( 64,   0,  64),
        (  0,  64,  64),
        (192,   0,   0),
        (  0, 192,   0),
        (  0,   0, 192),
        (192, 192,   0),
        (192,   0, 192),
        (  0, 192, 192),
    )

    data_split = {
        "train": ("train", (
            "MOT16-02", "MOT16-04", "MOT16-05", "MOT16-11", "MOT16-13",
        )),
        "val": ("train", (
            "MOT16-09", "MOT16-10",
        )),
        "trainval": ("train", (
            "MOT16-02", "MOT16-04", "MOT16-05", "MOT16-09", "MOT16-10",
            "MOT16-11", "MOT16-13",
        )),
        "test": ("test", (
            "MOT16-01", "MOT16-03", "MOT16-06", "MOT16-07", "MOT16-08",
            "MOT16-12", "MOT16-14",
        )),
    }

    def __init__(self, data_dir, split='train'):
        if not split in ("train", "val", "trainval", "test"):
            KeyError("Specified MOT16Dataset split is not available.")

        split_prefix, split_id = self.data_split[split]
        join_func = lambda id_: join(data_dir, split_prefix, id_)
        split_paths = tuple(map(join_func, split_id))

        self.seqinfo = pd.concat([seqinfo(path)
                                  for path in split_paths])
        self.gtinfo = {basename(path): gtinfo(path)
                       for path in split_paths}
        self.imgs = [name
                     for path in split_paths
                     for name in glob(join(path, "img1", "*"))]

        # self.seqinfo = pd.concat([seqinfo(path)
        #                           for path in glob(join(data_dir, split, "*"))])
        # self.gtinfo = {basename(path): gtinfo(path)
        #                for path in glob(join(data_dir, split, "*"))}
        # self.imgs = [name
        #              for name in glob(join(data_dir, split, "*", "img1", "*"))]

    def __len__(self):
        return len(self.imgs)

    def get_example(self, i):
        img_file = self.imgs[i]
        id_ = int(splitext(img_file.split(os.sep)[-1])[0])
        dir_ = img_file.split(os.sep)[-3]

        annos = self.gtinfo[dir_].query(f"frame == {id_} and score != 0")
        label = (np.asarray(annos["class"]) - 1).astype(np.int32)

        left = np.asarray(annos["left"])
        top = np.asarray(annos["top"])
        width = np.asarray(annos["width"])
        height = np.asarray(annos["height"])

        left[left < 0] = 0
        top[top < 0] = 0
        width[width < 0] = 0
        height[height < 0] = 0

        xmin = left
        ymin = top
        xmax = xmin + width
        ymax = ymin + height
        bbox = np.stack((ymin, xmin, ymax, xmax), axis=-1).astype(np.float32)

        # bbox = np.stack((left, top, width, height), axis=-1).astype(np.float32)

        img = read_image(img_file, color=True)

        return img, bbox, label

class MOT16Transform:
    def __init__(self):
        pass

    def __call__(self, in_data):
        pass

class MOT16Evaluator(chainer.training.extensions.Evaluator):
    def __init__(self, iterator, target):
        super().__init__(iterator, target)

    def evaluate(self):
        pass

def parse_opt():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump",
                        action="store_true", default=True)
    return parser.parse_args()

def main():
    args = parse_opt()

    if args.dump:
        for target in glob("MOT16/train/*"):
            convert_seq(target)
        for target in glob("MOT16/test/*"):
            convert_seq(target)
        # with Pool(8) as p:
        #     p.map(convert_seq, glob("MOT16/train/*"))
        #     p.map(convert_seq, glob("MOT16/test/*"))
    else:
        D = MOT16Dataset("MOT16")
        print(D.seqinfo)
        arglist = [np.sort(D.gtinfo[name]["class"].unique())
                   for name in D.seqinfo["name"].unique()]
        print(arglist)
        print(gtinfo("MOT16/train/MOT16-02"))
        print(detinfo("MOT16/test/MOT16-01"))
        # print(D.imgs)

if __name__ == "__main__":
    main()
