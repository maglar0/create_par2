# create_par2.py

## Rationale

Let's say you have 10,000 photos that you want to burn to DVD. Since you want to store them for a long time you of course want to have some redundancy so that you can still get your photos back if some of the DVDs are damaged or has read errors 10 years from now. You can store the photos many times over to lessen the risk of being impacted by a bad disc, but there is a more efficient way - Error Correcting Codes (ECC).

[par2](https://github.com/Parchive/par2cmdline) is an open source program to create Error Correcting Codes, but it is primarily designed to aid in transferring binary files over Usenet, not for burning DVDs. This script helps in creating suitable par2 files and spreading your files over a number of DVDs. You can specify the number of DVDs you want and the amount of space (in DVDs) that you want to devote to ECCs. E.g. you might want to spread your files out over 9 DVDs of which 1.5 are ECC. That way you will still be able to recover your files if one DVD fails and you encounter a few read errors on the others.

The script also lets you compress and encrypt your files using [7zip](http://www.7-zip.org/) if you want.

An important aspect of using this script for the creation of your DVDs is that you do **not** need it at the time of your recovery. If you don't encounter any read errors you can use your files without any particular software what so ever, or using just 7zip if you chose to compress/encrypt your files. If you do encounter read errors, you will need par2. Both par2 and 7zip are widely used open source software and thus likely to be available for a long time in the future. You can even burn the source code together with your data files if you wish.

## Example Use

To use the script, you will need to have par2 and optionally 7zip installed on your computer and available in your path. You also need the program [md5sum](https://en.wikipedia.org/wiki/Md5sum).

Put some files (e.g. 1000 photos) in a directory, cd to the directory, and type `create_par2.py 7`. The script will create a subdirectory itself containing 7 subdirectories, each of them containing the files you should put on a separate media (e.g. DVD or Bluray). The files in each subdirectory will occupy about the same amount of space, and about 110 % of the average subdirectory size (i.e. 1.1/7 = 15.7 % of the total size) will be devoted to ECC in par2 files, but they will be spread out into different directories.


## Gotchas

It takes a long time to create ECC and verify that they work. For a couple of DVDs worth of data you are probably looking at an overnight job on a fast computer.

The encryption will not protect file metadata such as file name, file size, or creation time. If you want to do that you need to do it as a separate step before invoking the script, e.g. with 7zip or [GPG](https://www.gnupg.org/)

If you just have a few files or files with very different sizes (e.g. one 200 MB .avi file and ten 5 MB .jpgs), you will not be able to spread them out over a couple of DVDs with a working ECC, unless you create a ridiculously huge amount of ECC. The script will refuse to continue in that case.