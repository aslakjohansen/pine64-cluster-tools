#!/usr/bin/env python3

from sys import argv, exit
import requests
from subprocess import Popen, STDOUT, PIPE
from os import mkdir, unlink
from os.path import exists
from shutil import copy2 as copy_file

'''
(c) Aslak Johansen

Sources:
- https://forum.pine64.org/showthread.php?tid=10432
- https://forum.armbian.com/topic/17333-unable-to-boot-focal-or-buster-images-on-sopine-clusterboard/
'''

debug = False

###############################################################################
####################################################################### asserts

def assert_param_count (count):
    if type(count)==int: count = [count]
    if not len(argv) in map(lambda v: v+2, count):
        print('Wrong number of parameters for command "%s": %u' % (command, len(argv)))
        print_help()
        exit()

def assert_root ():
    if system('whoami').strip()!='root':
        print('Must be a privileged user to continue')
        exit()

###############################################################################
####################################################################### helpers

def system (command, err=STDOUT, out=PIPE):
    if debug: print(command)
    p = Popen(command, shell=True, stderr=err, stdout=out)
    output = p.communicate()[0]
    return output.decode('utf-8')

def read_file (filename):
    with open(filename) as fo:
        return fo.readlines()

def write_file (filename, lines):
    with open(filename, 'w') as fo:
        fo.writelines(lines)

def print_help():
    hosts = ','.join(map(lambda i: 'andes%s:192.168.1.1%s'%(i,i), range(7)))
    print('Syntax: %s COMMAND PARAMETERS' % argv[0])
    print('        %s download URL' % argv[0])
    print('        %s extract DOWNLOADED_FILE' % argv[0])
    print('        %s mount UNCOMPRESSED_DOWNLOAD MOUNTPOINT' % argv[0])
    print('        %s update MOUNTPOINT HOSTNAME2IP_MAP CURRENT_INDEX_IN_MAP NETMASK GATEWAY DNS' % argv[0])
    print('        %s umount MOUNTPOINT' % argv[0])
    print('        %s list' % argv[0])
    print('        %s flash IMAGE DEVICE' % argv[0])
    print('')
    print('Examples: %s download https://mirrors.dotsrc.org/armbian-dl/pine64so/archive/Armbian_21.05.1_Pine64so_focal_current_5.10.34.img.xz' % argv[0])
    print('          %s extract Armbian_21.05.1_Pine64so_focal_current_5.10.34.img.xz' % argv[0])
    print('          %s mount Armbian_21.05.1_Pine64so_focal_current_5.10.34.img mountpoint' % argv[0])
    print('          %s update mountpoint %s 0 255.255.255.0 192.168.1.1 192.168.1.1' % (argv[0], hosts))
    print('          %s umount mountpoint' % argv[0])
    print('          %s list' % argv[0])
    print('          %s flash Armbian_21.05.1_Pine64so_focal_current_5.10.34.img /dev/sdd' % argv[0])
    print('')
    print('You probably want to run the commands in the above order.')
    print('')
    print('WARNING: Make sure you point to the right device when issuing the "flash command".')
    print('         It will override the device. Use "list" command to inspect available devices.')

###############################################################################
###################################################################### commands

def command_download (url):
    print('download %s' % (url))
    filename = url.split('/')[-1]
    r = requests.get(url, allow_redirects=True)
    with open(filename, 'wb') as fo:
        fo.write(r.content)

def command_extract (path):
    print('extract %s' % (path))
    system('unxz -k %s' % path)

def command_mount (image, mountpoint):
    print('mount %s %s' % (image, mountpoint))
    
    # get offset
    output = system('/sbin/fdisk -l %s' % image)
    for line in output.split('\n'):
        if line.startswith('Sector size (logical/physical):'):
            sectorsize = int(line.split(' ')[-5])
        elif line.startswith(image):
            sectoroffset = int(list(filter(lambda e: e!='', line.split(' ')))[-6])
    offset = sectoroffset*sectorsize
    
    # guard: mountpoint hasn't been created
    if not exists(mountpoint):
        mkdir(mountpoint)
    
    system('sudo mount -o loop,rw,sync,offset=%u %s %s' % (offset, image, mountpoint))

