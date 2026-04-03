#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, re, sys, argparse, psutil, logging, socket
import subprocess
import paramiko

global logger
logger = None

def init_logging(args):
    global logger
    logger = logging.getLogger(__name__)
    level = logging.INFO
    if args.debug:
        level = logging.DEBUG
    logger.setLevel(level)
    # Log to stderr, inventory output goes to stdout
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(level)
    formatter = logging.Formatter('[%(asctime)s] %(levelname)s %(message)s', datefmt='%c')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger

def load_real_host_list(real_host_list):
    l = set([])
    with open(real_host_list, 'r') as rhl:
        for x in rhl:
            x = x.rstrip('\n')
            if len(x) > 0:
                l.add(x)
    return l

def find_process_re(pgname_re, search_re=None):
    procs = []
    for proc in psutil.process_iter(['name', 'cmdline']):
        if re.match(pgname_re, proc.info['name']) is not None:
            if search_re is None:
                procs.append(proc)
                continue
            for argv in proc.info['cmdline']:
                    if re.match(search_re, argv) is not None:
                        procs.append(proc)
                        break
    return procs

def get_hostname():
    return socket.gethostname()

def ssh_check_command(host, cmd):
    client = paramiko.client.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.load_system_host_keys()
    client.connect(host, username='root')
    _, stdout, _ = client.exec_command(cmd)
    return stdout

def get_remote_hostname(host):
    stdout = ssh_check_command(host, 'hostname')
    return stdout.read().decode('utf-8').rstrip(os.linesep)

def lookup_ip_by_iface(iface):
    o = subprocess.check_output('ip addr show {}'.format(iface))
    for line in o.splitlines():
        m = re.match(r'^[\t ]*inet (\d+\.\d+\.\d+\.\d+)/(\d+.*) brd (\d+\.\d+\.\d+\.\d+).*$', line)
        if m is not None:
            return m.group(1)
    # Return localhost if not found
    return '127.0.0.1'

def get_default_route():
    o = subprocess.check_output('ip route')
    for line in o.splitlines():
        m = re.match(r'^default via \d+\.\d+\.\d+.\d+ dev (.*?) .*$', line)
        if m is not None:
            return lookup_ip_by_iface(m.group(1))
    # Return localhost if not found
    return '127.0.0.1'

def build_host_map(real_host_list):
    my_hostname = get_hostname()
    host_map = {'physnodes': {}, 'monitor': {my_hostname: '127.0.0.1'}}
    # Build physnodes map
    for host in real_host_list:
        logger.info('Looking up hostname for real host {} ... '.format(host))
        host_map['physnodes'][get_remote_hostname(host)] = host
    # Set monitor IP 
    if my_hostname in host_map['physnodes']:
        host_map['monitor'][my_hostname] = host_map['physnodes'][my_hostname]
    else:
        host_map['monitor'][my_hostname] = get_default_route()
    # Build all map
    host_map['all'] = {}
    for name, host in host_map['physnodes'].items():
        host_map['all'][name] = host
    for name, host in host_map['monitor'].items():
        host_map['all'][name] = host
    return host_map

def write_ansible_ini_inventory(host_map, output=None):
    to_close = False
    if output is None:
        output = sys.stdout
    else:
        output = open(output, 'w')
        to_close = True

    print('[all]', file=output)
    for name, host in host_map['all'].items():
        print('{} ansible_host={}'.format(name, host), file=output)
    
    print('\n[monitor]', file=output)
    for h in host_map['monitor'].keys():
        print(h, file=output)

    print('\n[physnodes]', file=output)
    for h in host_map['physnodes'].keys():
        print(h, file=output)

    if to_close:
        output.close()

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Generate inventory file for Ansible playbooks')
    ap.add_argument('--output',
            type=str,
            action='store',
            nargs='?',
            help='Output file')
    ap.add_argument('--debug',
            action='store_true',
            help='Debug mode')
    ap.add_argument('--real-host-list',
            type=str,
            action='store',
            nargs='?',
            help='Real host list from SherlockFog (overrides running SherlockFog)')
    ap.set_defaults(output=None, debug=False, real_host_list=None)
    args = ap.parse_args()

    init_logging(args)
    real_host_list = args.real_host_list
    output = args.output

    if real_host_list:
        real_host_list = load_real_host_list(args.real_host_list)
    else:
        try:
            # Filter out processes that include the sherlockfog(.py), but have no children.
            # This avoids including processes that launch sherlockfog (such as sudo).
            sherlockfog = [proc for proc in find_process_re('.*', search_re='^.*?sherlockfog((\.py)|())$') if len(proc.children()) == 0][0]
        except IndexError:
            logger.error('SherlockFog not found, bailing out ...')
            sys.exit(1)

        # Parse --real-host-list from SherlockFog's cmdline.
        args, unknown = ap.parse_known_args(sherlockfog.cmdline())
        cwd = sherlockfog.cwd()
        try:
            real_host_list = load_real_host_list(os.path.join(cwd, args.real_host_list))
        except TypeError:
            logger.error('Detected instance of SherlockFog does not set --real-host-list, please pass option to generator.')
            sys.exit(1)

    host_map = build_host_map(real_host_list)
    write_ansible_ini_inventory(host_map, output)
