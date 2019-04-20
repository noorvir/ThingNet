import os
import re
import h5py
import webp
import logging
import tarfile
import numpy as np

from imageio import imread
from utils.dataio import read_pfm
from time import time, gmtime, strftime


def encode_webp(image, quality=100, ret="numpy"):

    pic = webp.WebPPicture.from_numpy(image)
    config = webp.WebPConfig.new(quality=quality)
    buff = pic.encode(config).buffer()

    if ret == 'numpy':
        return np.frombuffer(buff, dtype=np.int8)
    else:
        return buff


def decode_webp(data):
    if type(data) == np.ndarray:
        data = data.tobytes()

    webp_data = webp.WebPData.from_buffer(data)
    np_data = webp_data.decode()

    return np_data


def shift_dataset(dataset):

    if type(dataset) ==  h5py._hl.group.Group or \
            type(dataset) ==  h5py._hl.files.File:

        keys = dataset.keys()

        for key in keys:
            shift_dataset(dataset[key])
    else:
        dataset[0:-1] = dataset[1:]
        dataset.resize(len(dataset) - 1, axis=0)
        logging.info("Shifted data group %s" % dataset.name)
        logging.info("New size %s" % (dataset.shape,))


def tar_to_hdf5(tar_path, hdf5_path, max_size=5000, compression=9):
    """
    Convert tarfile to HDF5 database which allows indexing.
    Parameters
    ----------
    tar_path: str
    hdf5_path: str
    max_size: int
    compression: int

    Returns
    -------

    """
    start_time = time()
    total_datapoints = 0

    with tarfile.open(tar_path, 'r') as archive, \
            h5py.File(hdf5_path, 'w') as h5f:

        datasets = {}

        while True:
            member = archive.next()

            if member is None:
                break

            name = member.name
            substring, suffix = os.path.splitext(name)

            if suffix == "":
                continue

            data = archive.extractfile(member)
            dataset_name = re.split('\d+(?=\.)', name)[0]
            datapoint_idx = int(re.search('\d+(?=\.)', name).group(0)) - 1

            if suffix == '.pfm':
                data, scale = read_pfm(data)
            elif suffix == '.webp':
                data = data.read()
                data = np.frombuffer(data, dtype=np.int8)
                compression = 0
            else:
                data = imread(data.read())

            # If first image in group, create new data-set
            if dataset_name not in datasets:

                if suffix == '.webp':
                    data_shape = ()
                    data_type = h5py.special_dtype(vlen=data.dtype)
                else:
                    data_shape = data.shape
                    data_type = data.dtype

                shape = (max_size,) + data_shape
                chunk_shape = (1,) + data_shape
                logging.info("Creating subgroup: %s of shape: %s \n\n"
                             % (dataset_name, (shape,)))
                datasets[dataset_name] = [h5f.create_dataset(dataset_name,
                                                             shape,
                                                             chunks=chunk_shape,
                                                             compression='gzip',
                                                             compression_opts=compression,
                                                             dtype=data_type),
                                          0]
                datasets[dataset_name][0].attrs['format'] = suffix

            # Get index into dataset
            dataset, max_idx = datasets[dataset_name]
            dataset[datapoint_idx] = data

            # Update the max data index seen so far for pruning later
            datasets[dataset_name][1] = datapoint_idx if datapoint_idx > max_idx else max_idx
            total_datapoints += 1

            if total_datapoints % 100 == 0:
                logging.info("Processing datapoint number %d.\n" % total_datapoints)

        # Prune
        for key, val in datasets.items():
            dataset, max_idx = val
            datasets[key] = dataset.resize(max_idx + 1, axis=0)
            logging.info("Pruned dataset %s to size %d points.\n" % (key, max_idx + 1))

    end_time = time() - start_time
    logging.info("\n\n*****Finished converting tarfile to HDF5 dataset*****\n\n"
                 "HDF5 file saved at: %s\n"
                 "Tar to HDF5 conversion done in %s" %
                 (hdf5_path, strftime("%H:%M:%S", gmtime(end_time))))

