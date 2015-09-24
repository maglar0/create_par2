#!/usr/bin/env python

import argparse
import sys
import os
import tempfile
import textwrap
import re
import subprocess
import shutil
import itertools
import math
import decimal
import fractions
import glob
import time

MAX_NUM_BLOCKS = 32700


ignore_files_regexps = map(re.compile, [
    r"^\.DS_Store$"
])

def filter_infiles(files):
    result = []
    for filename in files:
        for regexp in ignore_files_regexps:
            if regexp.match(filename):
                break
        else:
            result.append(filename)
    return result



class ExecutionFailed(Exception):
    pass


def execute_and_throw_if_error(command, cwd, shell=False):
    assert isinstance(command, str) == shell, "Must be a list and shell=False or a string and shell=True"
    if shell:
        return_code = subprocess.call(command, cwd=cwd, shell=True)
    else:
        return_code = subprocess.call([c for c in command if c is not None], cwd=cwd)

    if return_code != 0:
        raise ExecutionFailed()


def print_wrap(s):
    print("\n".join(textwrap.wrap(s)))


def compress_file(infile, outfile, tmpdir, password):
    execute_and_throw_if_error([
                '7z',
                'a',
                ('-p%s' % password) if password else None,
                '-w%s' % tmpdir,
                '--',
                outfile,
                infile],
            cwd=None)


def compress_files(infiles, outdir, tmpdir, password):
    outfiles = []
    for infile in infiles:
        filename = os.path.split(infile)[-1]
        outfile = os.path.join(outdir, "%s.7z" % filename)
        try:
            compress_file(infile=infile, outfile=outfile, tmpdir=tmpdir, password=password)
            outfiles.append(outfile)
        except ExecutionFailed:
            print_wrap("Couldn't compress file %r" % filename)
            raise SystemExit(1)
    return outfiles


def copy_files(infiles, outdir):
    outfiles = []
    for infile in infiles:
        filename = os.path.split(infile)[-1]
        outfile = os.path.join(outdir, filename)
        try:
            shutil.copyfile(infile, outfile)
            outfiles.append(outfile)
        except:
            print_wrap("Couldn't copy file %r to destination %r" % (infile, outfile))
            raise SystemExit(1)
    return outfiles


def create_par2_files(inoutdir, par2_filename, num_recovery_blocks,
        block_size, num_blocks, memory):
    
    assert 0 < num_recovery_blocks < 20000, "%r" % num_recovery_blocks
    assert block_size is None or num_blocks is None, "Can't give both block_size and num_blocks"
    
    try:
        input_filenames = os.listdir(inoutdir)
        
        execute_and_throw_if_error([
                        "par2",
                        "create",
                        ("-s%d" % block_size) if block_size is not None else None,
                        ("-b%d" % num_blocks) if num_blocks is not None else None,
                        "-c%d" % num_recovery_blocks,
                        ("-m%d" % memory) if memory is not None else None,
                        "--",
                        par2_filename
                    ] + input_filenames,
                cwd=inoutdir)
    
    except ExecutionFailed:
        print_wrap("Couldn't create par2 files")
        raise SystemExit(1)


def calculate_last_overshoot(file_size, max_bin_size, last_bin_size, last_bin_size_fraction):
    space_left_until_overshoot = max_bin_size * last_bin_size_fraction - last_bin_size
    overshoot = file_size - space_left_until_overshoot
    if overshoot < 0:
        return overshoot
    else:
        return int(overshoot / last_bin_size_fraction)



def index_of_smallest(a):
    return a.index(min(a))


def distribute_files_uniformly(files_with_sizes, num_bins, last_bin_size_fraction=1):
    """Tries to distribute a set of files about uniformly into a set of bins. It may optionally
    try to only put a fraction of the size of the other bins into the last bin."""
    assert 0 < last_bin_size_fraction <= 1

    sizes_to_files = sorted([(size, file) for file, size in files_with_sizes.items()])

    bins = [[] for i in range(num_bins)]
    bin_sizes = [0] * num_bins

    for size, file in reversed(sizes_to_files):
        adjusted_last_bin_size = int(bin_sizes[-1] / last_bin_size_fraction)
        max_bin_size = max(adjusted_last_bin_size, *bin_sizes[:-1])
        
        overshoot_if_put_in_bin = [size - (max_bin_size - bin_size) for bin_size in bin_sizes[:-1]]
        overshoot_if_put_in_bin.append(
                calculate_last_overshoot(size, max_bin_size, bin_sizes[-1], last_bin_size_fraction))

        target_index = index_of_smallest(overshoot_if_put_in_bin)
        bins[target_index].append(file)
        bin_sizes[target_index] += size

    return bins, bin_sizes


