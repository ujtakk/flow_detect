#!/usr/bin/env python3

import os
from os.path import join, exists, basename
import re
import sys

import argparse
import subprocess

import cv2
import numpy as np
import tqdm

FLOW_CMD = join("mpegflow", "mpegflow")
VIS_CMD = join("mpegflow", "vis")

def dump_flow(movie, occupancy=False):
    flow_dir = join(movie, "mpegflow_dump")
    if not exists(flow_dir):
        os.makedirs(flow_dir)

    vis_dir = join(movie, "vis_dump")
    if not exists(vis_dir):
        os.makedirs(vis_dir)

    movie_name = join(movie, basename(movie))
    if not exists(movie_name+".avi"):
        if exists(movie_name+".mp4"):
            subprocess.run(f"ffmpeg -y -i {movie_name+'.mp4'} {movie_name+'.avi'}", shell=True)
        else:
            raise Exception("source movie doesn't exist.")
    movie_file = movie_name + ".avi"

    # extract motion vectors
    flow_base = join(flow_dir, basename(movie))
    subprocess.run(f"{FLOW_CMD} {movie_file} > {flow_base+'.txt'}",
                    shell=True)

    # visualize motion vectors
    subprocess.run(f"{FLOW_CMD} {movie_file} | {VIS_CMD} {movie_file} {vis_dir}",
                    shell=True)

    # visualize motion vectors and occupancy info
    if occupancy:
        occu_dir = join(movie, "vis_dump_occupancy")
        os.makedirs(occu_dir)

        subprocess.run(f"{FLOW_CMD} --occupancy {movie_file} | {VIS_CMD} --occupancy {movie_file} {occu_dir}",
                        shell=True)

def pick_flow(movie):
    flow_dir = join(movie, "mpegflow_dump")
    flow_base = join(flow_dir, basename(movie))

    header = r"# pts=(\d+) frame_index=(\d+) pict_type=([IPB]) " \
           + r"output_type=(\w+) shape=(\w+) origin=(\w+)"
    string = open(flow_base+".txt").readline().strip()
    H = re.match(header, string)

    pts = int(H.group(1))
    frame_index = int(H.group(2))
    pict_type = H.group(3)
    output_type = H.group(4)
    shape = tuple(map(int, H.group(5).split('x')))
    origin = H.group(6)

    data = np.loadtxt(flow_base+".txt") \
             .reshape((-1, 2, shape[0]//2, shape[1]))
    data = np.moveaxis(data, 1, 3)

    return data

def flow(movie, occupancy=False):
    dump_flow(movie, occupancy)
    flow = pick_flow(movie)

    return flow

def draw_arrow(frame, start, end, len=2.0, alpha=20.0,
               line_color=(0, 0, 255), start_color=(0, 255, 0)):
    cv2.line(frame, start, end, line_color, 2)
    return frame

def draw_flow(frame, flow):
    frame_rows = frame.shape[0]
    frame_cols = frame.shape[1]
    assert(frame.shape[2] == 3)

    rows = flow.shape[0]
    cols = flow.shape[1]
    assert(flow.shape[2] == 2)

    for i in range(rows):
        for j in range(cols):
            dx = flow[i, j, 0]
            dy = flow[i, j, 1]

            start = (j * frame_cols / cols + frame_cols / cols / 2,
                     i * frame_rows / rows + frame_rows / rows / 2)
            start = tuple(map(int, start))

            end = (start[0] + dx, start[1] + dy)
            end = tuple(map(int, end))

            frame = draw_arrow(frame, start, end)

    return frame

def vis_flow(movie, flow, draw=draw_flow):
    movie_name = join(movie, basename(movie))
    if not exists(movie_name+".mp4"):
        if exists(movie_name+".avi"):
            subprocess.run(
                f"ffmpeg -y -i {movie_name+'.avi'} {movie_name+'.mp4'}",
                shell=True)
        else:
            raise Exception("source movie doesn't exist.")
    movie_file = join(movie, basename(movie)) + ".mp4"

    cap = cv2.VideoCapture(movie_file)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    if exists("out.mp4"):
        os.remove("out.mp4")
    fourcc = cv2.VideoWriter_fourcc(*"avc1")
    out = cv2.VideoWriter("out.mp4", fourcc, fps, (width, height))

    for i in tqdm.tqdm(range(flow.shape[0])):
        ret, frame = cap.read()
        if ret is True:
            frame_drawed = draw(frame, flow[i])
            out.write(frame_drawed)
        else:
            break

    cap.release()
    out.release()

def parseopt():
    parser = argparse.ArgumentParser(
        description="script for extracting motion vectors")
    parser.add_argument("movie",
                        default="mpi_sinel_final_alley_1",
                        help="source movie dir to extract motion vectors")
    parser.add_argument("--occupancy", "-o",
                        action="store_true", default=False,
                        help="dump occupancy enabled version")
    return parser.parse_args()

def main():
    args = parseopt()
    dump_flow(args.movie, args.occupancy)
    flow = pick_flow(args.movie)
    vis_flow(args.movie, flow)

if __name__ == "__main__":
    main()
