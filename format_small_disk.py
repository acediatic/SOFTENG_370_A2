from logging import getLogger
from os import write
from disktools import BLOCK_SIZE, NUM_BLOCKS, int_to_bytes, path_name_as_bytes, print_block, write_block
from constants import *

from time import time

from stat import S_IFDIR, S_IFLNK, S_IFREG

# Top of file
from os import getuid, getgid
UID = getuid()
GID = getgid()


# Create the file's data (metadata).
def create_file_data(path, o_mode, st_n_links = 1):

    int_now = int(time())

    st_mode = int_to_bytes(o_mode, ST_MODE_SIZE)
    st_uid = int_to_bytes(UID, ST_UID_SIZE)
    st_gid = int_to_bytes(GID, ST_GID_SIZE)
    st_nlinks = int_to_bytes(st_n_links, ST_NLINKS_SIZE)
    st_size = int_to_bytes(0, ST_SIZE_SIZE)
    st_ctime = int_to_bytes(int_now, ST_CTIME_SIZE)
    st_mtime = int_to_bytes(int_now, ST_MTIME_SIZE)
    st_atime = int_to_bytes(int_now, ST_ATIME_SIZE)

    st_name = path_name_as_bytes(path)

    file_data = st_mode + st_uid + st_gid + st_nlinks + st_size + \
        st_ctime + st_mtime + st_atime + st_name

    return file_data


# Root's metadata stored in the 0th block.
def format_dir(path, mode, file_num = 0, next_free_block = 1):
    # Block index out of range, indicating no next block
    next_free_block = int_to_bytes(next_free_block, NEXT_BLOCK_SIZE)
    next_file = int_to_bytes(NUM_BLOCKS, NEXT_FILE_SIZE)

    metadata = create_file_data(path, (S_IFDIR | mode), 2)

    fh = int_to_bytes(0, FH_SIZE)

    # 1 + 1 + 37 + 1
    root_data = next_file + next_free_block + metadata + fh
    padded_root_data = root_data + bytearray(BLOCK_SIZE - len(root_data)) 

    write_block(file_num, padded_root_data)


def format_block(block_num, next_free_block):
    null_next_file = int_to_bytes(NUM_BLOCKS, NEXT_FILE_SIZE)
    next_block = int_to_bytes(next_free_block, NEXT_BLOCK_SIZE)
    padded_data = null_next_file + next_block + bytearray(BLOCK_SIZE - 2)
    write_block(block_num, padded_data)


def format_all_blocks():
    # formats all blocks EXCEPT ROOT
    for i in range(1, NUM_BLOCKS):
        format_block(i, i+1)


if __name__ == '__main__':
    format_all_blocks()
    format_dir('/', 0o755)
    for i in range(10):
        print_block(i)
