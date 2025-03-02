#!/usr/bin/env python3
#
# Copyright 2021 Graviti. Licensed under MIT License.
#
# pylint: disable=invalid-name

"""Dataloader of nuScenes dataset."""


import json
import os
from typing import Any, Dict, Iterator, List

from tensorbay.dataset import Data, Frame, FusionDataset, FusionSegment
from tensorbay.geometry import Transform3D
from tensorbay.label import LabeledBox3D
from tensorbay.opendataset._utility.nuScenes import (
    get_info_with_determined_token,
    get_info_with_token,
    get_sensor,
)

DATASET_NAME = "nuScenes"

_ATTRIBUTE_KEYS = {
    "vehicle": "vehicle_motion",
    "cycle": "cycle_rider",
    "pedestrian": "pedestrian_motion",
}


def nuScenes(path: str) -> FusionDataset:
    """`nuScenes <https://www.nuscenes.org/>`_ dataset.

    The file structure should be like::

        <path>
            v1.0-mini/
                maps/
                    36092f0b03a857c6a3403e25b4b7aab3.png
                    ...
                samples/
                    CAM_BACK/
                    CAM_BACK_LEFT/
                    CAM_BACK_RIGHT/
                    CAM_FRONT/
                    CAM_FRONT_LEFT/
                    CAM_FRONT_RIGHT/
                    LIDAR_TOP/
                    RADAR_BACK_LEFT/
                    RADAR_BACK_RIGHT/
                    RADAR_FRONT/
                    RADAR_FRONT_LEFT/
                    RADAR_FRONT_RIGHT/
                sweeps/
                    CAM_BACK/
                    CAM_BACK_LEFT/
                    CAM_BACK_RIGHT/
                    CAM_FRONT/
                    CAM_FRONT_LEFT/
                    CAM_FRONT_RIGHT/
                    LIDAR_TOP/
                    RADAR_BACK_LEFT/
                    RADAR_BACK_RIGHT/
                    RADAR_FRONT/
                    RADAR_FRONT_LEFT/
                    RADAR_FRONT_RIGHT/
                v1.0-mini/
                    attribute.json
                    calibrated_sensor.json
                    category.json
                    ego_pose.json
                    instance.json
                    log.json
                    map.json
                    sample_annotation.json
                    sample_data.json
                    sample.json
                    scene.json
                    sensor.json
                    visibility.json
            v1.0-test/
                maps/
                samples/
                sweeps/
                v1.0-test/
            v1.0-trainval/
                maps/
                samples/
                sweeps/
                v1.0-trainval/

    Arguments:
        path: The root directory of the dataset.

    Returns:
        Loaded :class:`~tensorbay.dataset.dataset.FusionDataset` instance.

    """
    root_path = os.path.abspath(os.path.expanduser(path))

    dataset = FusionDataset(DATASET_NAME)
    dataset.notes.is_continuous = True
    dataset.notes.bin_point_cloud_fields = ["X", "Y", "Z", "Intensity", "Ring"]
    dataset.load_catalog(os.path.join(os.path.dirname(__file__), "catalog.json"))

    for subset in os.listdir(root_path):
        for segment in _generate_segments(root_path, subset):
            dataset.add_segment(segment)

    return dataset


def _generate_segments(root_path: str, subset: str) -> Iterator[FusionSegment]:
    subset_path = os.path.join(root_path, subset)
    is_test = subset.endswith("test")
    annotation_info = _get_annotation_info(os.path.join(subset_path, subset), is_test)

    for scene in annotation_info["scenes"]:
        segment = FusionSegment(f"{subset}-{scene['name']}")
        segment.description = scene["description"]
        current_frame_token = scene["first_sample_token"]
        while current_frame_token:
            _load_frame_and_sensor(
                segment,
                current_frame_token,
                annotation_info,
                subset_path,
                is_test,
            )
            current_frame_token = annotation_info["samples"][current_frame_token]["next"]
        yield segment


