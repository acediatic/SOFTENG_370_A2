from logging import getLogger
from os import write
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

    st_mode = int_to_bytes(o_mode, 2)
    st_uid = int_to_bytes(UID, 2)
    st_gid = int_to_bytes(GID, 2)
    st_nlinks = int_to_bytes(1, 1)
    st_size = int_to_bytes(0, 2)
    st_ctime = int_to_bytes(int_now, 4)
    st_mtime = int_to_bytes(int_now, 4)
    st_atime = int_to_bytes(int_now, 4)

    st_name = path_name_as_bytes(path)

    print("file data", o_mode, UID, GID, 1, 0, int_now)

    file_data = st_mode + st_uid + st_gid + st_nlinks + st_size + \
        st_ctime + st_mtime + st_atime + st_name

    return file_data


# Root's metadata stored in the 0th block.
def format_root():
    # Block index out of range, indicating no next block
    next_free_block = int_to_bytes(1, 1)
    next_file = int_to_bytes(NUM_BLOCKS, 1)

    metadata = create_file_data('/', (S_IFDIR | 0o755))

    fh = int_to_bytes(0, 1)

    # 1 + 1 + 37 + 1
    root_data = next_file + next_free_block + metadata + fh # + other data

    write_block(0, root_data)

def format_block(block_num, next_free_block):
    null_next_file = int_to_bytes(NUM_BLOCKS, 1)
    next_block = int_to_bytes(next_free_block, 1)
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