def command_update_dhcp (mountpoint, ip, netmask):
    rfilename = '%s/etc/dhcp/dhclient.conf'     % mountpoint # real
    bfilename = '%s/etc/dhcp/dhclient.conf.bk0' % mountpoint # backup
    
    ilines = read_file(rfilename)
    olines = []
    
    # copy relevant lines
    inside = False
    skipped = False
    for line in ilines:
        if line.strip()=='alias {':
            inside = True
            skipped = True
        elif line.strip()=='}':
            inside = False
        elif not inside:
            olines.append(line)
    
    # add extra lines
    olines.append('alias {\n')
    olines.append('  interface "eth0";\n')
    olines.append('  fixed-address %s;\n' % ip)
    olines.append('  option subnet-mask %s;\n' % netmask)
    olines.append('}\n')
    
    # make backup of original
    if not skipped:
        print('NOTICE: No previous update to %s detected. Creating backup %s ...' % (rfilename, bfilename))
        copy_file(rfilename, bfilename)
    
    # write back updated file
    write_file(rfilename, olines)

def command_update_dtb (mountpoint):
    rfilename = '%s/boot/dtb/allwinner/sun50i-a64-sopine-baseboard.dtb'     % mountpoint # real
    bfilename = '%s/boot/dtb/allwinner/sun50i-a64-sopine-baseboard.dtb.bk0' % mountpoint # backup
    tfilename = '%s/boot/dtb/allwinner/sun50i-a64-sopine-baseboard.dts'     % mountpoint # temporary
    
    # make sure backup exists
    if not exists(bfilename):
        print('NOTICE: No previous update to %s detected. Creating backup %s ...' % (rfilename, bfilename))
        copy_file(rfilename, bfilename)
    
    # decode
    system('dtc -I dtb -O dts -o %s %s' % (tfilename, rfilename))
    
    # init lists of lines
    ilines = read_file(tfilename)
    olines = []
    
    # build new list of lines
    extraline = '\t\t\tallwinner,tx-delay-ps = <0x1f4>;'
    for line in ilines:
        if not line.strip()==extraline:
            olines.append(line)
        if line.strip()=='phandle = <0x88>;':
            olines.append(extraline)
    
    # override temporary file with update
    write_file(tfilename, olines)
    
    # encode
    system('dtc -O dtb -o %s -b 0 %s' % (rfilename, tfilename))
    
    # cleanup
    unlink(tfilename)

def command_update_hosts (mountpoint, hosts):
    def add_lines (olines, insert_initial):
        if insert_initial:
            olines.append('\n')
        olines.append('%s\n' % headerline)
        for hostname in hosts:
            olines.append('%s %s\n' % (hosts[hostname], hostname))
    
    rfilename = '%s/etc/hosts'     % mountpoint # real
    bfilename = '%s/etc/hosts.bk0' % mountpoint # backup
    
    # make sure backup exists
    if not exists(bfilename):
        print('NOTICE: No previous update to %s detected. Creating backup %s ...' % (rfilename, bfilename))
        copy_file(rfilename, bfilename)
    
    # init lists of lines
    ilines = read_file(rfilename)
    olines = []
    
    # build new list of lines
    headerline = '# autogenerated table'
    state = 'outside'
    inserted = False
    for line in ilines:
        if line.strip()==headerline:
            add_lines(olines, False)
            inserted = True
            state = 'inside'
        elif line.strip()=='':
            state = 'outside'
        
        if state=='outside':
            olines.append(line)
    
    # insert at the end if no possibility has presented itself
    if not inserted:
        add_lines(olines, True)
    
    # override file
    write_file(rfilename, olines)

