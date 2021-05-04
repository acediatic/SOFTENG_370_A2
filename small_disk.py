#!/usr/bin/env python
from __future__ import print_function, absolute_import, division
from typing import Tuple
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

import logging

from time import time

from errno import ENOENT
from stat import S_IFDIR, S_IFLNK, S_IFREG

from disktools import NUM_BLOCKS, bytes_to_int, int_to_bytes, path_name_as_bytes, print_block, read_block, write_block

from format_small_disk import create_file_data

FILE_DATA_SIZE = 37
NEXT_FILE_SIZE = 1
NEXT_BLOCK_SIZE = 1
FH_SIZE = 1

# Order of storage in metadata block
NEXT_FILE_LOC = 0
NEXT_BLOCK_LOC = 1
FILE_DATA_LOC = 2

FH_LOC = 39

MTIME_LOC = 13 + FILE_DATA_LOC
ATIME_LOC = 17 + FILE_DATA_LOC

MTIME_SIZE = 4
ATIME_SIZE = 4


class SmallDisk(LoggingMixIn, Operations):
    'Example memory filesystem. Supports only one level of files.'

    def get_first_file(self):
        root = read_block(0)
        fh_b = root[NEXT_FILE_LOC: NEXT_FILE_LOC + NEXT_FILE_SIZE]
        return bytes_to_int(fh_b)

    def get_first_free_block(self):
        root = read_block(0)
        return root[NEXT_BLOCK_LOC]

    def get_fh(self):
        root = read_block(0)
        return root[FH_LOC]

    def create(self, path, mode):
        file_data = create_file_data(path, (S_IFREG | mode))

        next_file = int_to_bytes(NUM_BLOCKS, NEXT_FILE_SIZE)
        next_block = int_to_bytes(NUM_BLOCKS, NEXT_BLOCK_SIZE)

        data = next_file + next_block + file_data

        # Finds the next free block, updating both self and file.
        next_free_block = self.find_free_block()

        write_block(next_free_block, data)

        fh = self.get_fh()
        fh += 1

        self.convert_bytes_and_update_block(0, FH_LOC, fh, FH_SIZE)

        last_file = self.find_last_file()

        self.convert_bytes_and_update_block(
            last_file, NEXT_FILE_LOC, next_free_block, NEXT_FILE_SIZE)

        return fh

    def utimens(self, path, times=None):
        now = int(time())

        times = tuple(int(t) for t in times)
        atime, mtime = times if times else (now, now)

        file_num = self.find_file_num(path)

        self.convert_bytes_and_update_block(
            file_num, MTIME_LOC, mtime, MTIME_SIZE)
        self.convert_bytes_and_update_block(
            file_num, ATIME_LOC, atime, ATIME_SIZE)

    def unlink(self, path):
        (prev_block_num, file_block_num, next_block_num) = self.find_file_tuple(path)

        if (prev_block_num == file_block_num or prev_block_num == next_block_num or file_block_num == next_block_num):
            raise IOError("prev, current, or next block equal")

        self.convert_bytes_and_update_block(
            prev_block_num, NEXT_FILE_LOC, next_block_num, NEXT_FILE_SIZE)

    def getattr(self, path, fh=None):
        file_block_num = self.find_file_num(path)
        return self.get_file_data(file_block_num)

    def getxattr(self, path, name, position=0):
        attrs = self.getattr(path)

        try:
            return attrs[name]
        except KeyError:
            # edited as per https://piazza.com/class/klboaqfyq7q2ln?cid=56_f1
            return bytes()      # Should return ENOATTR

    def listxattr(self, path):
        attrs = self.getattr(path)
        return attrs.keys()

    def get_file_data(self, file_meta_block_num):
        meta_block = read_block(file_meta_block_num)
        file_details = dict()

        details = ["st_mode", "st_uid", "st_gid", "st_nlinks",
                   "st_size", "st_ctime", "st_mtime", "st_atime"]

        locations = [2, 4, 6, 7, 9, 13, 17, 21]

        prev_end = FILE_DATA_LOC
        for (i, detail) in enumerate(details):
            end = locations[i] + FILE_DATA_LOC
            file_details[detail] = bytes_to_int(meta_block[prev_end:end])
            prev_end = end

        return file_details

        # def write(self, path, data, offset, fh):
    #     b_name = path_name_as_bytes(path)

    #     current_file = self.next_file

    # if size of file < SIZE_BLOCK:
    # next_block = int_to_bytes(NUM_BLOCKS)
    # else next_block = get next free block.

    #     try:
    #         while(true):
    #             current_data = read_block(current_file)
    #             current_name =

    #     except IOError:
    #         raise IOError("File not found")

    #     self.data[path] = (
    #         # make sure the data gets inserted at the right offset
    #         self.data[path][:offset].ljust(offset, '\x00'.encode('ascii'))
    #         + data
    #         # and only overwrites the bytes that data is replacing
    #         + self.data[path][offset + len(data):])
    #     self.files[path]['st_size'] = len(self.data[path])
    #     return len(data)

    ##### UTIL METHODS #####

    def find_file_num(self, path):
        _, file_num, _ = self.find_file_tuple(path)
        return file_num

    def find_file_tuple(self, path: str) -> Tuple[int, int, int]:
        b_name_to_find = path_name_as_bytes(path)

        block_num = 0
        prev_block_num = 0

        while True:
            if block_num >= NUM_BLOCKS:
                raise FuseOSError(ENOENT)

            current_block = read_block(block_num)

            start = FILE_DATA_LOC + 21
            end = FILE_DATA_LOC + FILE_DATA_SIZE

            current_file_name = current_block[start:end]

            if current_file_name == b_name_to_find:
                return (prev_block_num, block_num, current_block[NEXT_FILE_LOC])
            else:
                prev_block_num = block_num
                block_num = current_block[NEXT_FILE_LOC]

    def find_last_file(self) -> int:
        current_block_num = next_block_num = 0

        while next_block_num < NUM_BLOCKS:
            current_block_num = next_block_num
            next_block_num = self.find_next_file(current_block_num)

        return current_block_num

    def find_next_file(self, current_file):
        current_meta = read_block(current_file)
        return current_meta[0]

    def update_block(self, block_num: int, start: int, data: bytearray):
        block_data = read_block(block_num)
        end = start + len(data)

        block_data[start:end] = data
        write_block(block_num, block_data)

    def convert_bytes_and_update_block(self, block_num: int, start: int, data: int, num_bytes: int):
        data = int_to_bytes(data, num_bytes)
        self.update_block(block_num, start, data)

    def find_free_block(self):
        first_free_block_i = self.get_first_free_block()
        if first_free_block_i >= NUM_BLOCKS:
            raise IOError("No free blocks remaining")

        free_block = read_block(first_free_block_i)

        next_free_block_i = free_block[NEXT_BLOCK_LOC]

        self.convert_bytes_and_update_block(
            0, NEXT_BLOCK_LOC, next_free_block_i, 1)

        return first_free_block_i


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('mount')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    fuse = FUSE(SmallDisk(), args.mount, foreground=True)
