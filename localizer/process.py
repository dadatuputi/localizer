import csv
import logging
import os
import time
from multiprocessing import Pool

import pyshark
from tqdm import tqdm

from localizer import capture

module_logger = logging.getLogger('localizer.capture')


def process_capture(meta_tuple):

    # Unpack tuple - required for tqdm imap
    path, meta_file = meta_tuple

    with open(os.path.join(path, meta_file), 'rt') as meta_csv:
        _meta_reader = csv.DictReader(meta_csv, dialect='unix')
        meta = next(_meta_reader)

    _beacon_count = 0
    _beacon_failures = 0

    # Fix any absolute paths in meta
    meta[capture._meta_csv_fieldnames[14]] = os.path.split(meta[capture._meta_csv_fieldnames[14]])[1]
    meta[capture._meta_csv_fieldnames[15]] = os.path.split(meta[capture._meta_csv_fieldnames[15]])[1]
    meta[capture._meta_csv_fieldnames[16]] = os.path.split(meta[capture._meta_csv_fieldnames[16]])[1]

    _results_path = os.path.join(path, time.strftime('%Y%m%d-%H-%M-%S') + "-results" + ".csv")

    module_logger.info("Processing capture (meta: {})".format(str(meta)))

    # Build CSV of beacons from pcap and antenna_results
    try:
        with open(_results_path, 'w', newline='') as results_csv:

            # Read pcapng
            _pcap = os.path.join(path, meta[capture._meta_csv_fieldnames[14]])
            packets = pyshark.FileCapture(_pcap, display_filter='wlan[0] == 0x80')
            fieldnames = ['timestamp', 'bssid', 'ssi', 'channel', 'bearing',
                          'lat', 'lon', 'alt', 'lat_err', 'lon_error', 'alt_error']
            results_csv_writer = csv.DictWriter(results_csv, dialect="unix", fieldnames=fieldnames)
            results_csv_writer.writeheader()

            module_logger.info("Processing packets")
            for packet in packets:

                try:
                    # Get time, bssid & db from packet
                    ptime = packet.sniff_time.timestamp()
                    pbssid = packet.wlan.bssid
                    pssi = int(packet.radiotap.dbm_antsignal)
                    pchannel = int(packet.radiotap.channel_freq)
                except AttributeError:
                    _beacon_failures += 1
                    continue

                # Antenna correlation
                # Compute the timespan for the rotation, and use the relative packet time to determine
                # where in the rotation the packet was captured
                # This is necessary to have a smooth antenna rotation with microstepping
                total_time = float(meta["end"]) - float(meta["start"])
                pdiff = ptime - float(meta["start"])
                if pdiff <= 0:
                    pdiff = 0

                pprogress = pdiff / total_time
                pbearing = pprogress * float(meta["degrees"]) + float(meta["bearing"])

                results_csv_writer.writerow({
                    fieldnames[0]: ptime,
                    fieldnames[1]: pbssid,
                    fieldnames[2]: pssi,
                    fieldnames[3]: pchannel,
                    fieldnames[4]: pbearing,
                    fieldnames[5]: meta["pos_lat"],
                    fieldnames[6]: meta["pos_lon"],
                    fieldnames[7]: meta["pos_alt"],
                    fieldnames[8]: meta["pos_lat_err"],
                    fieldnames[9]: meta["pos_lon_err"],
                    fieldnames[10]: meta["pos_alt_err"], })

                _beacon_count += 1

        module_logger.info("Completed processing {} beacons to {}".format(_beacon_count, _results_path))
        module_logger.info("Failed to process {} beacons".format(_beacon_failures))
        return _beacon_count, _results_path

    except ValueError as e:
        module_logger.error(e)
        # Delete csv
        os.remove(_results_path)
        return _beacon_count, None


def _check_capture_dir(files):
    """
    Check whether the list of files has the required files in it to be considered a capture directory

    :param files: Files to check
    :type files: list
    :return: True if the files indicate a capture path, false otherwise
    :rtype: bool
    """

    for suffix in capture._capture_suffixes.values():
        if not any(file.endswith(suffix) for file in files):
            return False

    return True


def _check_capture_processed(files):
    """
    Check whether the list of files has already been processed

    :param files: Files to check
    :type files: list
    :return: True if the files indicate a capture has been processed already, false otherwise
    :rtype: bool
    """

    if any(file.endswith(capture._results_suffix) for file in files):
        return True

    return False


def _get_capture_meta(files):
    """
    Get the capture meta file path from list of files

    :param files: Files to check
    :type files: list
    :return: Filename of meta file
    :rtype: str
    """

    for file in files:
        if file.endswith(capture._capture_suffixes["meta"]):
            return file

    return None


def process_directory():
    """
    Process entire directory - will search subdirectories for required files and process them if not already processed

    :param limit: limit on the number of directories to process
    :type limit: int
    :return: The number of directories processed
    :rtype: int
    """

    _tasks = []

    # Walk through each subdirectory of working directory
    module_logger.info("Building list of directories to process")
    for root, dirs, files in os.walk(os.getcwd()):
        if not _check_capture_dir(files):
            continue
        elif _check_capture_processed(files):
            continue
        else:
            # Add meta file to list
            _file = _get_capture_meta(files)
            assert _file is not None
            _tasks.append((root, _file))

    print("Found {} unprocessed data sets".format(len(_tasks)))

    if _tasks:
        with Pool(processes=4) as pool:
            _results = 0
            for result in tqdm(pool.imap_unordered(process_capture, _tasks), total=len(_tasks)):
                _results += result[0]

            print("Processed {} packets in {} directories".format(_results, len(_tasks)))