def create_bar_chart(values, width=60):
    max_value = max(values)

    lines = []
    for value in values:
        num_x = int(round(float(value) * width / max_value))
        num_space = width - num_x
        lines.append("%s%s %d" % ("#" * num_x, " " * num_space, value))

    return lines


def get_dest_dirs(destdir, prefix, num_volumes):
    dest_dirs = [os.path.abspath(os.path.join(destdir, "%s%d" % (prefix, i+1)))
                    for i in range(num_volumes)]
    return dest_dirs


def move_files_to_destination_dir(srcdir, destdir, par2_filename, prefix, num_volumes):
    files = os.listdir(srcdir)
    assert par2_filename in files
    files.remove(par2_filename)
    
    par2_src_path = os.path.join(srcdir, par2_filename)

    dest_dirs = get_dest_dirs(destdir, prefix, num_volumes)

    file_paths = [os.path.join(srcdir, f) for f in files]
    file_sizes = {f: os.path.getsize(f) for f in file_paths}

    bins, bin_sizes = distribute_files_uniformly(file_sizes, num_volumes, 1)

    i = 0
    for current_bin, current_dest_dir in zip(bins, dest_dirs):
        os.mkdir(current_dest_dir)
        shutil.copyfile(par2_src_path, os.path.join(current_dest_dir, os.path.split(par2_src_path)[1]))

        for filepath in (current_bin):
            print("Moving file %d of %d" % (i+1, len(file_sizes)))
            shutil.move(filepath, current_dest_dir)
            i += 1

    os.remove(par2_src_path)


def create_md5_sums(inoutdir, prefix, num_volumes):
    dest_dirs = get_dest_dirs(inoutdir, prefix, num_volumes)

    for d in dest_dirs:
        input_filepaths = [os.path.join(inoutdir, f) for f in glob.glob("%s/*" % d)]
        execute_and_throw_if_error("md5sum -- * > MD5SUM", cwd=d, shell=True)


def verify(outdir, par2_filename, prefix, num_volumes):
    dest_dirs = get_dest_dirs(outdir, prefix, num_volumes)

    for i, skip_dir in enumerate(dest_dirs):
        test_dir = tempfile.mkdtemp(prefix="verify_%d_" % (i+1), dir=outdir)

        print("Verifying restorability without volume %d" % (i+1))
        try:
            for link_dir in dest_dirs:
                if link_dir == skip_dir:
                    continue

                files = os.listdir(link_dir)
                for f in files:
                    src = os.path.abspath(os.path.join(link_dir, f))
                    dst = os.path.abspath(os.path.join(test_dir, f))
                    if not os.path.islink(dst):
                        os.symlink(src, dst)
        
            print("")
            return_code = subprocess.call(["par2", "verify", par2_filename], cwd=test_dir)
            if return_code == 0:
                print("\nSuccess, no recovery needed at all if volume %d fails." % (i+1))
            elif return_code == 1:
                print("\nSuccess, all files are recoverable if volume %d fails." % (i+1))
            else:
                print("\n")
                print_wrap("Failure, not all files are recoverable if volume %d fails. " % (i+1) +
                            "This usually happens either because you have chosen your redundancy too low "
                            "(try increasing it with the --redundancy option) or because your files are "
                            "too few and/or are of vastly different sizes. A workaround is to split your "
                            "large files.")
                raise SystemExit(1)
        finally:
            shutil.rmtree(test_dir)


def get_size_statistics(outdir, prefix, num_volumes):
    dest_dirs = get_dest_dirs(outdir, prefix, num_volumes)

    volume_sizes = []
    par2_sizes = []
    for d in dest_dirs:
        volume_sizes.append(0)
        par2_sizes.append(0)
        for f in os.listdir(d):
            size = os.path.getsize(os.path.join(d, f))
            volume_sizes[-1] += size
            if os.path.splitext(f)[-1] == ".par2":
                par2_sizes[-1] += size

    return volume_sizes, par2_sizes



