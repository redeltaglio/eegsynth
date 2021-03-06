#!/usr/bin/env python

# Lsl2ft reads data from an LSL stream and writes it to a FieldTrip buffer
#
# This software is part of the EEGsynth project, see https://github.com/eegsynth/eegsynth
#
# Copyright (C) 2019 EEGsynth project
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import configparser
import argparse
import numpy as np
import os
import redis
import sys
import time
import pylsl as lsl

if hasattr(sys, 'frozen'):
    basis = sys.executable
elif sys.argv[0] != '':
    basis = sys.argv[0]
else:
    basis = './'
installed_folder = os.path.split(basis)[0]

# eegsynth/lib contains shared modules
sys.path.insert(0, os.path.join(installed_folder, '../../lib'))
import EEGsynth
import FieldTrip

parser = argparse.ArgumentParser()
parser.add_argument("-i", "--inifile", default=os.path.join(installed_folder,
                                                            os.path.splitext(os.path.basename(__file__))[0] + '.ini'), help="optional name of the configuration file")
args = parser.parse_args()

config = configparser.ConfigParser(inline_comment_prefixes=('#', ';'))
config.read(args.inifile)

try:
    r = redis.StrictRedis(host=config.get('redis', 'hostname'), port=config.getint('redis', 'port'), db=0)
    response = r.client_list()
except redis.ConnectionError:
    print("Error: cannot connect to redis server")
    exit()

# combine the patching from the configuration file and Redis
patch = EEGsynth.patch(config, r)
del config

# this determines how much debugging information gets printed
debug    = patch.getint('general', 'debug')
delay    = patch.getint('general', 'delay')
lsl_name = patch.getstring('lsl', 'name')
lsl_type = patch.getstring('lsl', 'type')

try:
    ftc_host = patch.getstring('fieldtrip', 'hostname')
    ftc_port = patch.getint('fieldtrip', 'port')
    if debug > 0:
        print('Trying to connect to buffer on %s:%i ...' % (ftc_host, ftc_port))
    ft_output = FieldTrip.Client()
    ft_output.connect(ftc_host, ftc_port)
    if debug > 0:
        print("Connected to output FieldTrip buffer")
except:
    print("Error: cannot connect to output FieldTrip buffer")
    exit()

# first resolve an EEG stream on the lab network
print("looking for an LSL stream...")
streams = lsl.resolve_streams()
selected = []

for stream in streams:
    inlet           = lsl.StreamInlet(stream)
    name            = inlet.info().name()
    type            = inlet.info().type()
    channel_count   = inlet.info().channel_count()
    nominal_srate   = inlet.info().nominal_srate()
    channel_format  = inlet.info().channel_format()
    source_id       = inlet.info().source_id()
    # determine whether this stream should be further processed
    match = True
    if len(lsl_name):
        match = match and lsl_name==name
    if len(lsl_type):
        match = match and lsl_type==type
    if match:
        # select this stream for further processing
        selected.append(stream)
        print('-------- STREAM(*) ------')
    else:
        print('-------- STREAM ---------')
    if debug>0:
        print("name", name)
        print("type", type)
        print("channel_count", channel_count)
        print("nominal_srate", nominal_srate)
        print("channel_format", channel_format)
        print("source_id", source_id)
    print('-------------------------')

# create a new inlet from the first (and probably only) selected stream
inlet = lsl.StreamInlet(selected[0])
channel_count = inlet.info().channel_count()
nominal_srate = inlet.info().nominal_srate()

ft_output.putHeader(channel_count, nominal_srate, FieldTrip.DATATYPE_FLOAT32)

# this is used for feedback
start = time.time()
count = 0

print("STARTING STREAM")
while True:
    chunk, timestamps = inlet.pull_chunk()
    if timestamps:
        dat = np.asarray(chunk, dtype=np.float32)
        count += dat.shape[0]
        ft_output.putData(dat)
        if debug>0 and (start-time.time())>delay:
            print("processed %d samples" % count)
            start = time.time()