def _get_annotation_info(info_path: str, is_test: bool = False) -> Dict[str, Any]:
    annotation_info = {
        "samples": get_info_with_token(info_path, "sample"),
        "frame_data": get_info_with_determined_token(info_path, "sample_data"),
        "calibrated_sensors": get_info_with_token(info_path, "calibrated_sensor"),
        "ego_poses": get_info_with_token(info_path, "ego_pose"),
        "sensor": get_info_with_token(info_path, "sensor"),
    }
    with open(os.path.join(info_path, "scene.json"), encoding="utf-8") as file:
        annotation_info["scenes"] = json.load(file)
    if not is_test:
        annotation_info["sample_annotations"] = get_info_with_determined_token(
            info_path, "sample_annotation", no_key_frame=True
        )
        annotation_info["instance"] = get_info_with_token(info_path, "instance")
        annotation_info["category"] = get_info_with_token(info_path, "category")
        annotation_info["attribute"] = get_info_with_token(info_path, "attribute")
        annotation_info["visibility"] = get_info_with_token(info_path, "visibility")

    return annotation_info


def _load_frame_and_sensor(
    segment: FusionSegment,
    current_frame_token: str,
    annotation_info: Dict[str, Any],
    subset_path: str,
    is_test: bool,
) -> None:
    frame = Frame()
    for sensor_frame in annotation_info["frame_data"][current_frame_token]:
        calibrated_sensor_info = annotation_info["calibrated_sensors"][
            sensor_frame["calibrated_sensor_token"]
        ]
        common_sensor = annotation_info["sensor"][calibrated_sensor_info["sensor_token"]]
        sensor_name = common_sensor["channel"]
        sensor_type = common_sensor["modality"]

        if sensor_name not in segment.sensors:
            segment.sensors.add(get_sensor(sensor_type, sensor_name, calibrated_sensor_info))

        data = Data(
            os.path.join(subset_path, sensor_frame["filename"]),
            timestamp=sensor_frame["timestamp"] / 10 ** 6,
        )

        if not is_test and sensor_type == "lidar":
            data.label.box3d = _get_labels(
                current_frame_token,
                annotation_info["ego_poses"][sensor_frame["ego_pose_token"]],
                segment.sensors[sensor_name].extrinsics,
                annotation_info,
            )

        frame[sensor_name] = data
    segment.append(frame)


def _get_labels(
    current_frame_token: str,
    lidar_ego_pose_info: Dict[str, Any],
    lidar_to_ego: Transform3D,
    annotation_info: Dict[str, Dict[str, Any]],
) -> List[LabeledBox3D]:
    labels = []
    sample_annotations = annotation_info["sample_annotations"]
    if current_frame_token in sample_annotations:
        lidar_ego_pose = Transform3D(
            translation=lidar_ego_pose_info["translation"],
            rotation=lidar_ego_pose_info["rotation"],
        )
        world_to_lidar = (lidar_ego_pose * lidar_to_ego).inverse()
        for instance_annotation in sample_annotations[current_frame_token]:
            labeled_box = _get_labeled_box(instance_annotation, annotation_info)
            labels.append(world_to_lidar * labeled_box)
    return labels


def _get_labeled_box(
    instance_annotation: Dict[str, Any],
    annotation_info: Dict[str, Any],
) -> LabeledBox3D:
    instance = instance_annotation["instance_token"]
    category = annotation_info["category"][annotation_info["instance"][instance]["category_token"]][
        "name"
    ]
    attributes = {}
    for attribute_token in instance_annotation["attribute_tokens"]:
        attribute_full_name = annotation_info["attribute"][attribute_token]["name"]
        key, value = attribute_full_name.rsplit(".", 1)
        attributes[_ATTRIBUTE_KEYS[key]] = value
    attributes["visibility"] = annotation_info["visibility"][
        instance_annotation["visibility_token"]
    ]["level"]

    width, length, height = instance_annotation["size"]
    return LabeledBox3D(
        translation=instance_annotation["translation"],
        rotation=instance_annotation["rotation"],
        size=(length, width, height),
        category=category,
        instance=instance,
        attributes=attributes,
    )
