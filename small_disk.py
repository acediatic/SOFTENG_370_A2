#!/usr/bin/env python
from __future__ import print_function, absolute_import, division
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

import logging

from time import time

from errno import ENOENT
from stat import S_IFDIR, S_IFLNK, S_IFREG

from disktools import NUM_BLOCKS, bytes_to_int, int_to_bytes, path_name_as_bytes, read_block, write_block

from format_small_disk import create_file_data

FILE_DATA_SIZE = 37
NEXT_FILE_SIZE = 1
NEXT_BLOCK_SIZE = 1

# Order of storage in metadata block
NEXT_FILE_LOC = 0
NEXT_BLOCK_LOC = 1
FILE_DATA_LOC = 2

FH_LOC = 39


class SmallDisk(LoggingMixIn, Operations):
    'Example memory filesystem. Supports only one level of files.'

    def __init__(self):
        root_data = read_block(0)

        self.next_file = root_data[NEXT_FILE_LOC]

        self.next_free_block = root_data[NEXT_BLOCK_LOC]

        self.fh = root_data[FILE_DATA_LOC]

    def create(self, path, mode):
        file_data = create_file_data(path, (S_IFREG | mode))

        next_file = int_to_bytes(NUM_BLOCKS, 1)
        next_block = int_to_bytes(NUM_BLOCKS, 1)

        data = next_file + next_block + file_data

        # Finds the next free block, updating both self and file.
        next_free_block = self.find_free_block()

        write_block(next_free_block, data)

        self.fh += 1

        new_fh = int_to_bytes(self.fh, 1)

        self.update_block(0, FH_LOC, new_fh)

        return self.fh

    def getattr(self, path, fh=None):
        b_name_to_find = path_name_as_bytes(path)

        next_block_num = 0

        while True:
            try:
                current_block = read_block(next_block_num)

                start = FILE_DATA_LOC + 21
                end = FILE_DATA_LOC + FILE_DATA_SIZE

                current_file_name = current_block[start:end]

                print("\n\n\n\n\nYEET\n\n\n\n")
                print(current_file_name == b_name_to_find)
                
                if current_file_name == b_name_to_find:
                    return self.get_file_data(next_block_num)
                else:
                    next_block_num = current_block[NEXT_FILE_LOC]

            except IOError:
                raise FuseOSError(ENOENT)

    def get_file_data(self, file_meta_block_num):
        meta_block = read_block(file_meta_block_num)
        file_details = dict()

        details = ["st_mode", "st_uid", "st_gid", "st_nlinks",
                   "st_size", "st_ctime", "st_mtime", "st_atime"]

        locations = [2, 4, 6, 7, 9, 13, 17, 21]

        prev_end = 0
        for (i, detail) in enumerate(details):
            file_details[detail] = bytes_to_int(meta_block[prev_end:locations[i]])
            prev_end = locations[i]

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

    def update_block(self, block_num, start, data):
        block_data = read_block(block_num)
        end = len(data)

        block_data[start:end] = data
        write_block(block_num, block_data)

    def find_free_block(self):
        if self.next_free_block >= NUM_BLOCKS:
            raise IOError("No free blocks remaining")

        free_block_i = self.next_free_block
        free_block = read_block(free_block_i)

        next_free_block_i = free_block[NEXT_BLOCK_LOC]
        self.next_free_block = next_free_block_i

        data = int_to_bytes(next_free_block_i, 1)
        self.update_block(0, NEXT_BLOCK_LOC, data)

        return free_block_i


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('mount')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    fuse = FUSE(SmallDisk(), args.mount, foreground=True)