def create_dir_if_not_exists_or_fail(directory):
    if os.path.exists(directory) and not os.path.isdir(directory):
        print_wrap("Specified directory %r is not a directory" % directory)
        raise SystemExit(1)
    if not os.path.exists(directory):
        try:
            os.mkdir(directory)
        except:
            print_wrap("Could not create directory %r" % directory)
            raise SystemExit(1)



def get_suitable_block_size(file_sizes):
    sizes = list(sorted(file_sizes.values()))
    total_size = sum(sizes)
    greatest_common_divider = sizes[0]
    
    x = sizes[len(sizes)/4]
    if x == sizes[-1] and total_size / x + len(sizes) < 20000:
        # At least 3/4 of the files are the same size.
        if x > 1024*1024:
            # Chose a value between 1 and 2 MB that doesn't cause too much overshoot (and thus padding
            # and wasted space).
            approximate_size_in_MB = x / (1024*1024)
            block_size = (x + approximate_size_in_MB - 1) // approximate_size_in_MB
        else:
            block_size = x
    else:
        block_size = max(sizes[len(sizes)/5] / 4, 4096)

    # Can't have more than about 20000 blocks
    while total_size / block_size + len(sizes) > 20000:
        block_size = min(block_size * 2, sizes[-1])

    # Must be multiple of 4
    if block_size % 4 != 0:
        block_size += 4 - (block_size % 4)

    return block_size


def get_total_num_blocks(file_sizes, block_size):
    total = 0
    for size in file_sizes:
        total += (size + block_size - 1) // block_size

    return total


def get_num_recovery_blocks(num_data_blocks, redundancy_fraction):
    """Return the number of blocks needed to make the fraction of blocks
    that are recovery blocks equal to redundancy_fraction"""

    return int(math.ceil(num_data_blocks * redundancy_fraction / (1 - redundancy_fraction)))



def check_integer_equal_or_greater(minimum):
    def check(n):
        try:
            value = int(n)
        except ValueError:
            raise argparse.ArgumentTypeError("%s is not an integer" % n)
        if value < minimum:
            raise argparse.ArgumentTypeError("%s is not an integer greater than or equal to %d" % (n, minimum))
        return value
    return check

def check_decimal_greater(minimum):
    def check(n):
        try:
            value = decimal.Decimal(n)
        except decimal.InvalidOperation:
            raise argparse.ArgumentTypeError("%s is not a decimal value" % n)
        if value < minimum:
            raise argparse.ArgumentTypeError("%s is not greater than %d" % (n, minimum))
        return value
    return check

def check_integer_in_interval(minimum, maximum):
    def check(n):
        try:
            value = int(n)
        except ValueError:
            raise argparse.ArgumentTypeError("%s is not an integer" % n)
        if not (minimum <= value <= maximum):
            raise argparse.ArgumentTypeError("%s is not an integer in range [%d,%d]" % (n, minimum, maximum))
        return value
    return check


