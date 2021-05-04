from logging import getLogger
from os import write
from small_disk import FH_SIZE, NEXT_BLOCK_SIZE, NEXT_FILE_SIZE, ST_ATIME_SIZE, ST_CTIME_SIZE, ST_GID_SIZE, ST_MODE_SIZE, ST_MTIME_SIZE, ST_NLINKS_SIZE, ST_SIZE_SIZE, ST_UID_SIZE
from disktools import BLOCK_SIZE, NUM_BLOCKS, int_to_bytes, path_name_as_bytes, print_block, write_block

from time import time

from stat import S_IFDIR, S_IFLNK, S_IFREG

# Top of file
from os import getuid, getgid
UID = getuid()
GID = getgid()


# Create the file's data (metadata).
def create_file_data(path, o_mode):
    
    int_now = int(time())

    st_mode = int_to_bytes(o_mode, ST_MODE_SIZE)
    st_uid = int_to_bytes(UID, ST_UID_SIZE)
    st_gid = int_to_bytes(GID, ST_GID_SIZE)
    st_nlinks = int_to_bytes(1, ST_NLINKS_SIZE)
    st_size = int_to_bytes(0, ST_SIZE_SIZE)
    st_ctime = int_to_bytes(int_now, ST_CTIME_SIZE)
    st_mtime = int_to_bytes(int_now, ST_MTIME_SIZE)
    st_atime = int_to_bytes(int_now, ST_ATIME_SIZE)

    st_name = path_name_as_bytes(path)

    file_data = st_mode + st_uid + st_gid + st_nlinks + st_size + \
        st_ctime + st_mtime + st_atime + st_name

    return file_data


# Root's metadata stored in the 0th block.
def format_root():
    # Block index out of range, indicating no next block
    next_free_block = int_to_bytes(1, NEXT_BLOCK_SIZE)
    next_file = int_to_bytes(NUM_BLOCKS, NEXT_FILE_SIZE)

    metadata = create_file_data('/', (S_IFDIR | 0o755))

    fh = int_to_bytes(0, FH_SIZE)

    # 1 + 1 + 37 + 1
    root_data = next_file + next_free_block + metadata + fh # + other data

    write_block(0, root_data)

def format_block(block_num, next_free_block):
    null_next_file = int_to_bytes(NUM_BLOCKS, NEXT_FILE_SIZE)
    next_block = int_to_bytes(next_free_block, NEXT_BLOCK_SIZE)
    padded_data = null_next_file + next_block + bytearray(BLOCK_SIZE - 2)
    write_block(block_num, padded_data)

# formats all blocks EXCEPT ROOT


def format_all_blocks():
    for i in range(1, NUM_BLOCKS):
        format_block(i, i+1)


if __name__ == '__main__':
    format_all_blocks()
    format_root()
    for i in range(10):
        print_block(i)
