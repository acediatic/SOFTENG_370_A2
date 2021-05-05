from logging import getLogger
from os import write
from disktools import BLOCK_SIZE, NUM_BLOCKS, int_to_bytes, print_block, write_block
from constants import *

from errno import EINVAL
from fuse import FuseOSError

from time import time

from stat import S_IFDIR, S_IFLNK, S_IFREG

from os import getuid, getgid
UID = getuid()
GID = getgid()


def create_file_data(path, o_mode, st_n_link=1):
    '''Create the file's data (metadata)'''
    int_now = int(time())

    st_mode = int_to_bytes(o_mode, ST_MODE_SIZE)
    st_uid = int_to_bytes(UID, ST_UID_SIZE)
    st_gid = int_to_bytes(GID, ST_GID_SIZE)
    st_nlink = int_to_bytes(st_n_link, ST_NLINKS_SIZE)
    st_size = int_to_bytes(0, ST_SIZE_SIZE)
    st_ctime = int_to_bytes(int_now, ST_CTIME_SIZE)
    st_mtime = int_to_bytes(int_now, ST_MTIME_SIZE)
    st_atime = int_to_bytes(int_now, ST_ATIME_SIZE)

    st_name = path_name_as_bytes(path)

    file_data = st_mode + st_uid + st_gid + st_nlink + st_size + \
        st_ctime + st_mtime + st_atime + st_name

    return file_data


def format_dir(path, mode, file_num=0, next_free_block=1):
    ''' Used to format a directory, including the root which uses the 0th block'''

    next_free_block = int_to_bytes(next_free_block, NEXT_BLOCK_SIZE)
    # Block index out of range is used to indicate no next block
    next_file = int_to_bytes(NUM_BLOCKS, NEXT_FILE_SIZE)

    metadata = create_file_data(path, (S_IFDIR | mode), 2)

    fh = int_to_bytes(0, FH_SIZE)

    # 1 + 1 + 37 + 1
    root_data = next_file + next_free_block + metadata + fh
    padded_root_data = root_data + bytearray(BLOCK_SIZE - len(root_data))

    write_block(file_num, padded_root_data)


def format_block(block_num, next_free_block):
    '''formats a regular block and points it to next_free_block'''
    null_next_file = int_to_bytes(NUM_BLOCKS, NEXT_FILE_SIZE)
    next_block = int_to_bytes(next_free_block, NEXT_BLOCK_SIZE)
    padded_data = null_next_file + next_block + \
        bytearray(BLOCK_SIZE - (NEXT_FILE_SIZE + NEXT_BLOCK_SIZE))
    write_block(block_num, padded_data)


def format_all_blocks():
    '''formats all blocks EXCEPT ROOT'''
    for i in range(1, NUM_BLOCKS):
        format_block(i, i+1)


def path_name_as_bytes(path):
    ''' converts a path name to a 16 byte array of ascii '''
    name_bytes = []

    file_name = path

    if not file_name:
        file_name = '/'

    for c in file_name:
        name_bytes.append(int_to_bytes(ord(c), 1))

    if NAME_SIZE - len(name_bytes) < 0:
        raise FuseOSError(EINVAL)

    name_bytes.append(bytearray(NAME_SIZE - len(name_bytes)))

    name = b''.join(name_bytes)

    return name


def bytes_to_pathname(bytes):
    ''' converts a 16 byte array to a path name '''
    ascii_name = []
    for int_val in bytes:
        if int_val == 0:
            break
        else:
            ascii_name.append(chr(int_val))

    return ''.join(ascii_name)


if __name__ == '__main__':
    format_all_blocks()
    format_dir('/', 0o755)
    for i in range(10):
        print_block(i)