def main():
    parser = argparse.ArgumentParser(description=(
        "Prepare all files in a directory to be written to a set of backup volumes (e.g. DVDs). "
        "Each file is optionally compressed and encrypted using 7zip and then a set of par2 files are created. "
        "The par2 files makes it possible to restore files even if one of the backup volumes is lost, "
        "if I/O errors are encountered, or if files are silently corrupted when reading back the data. "
        "This script will create one folder for each volume with approximately equal amount of data "
        "in each one. "))
        
    DEFAULT_REDUNDANCY = decimal.Decimal("1.1")

    parser.add_argument("-i", "--indir", metavar="DIR",
            help="Process the files in this directory. Default: current directory.")
    parser.add_argument("-o", "--outdir", metavar="DIR",
            help="Create the volume directories in this directory. Default: current directory.")
    parser.add_argument("-t", "--tmpdir", "--tempdir", metavar="DIR",
            help="The temporary directory to use. Default: output directory.")
    parser.add_argument("-p", "--prefix", metavar="PREFIX",
            help="The volume directories will get this name followed by underscore followed by a number. "
                    "Default: name of current directory followed by underscore.")
    parser.add_argument("-c", "--compress", action="store_true",
            help="Compress each file.")
    parser.add_argument("-e", "--encrypt", action="store_true",
            help="Encrypt each file (implies compression since the encryption will be done using 7zip). "
                    "You will be prompted for a password.")
    parser.add_argument("num_volumes", metavar="NUM_VOLUMES", type=check_integer_equal_or_greater(3),
            help="Number of volumes. Must be an integer greater or equal to 3.")
    parser.add_argument("-r", "--redundancy", metavar="NUM_VOLUMES", type=check_decimal_greater(0),
            help="Number of volumes to use for redundancy. Default: %s" % DEFAULT_REDUNDANCY)
    parser.add_argument("-f", "--force", action="store_true",
            help="Force creation even if the input files are not suitable to spread over the number "
                    "of volumes specified.")
    parser.add_argument("--block-size", metavar="BLOCK_SIZE", type=check_integer_in_interval(100, 200*1024*1024),
            help="Block size to pass on to par2. Default: Heuristically chosen.")
    parser.add_argument("--num-blocks", metavar="NUM_BLOCKS", type=check_integer_in_interval(2, 32600),
            help="Set the number of blocks for par2 to use. Default: Heuristically chosen.")
    parser.add_argument("--memory", metavar="MEGABYTES", type=check_integer_in_interval(1, 1000*1000),
            help="Number of megabytes of memory par2 may use. Default: Let par2 decide for itself.")
    parser.add_argument("--no-verify", action="store_true",
            help="Do not invoke par2 to verify that a missing volume does not lead to data loss.")

    args = parser.parse_args()

    # encryption implies compression
    compress = args.compress or args.encrypt

    outdir = args.outdir or os.getcwd()
    indir = args.indir or os.getcwd()
    prefix = args.prefix or (os.path.split(os.getcwd())[-1] + " ")
    redundancy = args.redundancy or DEFAULT_REDUNDANCY

    if redundancy > args.num_volumes - 1:
        print_wrap("Can't dedicate that many volumes to redundancy, at least one must contain the actual data.")
        raise SystemExit(1)
    
    if args.num_blocks is not None and args.block_size is not None:
        print_wrap("Can't set both block size and number of blocks.")
        raise SystemExit(1)

    infiles_paths = sorted([os.path.join(indir, f) for f in filter_infiles(os.listdir(indir))])
    infiles_paths = [f for f in infiles_paths if os.path.isfile(f)]

    if infiles_paths == []:
        print("No input files")
        raise SystemExit(1)

    if len(infiles_paths) < args.num_volumes - redundancy and not args.force:
        print_wrap(
                "Not enough input files to spread out over %d volumes. I suggest you use 7zip to create "
                "volumes out of the data, e.g. '7z a -v<volume_size> *'. You can use the option --force "
                "to still go ahead with the creation but the results will most likely not be what you want."
            )
        raise SystemExit(1)

    MAX_NUM_FILES = 6000

    if len(infiles_paths) > MAX_NUM_FILES:
        print_wrap(
                "Can't process %d files at once. You must split them up into " % len(infiles_paths) +
                "directories containing no more than %d files each." % MAX_NUM_FILES
            )
        raise SystemExit(1)

    for filepath in infiles_paths:
        if os.path.splitext(filepath) == ".par2" and not args.force:
            print_wrap(
                    "The input directory already contains .par2 files. You probably want to delete "
                    "them and start over instead of creating another set of .par2 files protecting "
                    "the old set. You can use the option --force to continue anyway."
                )
            raise SystemExit(1)


    input_filesizes = {f: os.path.getsize(f) for f in infiles_paths}

    last_bin_size_fraction = redundancy % 1 or 1
    bins, bin_sizes = distribute_files_uniformly(input_filesizes,
                                                    args.num_volumes - int(math.floor(redundancy)),
                                                    last_bin_size_fraction)
    adjusted_bin_sizes = bin_sizes[:-1] + [int(bin_sizes[-1] / last_bin_size_fraction)]

    total_file_sizes = sum(input_filesizes.values())
    average_volume_size = float(sum(adjusted_bin_sizes)) / len(adjusted_bin_sizes)
    unevenness = max(adjusted_bin_sizes) / average_volume_size
    if unevenness > args.num_volumes - 0.05 and not args.force:
        print_wrap(
                "The sizes of the input files %s" % ("(before compression) " if args.compression else "") +
                "is uneven and it will probably not be possible to restore the files if one of the volumes "
                "fail. To continue anyway you need to use the option --force."
            )
        raise SystemExit(1)


    password = None
    if args.encrypt:
        password = raw_input("Choose password: ")
        
        if password == "":
            print_wrap("Can't have empty password. Use without the --encrypt switch to run without encryption.")
            raise SystemExit(1)

        valid_password_regexp = r"""^[a-zA-Z0-9!@#$%^&*+=,.\-_\\/()|;: ~<>?"'{}[\]]+$"""
        if not re.match(valid_password_regexp, password):
            print_wrap("To prevent problems with command lines and differences in escaping and such, only "
                        "passwords matching the following regular expression are allowed: %r" % valid_password_regexp)
            raise SystemExit(1)

        verify_password = raw_input("Verify password: ")

        if password != verify_password:
            print_wrap("Passwords don't match.")
            raise SystemExit(1)

    start_time = time.time()

    tmp_parent_dir = args.tmpdir or outdir
    create_dir_if_not_exists_or_fail(tmp_parent_dir)
    
    tmpdir = tempfile.mkdtemp(prefix="%s_"%prefix, suffix="_tmp", dir=tmp_parent_dir)
    try:
        assert os.listdir(tmpdir) == []


        if compress:
            files_to_be_archived = compress_files(infiles=infiles_paths,
                                        outdir=tmpdir,
                                        tmpdir=tmpdir,
                                        password=password)
        else:
            files_to_be_archived = copy_files(infiles=infiles_paths, outdir=tmpdir)
        
        compression_copy_time = time.time()
        
        tmpdir_contents = sorted([os.path.join(tmpdir, f) for f in os.listdir(tmpdir)])
        assert tmpdir_contents == sorted(files_to_be_archived), "%r" % list(itertools.izip_longest(
                tmpdir_contents, sorted(files_to_be_archived)))

        file_sizes = {f: os.path.getsize(f) for f in files_to_be_archived}

        redundancy_fraction = fractions.Fraction(redundancy) / args.num_volumes
        
        block_size = args.block_size
        if args.num_blocks is None and block_size is None:
            block_size = get_suitable_block_size(file_sizes)
            print_wrap("Using block size %d" % block_size)
        
        if block_size is not None:
            total_blocks = get_total_num_blocks(file_sizes.values(), block_size)
            num_recovery_blocks = get_num_recovery_blocks(total_blocks, redundancy_fraction)
        else:
            num_recovery_blocks = get_num_recovery_blocks(args.num_blocks, redundancy_fraction)

        par2_filename = "%s.par2" % prefix.strip().strip("_")
        create_par2_files(tmpdir, par2_filename, num_recovery_blocks=num_recovery_blocks,
                block_size=block_size, num_blocks=args.num_blocks, memory=args.memory)

        par2_creation_time = time.time()

        create_dir_if_not_exists_or_fail(outdir)

        move_files_to_destination_dir(srcdir=tmpdir, destdir=outdir, par2_filename=par2_filename,
                prefix=prefix, num_volumes=args.num_volumes)

    finally:
        shutil.rmtree(tmpdir)

    create_md5_sums(inoutdir=outdir, prefix=prefix, num_volumes=args.num_volumes)

    md5sum_time = time.time()

    if not args.no_verify:
        verify(outdir, par2_filename, prefix, args.num_volumes)

    verify_time = time.time()

    print("")
    print("Success, everything done.")
    print("")
    print("Time statistics:")
    print(("Compression: " if compress else "Initial file copy: ") +
            "%.1f seconds" % (compression_copy_time - start_time))
    print("Par2 creation: %.1f seconds" % (par2_creation_time - compression_copy_time))
    print("MD5 sum: %.1f seconds" % (md5sum_time - par2_creation_time))
    print("Verification: %.1f seconds" % (verify_time - md5sum_time))

    volume_sizes, par2_sizes = get_size_statistics(outdir, prefix, args.num_volumes)
    print("")
    print("Volume sizes:")
    print("\n".join(create_bar_chart(volume_sizes)))
    print("")
    print_wrap(("Par2 recovery files are %.1f %% of the output (ideal for a redundancy "
                "of %s volumes out of %d would be %.1f %%)") % (
            100.0 * sum(par2_sizes) / sum(volume_sizes),
            redundancy,
            args.num_volumes,
            100.0 * float(redundancy) / args.num_volumes))
    print("")


if __name__ == "__main__":
    main()

