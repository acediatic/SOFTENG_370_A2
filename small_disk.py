#!/usr/bin/env python
from __future__ import print_function, absolute_import, division
from typing import Tuple
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

import logging

from time import time

from errno import ENOENT
from stat import ST_NLINK, S_IFDIR, S_IFLNK, S_IFREG

from disktools import BLOCK_SIZE, NUM_BLOCKS, bytes_to_int, bytes_to_pathname, int_to_bytes, path_name_as_bytes, print_block, read_block, write_block

from format_small_disk import create_file_data, format_block, format_dir

from constants import *

from math import ceil


class SmallDisk(LoggingMixIn, Operations):
    'Example memory filesystem. Supports only one level of files.'

    def get_first_file(self, root_num):
        root = read_block(root_num)
        fh_b = root[NEXT_FILE_LOC: NEXT_FILE_LOC + NEXT_FILE_SIZE]
        return bytes_to_int(fh_b)

    def get_block(self, block_num):
        current_block = read_block(block_num)
        b_block_num = current_block[NEXT_BLOCK_LOC: NEXT_BLOCK_LOC+NEXT_BLOCK_SIZE]
        return bytes_to_int(b_block_num)

    def get_fh(self):
        root = read_block(ROOT_LOC)
        return root[FH_LOC]

    def get_file_size(self, file_num):
        file_data = read_block(file_num)
        return bytes_to_int(file_data[FILE_DATA_LOC + ST_SIZE_LOC: FILE_DATA_LOC + ST_SIZE_LOC + ST_SIZE_SIZE])

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

        self.convert_bytes_and_update_block(ROOT_LOC, FH_LOC, fh, FH_SIZE)

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
            file_num, MTIME_LOC, mtime, ST_MTIME_SIZE)
        self.convert_bytes_and_update_block(
            file_num, ATIME_LOC, atime, ST_ATIME_SIZE)

    def unlink(self, path):
        (prev_block_num, file_block_num, next_block_num) = self.find_file_tuple(path)

        if (prev_block_num == file_block_num or prev_block_num == next_block_num or file_block_num == next_block_num):
            raise IOError("prev, current, or next block equal")

        self.convert_bytes_and_update_block(
            prev_block_num, NEXT_FILE_LOC, next_block_num, NEXT_FILE_SIZE)

    def getattr(self, path, fh=None):
        file_block_num = self.find_file_num(path)
        return self.get_file_description(file_block_num)

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

    def get_all_filenames(self, path) -> list:
        filenames = []
        # This intentionally skips the root

        dir_num = self.find_file_num(path)

        fnum = self.get_first_file(dir_num)
        while(fnum < NUM_BLOCKS):
            fname = self.get_file_name(fnum)

            if len(fname.split(path)) == 2:
                filenames.append('/' + fname.split('/')[-1])

            fnum = self.find_next_file(fnum)

        return filenames

    def get_all_file_blocks(self, file_num):
        block_nums = []
        b_num = self.get_block(file_num)

        while b_num < NUM_BLOCKS:
            block_nums.append(b_num)
            b_num = self.get_block(b_num)

        return block_nums

    def get_file_name(self, file_num):
        file_data = read_block(file_num)
        name_data = file_data[NAME_LOC:NAME_LOC+NAME_SIZE]
        return bytes_to_pathname(name_data)

    def read(self, path, size, offset, fh):
        file_num = self.find_file_num(path)
        return self.get_current_file_data(file_num)[offset:offset + size]

    def mkdir(self, path, mode):
        new_dir_num = self.find_free_block()
        format_dir(path, mode, file_num=new_dir_num,
                   next_free_block=NUM_BLOCKS)

        last_file = self.find_last_file()
        self.convert_bytes_and_update_block(
            last_file, NEXT_FILE_LOC, new_dir_num, NEXT_FILE_SIZE)
        self.increase_n_link()

    def increase_n_link(self):
        root = read_block(ROOT_LOC)
        st_n_link = bytes_to_int(
            root[ST_N_LINKS_LOC: ST_N_LINKS_LOC+ST_NLINKS_SIZE])
        st_n_link += 1
        self.convert_bytes_and_update_block(
            ROOT_LOC, ST_N_LINKS_LOC, st_n_link, ST_NLINKS_SIZE)

    def readdir(self, path, fh):
        return ['.', '..'] + [x[1:] for x in self.get_all_filenames(path)]

    def get_file_description(self, file_meta_block_num):
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

    def get_current_file_data(self, file_num):
        file_blocks = self.get_all_file_blocks(file_num)

        current_file_data = b''

        for block_num in file_blocks:
            current_file_data += read_block(
                block_num)[NEXT_BLOCK_LOC + NEXT_BLOCK_SIZE:]

        return current_file_data

    def write(self, path, data, offset, fh, length=None):
        file_num = self.find_file_num(path)
        file_blocks = self.get_all_file_blocks(file_num)

        current_file_data = self.get_current_file_data(file_num)

        if length == None:
            new_data = (current_file_data[:offset].ljust(offset, '\x00'.encode('ascii'))
                        + data
                        # and only overwrites the bytes that data is replacing
                        + current_file_data[offset + len(data):])
        else:  # truncate
            # make sure extending the file fills in zero bytes
            new_data = current_file_data[:length].ljust(
                length, '\x00'.encode('ascii'))

        new_file_size = len(new_data)

        num_blocks_needed = ceil(new_file_size / EFFECTIVE_BLOCK_SIZE)

        if len(file_blocks) != num_blocks_needed:
            if len(file_blocks) < num_blocks_needed:
                while len(file_blocks) < num_blocks_needed:
                    file_blocks.append(self.find_free_block())
            else:
                while len(file_blocks) > num_blocks_needed:
                    self.format_block(file_blocks.pop())

        NO_NEXT_FILE = int_to_bytes(NUM_BLOCKS, NEXT_FILE_SIZE)

        for i in range(num_blocks_needed):
            data_to_write = new_data[:EFFECTIVE_BLOCK_SIZE].ljust(
                EFFECTIVE_BLOCK_SIZE, '\x00'.encode('ascii'))
            new_data = new_data[EFFECTIVE_BLOCK_SIZE:]

            next_block = NUM_BLOCKS if i == num_blocks_needed - \
                1 else file_blocks[i+1]
            b_next_block = int_to_bytes(next_block, NEXT_BLOCK_SIZE)
            write_block(file_blocks[i], NO_NEXT_FILE +
                        b_next_block + data_to_write)

        # update file size in metadata
        self.convert_bytes_and_update_block(
            file_num, FILE_DATA_LOC + ST_SIZE_LOC, new_file_size, ST_SIZE_SIZE)

        # update file first block in metadata
        self.convert_bytes_and_update_block(
            file_num, NEXT_BLOCK_LOC, file_blocks[0], NEXT_BLOCK_SIZE)

        if data != None:
            return len(data)

    def truncate(self, path, length, fh=None):
        self.write(path, None, 0, None, length)

    ##### UTIL METHODS #####

    def find_file_num(self, path):
        _, file_num, _ = self.find_file_tuple(path)
        return file_num

    def find_file_tuple(self, path: str) -> Tuple[int, int, int]:
        b_name_to_find = path_name_as_bytes(path)

        block_num = ROOT_LOC
        prev_block_num = ROOT_LOC

        while True:
            if block_num >= NUM_BLOCKS:
                raise FuseOSError(ENOENT)

            current_block = read_block(block_num)

            start = NAME_LOC
            end = NAME_LOC + NAME_SIZE

            current_file_name = current_block[start:end]

            if current_file_name == b_name_to_find:
                return (prev_block_num, block_num, current_block[NEXT_FILE_LOC])
            else:
                prev_block_num = block_num
                block_num = current_block[NEXT_FILE_LOC]

    def find_last_file(self) -> int:
        current_block_num = next_block_num = ROOT_LOC

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

        block_data = block_data[:start] + data + block_data[end:]

        write_block(block_num, block_data)

    def convert_bytes_and_update_block(self, block_num: int, start: int, data: int, num_bytes: int):
        data = int_to_bytes(data, num_bytes)
        self.update_block(block_num, start, data)

    def find_free_block(self):
        first_free_block_i = self.get_block(ROOT_LOC)
        if first_free_block_i >= NUM_BLOCKS:
            raise IOError("No free blocks remaining")

        free_block = read_block(first_free_block_i)

        next_free_block_i = free_block[NEXT_BLOCK_LOC]

        self.convert_bytes_and_update_block(
            ROOT_LOC, NEXT_BLOCK_LOC, next_free_block_i, NEXT_BLOCK_SIZE)

        return first_free_block_i

    def format_block(self, block_num):
        first_free_block = self.get_block(ROOT_LOC)
        format_block(block_num, first_free_block)

        self.convert_bytes_and_update_block(
            ROOT_LOC, NEXT_BLOCK_LOC, block_num, NEXT_BLOCK_SIZE)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('mount')
    args = parser.parse_args()

    logging.basicConfig(level=logging.DEBUG)
    fuse = FUSE(SmallDisk(), args.mount, foreground=True)
