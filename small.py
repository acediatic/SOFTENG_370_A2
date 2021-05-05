#!/usr/bin/env python
from __future__ import print_function, absolute_import, division
from typing import Tuple
from fuse import FUSE, FuseOSError, Operations, LoggingMixIn

import logging

from time import time
from math import ceil

from errno import ENOENT, ENOTEMPTY
from stat import ST_NLINK, S_IFDIR, S_IFLNK, S_IFREG

from disktools import BLOCK_SIZE, NUM_BLOCKS, bytes_to_int,  int_to_bytes, print_block, read_block, write_block
from format import create_file_data, format_block, format_dir, path_name_as_bytes, bytes_to_pathname
from constants import *


class SmallDisk(LoggingMixIn, Operations):
    def get_first_file(self, root_num):
        ''' returns the block number of the file pointed to by the current file '''
        root = read_block(root_num)
        fh_b = root[NEXT_FILE_LOC: NEXT_FILE_LOC + NEXT_FILE_SIZE]
        return bytes_to_int(fh_b)

    def get_block(self, block_num):
        ''' returns the free/used block pointed to by the current file. 
        For files, this is the first data block. For the root, 
        this is the first free block '''
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
        ''' creates a file at path with no data blocks, and adds it to the
        linked list of files. '''
        file_data = create_file_data(path, (S_IFREG | mode))

        next_file = int_to_bytes(NUM_BLOCKS, NEXT_FILE_SIZE)
        next_block = int_to_bytes(NUM_BLOCKS, NEXT_BLOCK_SIZE)

        data = next_file + next_block + file_data

        # Finds the next free block, updating both self and file.
        next_free_block = self.find_free_block()
        write_block(next_free_block, data)

        # increments fh in the root.
        fh = self.get_fh()
        fh += 1
        self.convert_bytes_and_update_block(ROOT_LOC, FH_LOC, fh, FH_SIZE)

        # adds this file to the end of the file linked list
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

        # removes the current file from the file linked list by making the previous file
        # point to the next file.
        self.convert_bytes_and_update_block(
            prev_block_num, NEXT_FILE_LOC, next_block_num, NEXT_FILE_SIZE)

        file_blocks = self.get_all_file_blocks(file_block_num)
        file_blocks.append(file_block_num)

        while(file_blocks):
            self.format_block(file_blocks.pop())

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
        ''' returns a list of all filenames for the current directory (.,.. excl)'''
        filenames = []

        # files will always come after their directory
        dir_num = self.find_file_num(path)

        fnum = self.get_first_file(dir_num)
        while(fnum < NUM_BLOCKS):
            fname = self.get_file_name(fnum)

            if len(fname.split(path)) == 2:
                filenames.append('/' + fname.split('/')[-1])

            fnum = self.find_next_file(fnum)

        return filenames

    def get_all_file_blocks(self, file_num):
        ''' returns a list of the block numbers containing file data for the input file'''
        block_nums = []
        b_num = self.get_block(file_num)

        while b_num < NUM_BLOCKS:
            block_nums.append(b_num)
            b_num = self.get_block(b_num)

        return block_nums

    def get_file_name(self, file_num):
        ''' returns the name of the file with metadata in block file_num'''
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

        dir_path = self.get_dir_path(path)

        dir_num = self.find_file_num(dir_path)
        self.change_n_link(dir_num)

    def get_dir_path(self, path):
        ''' gets the path of the parent directory from the input path '''
        dir_path = path.rsplit('/', 1)[0]
        if not dir_path:
            dir_path = '/'
        return dir_path

    def change_n_link(self, dir_num: int, positive=True):
        ''' changes the n_links for the input directory.

        Args: 
            bool Positive: true for increment, false for decrement '''
        direction = 1 if positive else -1

        root = read_block(dir_num)
        st_n_link = bytes_to_int(
            root[ST_N_LINKS_LOC: ST_N_LINKS_LOC+ST_NLINKS_SIZE])
        st_n_link += 1 * direction
        self.convert_bytes_and_update_block(
            ROOT_LOC, ST_N_LINKS_LOC, st_n_link, ST_NLINKS_SIZE)

    def readdir(self, path, fh=None):
        return ['.', '..'] + [x[1:] for x in self.get_all_filenames(path)]

    def rmdir(self, path):
        ''' removes directory if it does not contain files, otherwise raises error'''
        if len(self.readdir(path)) > 2:
            raise FuseOSError(ENOTEMPTY)
        else:
            parent_path = self.get_dir_path(path)
            self.unlink(path)
            parent_num = self.find_file_num(parent_path)
            self.change_n_link(parent_num)

    def get_file_description(self, file_meta_block_num):
        ''' returns the description of the file from its metadata as a dictionary'''
        meta_block = read_block(file_meta_block_num)
        file_details = dict()

        details = ["st_mode", "st_uid", "st_gid", "st_nlink",
                   "st_size", "st_ctime", "st_mtime", "st_atime"]

        locations = [2, 4, 6, 7, 9, 13, 17, 21]

        prev_end = FILE_DATA_LOC
        for (i, detail) in enumerate(details):
            end = locations[i] + FILE_DATA_LOC
            file_details[detail] = bytes_to_int(meta_block[prev_end:end])
            prev_end = end

        return file_details

    def get_current_file_data(self, file_num):
        ''' Fetches all the data currently stored in the input file'''
        file_blocks = self.get_all_file_blocks(file_num)

        current_file_data = b''

        for block_num in file_blocks:
            current_file_data += read_block(
                block_num)[NEXT_BLOCK_LOC + NEXT_BLOCK_SIZE:]

        return current_file_data

    def write(self, path, data, offset, fh, length=None):
        ''' writes the data to file stored at path '''
        file_num = self.find_file_num(path)
        file_blocks = self.get_all_file_blocks(file_num)

        file_size = self.get_file_size(file_num)

        # fetches only the data that is real data, removing padding of rest of last block.
        current_file_data = self.get_current_file_data(file_num)
        current_file_data = current_file_data[:file_size]

        if length == None:
            # length == None indicates it is a regular write call
            new_data = (current_file_data[:offset].ljust(offset, '\x00'.encode('ascii'))
                        + data
                        # and only overwrites the bytes that data is replacing
                        + current_file_data[offset + len(data):])
        else:  # truncate
            # make sure extending the file fills in zero bytes
            new_data = current_file_data[:length].ljust(
                length, '\x00'.encode('ascii'))

        new_file_size = len(new_data)

        num_blocks_needed = max(ceil(new_file_size / EFFECTIVE_BLOCK_SIZE), 1)

        if len(file_blocks) != num_blocks_needed:
            if len(file_blocks) < num_blocks_needed:
                while len(file_blocks) < num_blocks_needed:
                    try:
                        file_blocks.append(self.find_free_block())
                    except:
                        if not file_blocks:
                            # Only got a metadata block and not a data block.
                            # Unlink metadata block, no room for file.
                            self.unlink(file_num)
                        raise IOError("No free blocks remaining")
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
        ''' returns the block number of the metadata block for file with name path'''
        _, file_num, _ = self.find_file_tuple(path)
        return file_num

    def find_file_tuple(self, path: str) -> Tuple[int, int, int]:
        ''' finds the preceding (points to), current (points to), and next file 
        for the file with name path'''
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
        ''' fetches the block number of the last file in the file linked list'''
        current_block_num = next_block_num = ROOT_LOC

        while next_block_num < NUM_BLOCKS:
            current_block_num = next_block_num
            next_block_num = self.find_next_file(current_block_num)

        return current_block_num

    def find_next_file(self, current_file):
        ''' retrieves the block number of the file pointed to by the current file'''
        current_meta = read_block(current_file)
        return current_meta[0]

    def update_block(self, block_num: int, start: int, data: bytearray):
        ''' reads a whole block, overwrites data between start and len(data), and rewrites the 
        whole block back to memory'''
        block_data = read_block(block_num)
        end = start + len(data)

        block_data = block_data[:start] + data + block_data[end:]

        write_block(block_num, block_data)

    def convert_bytes_and_update_block(self, block_num: int, start: int, data: int, num_bytes: int):
        ''' converts data to bytearray of size num_bytes, then updates the block with this data'''
        data = int_to_bytes(data, num_bytes)
        self.update_block(block_num, start, data)

    def find_free_block(self):
        ''' retrieves a free block from the front of the free block linked list. It then updates 
        the root to point to the next free block, and returns the first free block'''
        first_free_block_i = self.get_block(ROOT_LOC)
        if first_free_block_i >= NUM_BLOCKS:
            raise IOError("No free blocks remaining")

        free_block = read_block(first_free_block_i)

        next_free_block_i = free_block[NEXT_BLOCK_LOC]

        self.convert_bytes_and_update_block(
            ROOT_LOC, NEXT_BLOCK_LOC, next_free_block_i, NEXT_BLOCK_SIZE)

        return first_free_block_i

    def format_block(self, block_num):
        ''' formats a block and inserts it at the front of the free block linked list.
        This means the block now has no data written and points to no file, 
        but points to the next free block '''
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