def command_update_nm (mountpoint):
    links = [
        '%s/etc/systemd/system/multi-user.target.wants/NetworkManager.service' % mountpoint,
        '%s/etc/systemd/system/network-online.target.wants/NetworkManager-wait-online.service' % mountpoint,
        '%s/etc/systemd/system/dbus-org.freedesktop.nm-dispatcher.service' % mountpoint,
    ]
    
    for link in links:
        if exists(link):
            unlink(link)

def command_update_hostname (mountpoint, hostname):
    rfilename = '%s/etc/hostname'     % mountpoint # real
    bfilename = '%s/etc/hostname.bk0' % mountpoint # backup
    
    # make sure backup exists
    if not exists(bfilename):
        print('NOTICE: No previous update to %s detected. Creating backup %s ...' % (rfilename, bfilename))
        copy_file(rfilename, bfilename)
    
    # build new list of lines
    olines = ['%s\n' % hostname]
    
    # override file
    write_file(rfilename, olines)

def command_update_interfaces (mountpoint, ip, netmask, gateway, dns):
    rfilename = '%s/etc/network/interfaces'     % mountpoint # real
    bfilename = '%s/etc/network/interfaces.bk0' % mountpoint # backup
    
    # make sure backup exists
    if not exists(bfilename):
        print('NOTICE: No previous update to %s detected. Creating backup %s ...' % (rfilename, bfilename))
        copy_file(rfilename, bfilename)
    
    # build new list of lines
    olines = list(map(lambda line: '%s\n' % line, [
        'auto eth0',
        'allow-hotplug eth0',
        'iface eth0 inet static',
        '    address %s' % ip,
        '    netmask %s' % netmask,
        '    gateway %s' % gateway,
        '    dns-nameservers %s' % dns,
    ]))
    
    # override file
    write_file(rfilename, olines)

def command_update (mountpoint, hosts, hostname, netmask, gateway, dns):
    print('update %s %s %s %s %s %s' % (mountpoint, hosts, hostname, netmask, gateway, dns))
    assert_root()
    ip = hosts[hostname]
    command_update_dhcp(mountpoint, ip, netmask)
    command_update_dtb(mountpoint)
    command_update_hosts(mountpoint, hosts)
    command_update_nm(mountpoint)
    command_update_hostname(mountpoint, hostname)
    command_update_interfaces(mountpoint, ip, netmask, gateway, dns)
    command_update_resolveconf(mountpoint, dns)

def command_umount (mountpoint):
    print('umount %s' % (mountpoint))
    system('sudo umount %s' % mountpoint)

def command_list ():
    print('list' % ())
    ds = system('ls /dev/sd?').split('\n')
    print('Potentials:')
    for d in sorted(ds):
        if d=='': continue
        print('- %s (%s partitions)' % (d, system('ls -l %s? | wc -l'%d, err=PIPE).strip()))

def command_flash (image, device):
    print('flash %s %s' % (image, device))
    assert_root()
    system('sudo dd bs=4M if=%s of=%s conv=fsync' % (image, device))
    system('sudo sync')
    system('sudo eject %s' % device)

###############################################################################
########################################################################## main

# guard: no command
if len(argv) < 2:
    print_help()
    exit()
command = argv[1]

# dispatch
if   command=='download':
    assert_param_count(1)
    command_download(argv[2])
elif command=='extract':
    assert_param_count(1)
    command_extract(argv[2])
elif command=='mount':
    assert_param_count(2)
    command_mount(argv[2], argv[3])
elif command=='update':
    assert_param_count(6)
    pairs = list(map(lambda pair: pair.split(':'), argv[3].split(',')))
    table = {}
    for key, value in pairs:
        table[key] = value
    command_update(argv[2], table, pairs[int(argv[4])][0], argv[5], argv[6], argv[7])
elif command=='umount':
    assert_param_count(1)
    command_umount(argv[2])
elif command=='list':
    assert_param_count(0)
    command_list()
elif command=='flash':
    assert_param_count(2)
    command_flash(argv[2], argv[3])
else:
    print('Unknown command "%s"' % command)
    print_help()
    exit()

# indicate success
print('done')
