#!/usr/bin/env python3
#
# Copyright 2021 Graviti. Licensed under MIT License.
#

# pylint: disable=wrong-import-position
# pylint: disable=pointless-string-statement

"""This file includes the python code of request_configuration.rst."""


"""Example of request config"""
from tensorbay import GAS
from tensorbay.client import config

# Enlarge timeout and max_retries of configuration.
config.timeout = 40
config.max_retries = 4

# Please visit `https://gas.graviti.cn/tensorbay/developer` to get the AccessKey.
gas = GAS("<YOUR_ACCESSKEY>")

# The configs will apply to all the requests sent by TensorBay SDK.
gas.list_dataset_names()
""""""
