import testinfra
import os, pwd, grp
import logging
import tempfile
import pathlib
import sherlockfog
import paramiko

global logger
global testinfra_h

def list_netns(h=None):
    global testinfra_h
    if h is None:
        h = testinfra_h
    return h.run('ip netns list').stdout.splitlines()

def list_cgroups(h=None):
    global testinfra_h
    if h is None:
        h = testinfra_h
    return [os.path.basename(x) for x in h.run('cd /sys/fs/cgroup/ && find . -maxdepth 1 -type d').stdout.splitlines() if x != '.' and os.path.basename(x).startswith(args.node_name_prefix)]

def list_pids(h=None):
    global testinfra_h
    if h is None:
        h = testinfra_h
    return [x.strip() for x in h.run('ps ax -o pid=').stdout.splitlines()]

def run_in_netns_ssh(h, ns, cmd):
    return h.run("ip netns exec {0} ssh 127.0.0.1 '{1}'".format(ns, cmd))

def get_iface_mac_from_netns(h, ns, iface, family='ether'):
    return check_output_netns(h, ns, "ip l show dev {0} | grep link/{1}".format(iface, family)).split()[1]

def get_iface_cidr_from_netns(h, ns, iface, family='inet'):
    return check_output_netns(h, ns, "ip a s dev {0} | grep -E '{1} '".format(iface, family)).split()[1]

def get_iface_addr_from_netns(h, ns, iface, family='inet'):
    return get_iface_cidr_from_netns(h, ns, iface, family=family).split('/')[0]

def ensure_env_is_clean(h=None):
    global testinfra_h
    if h is None:
        h = testinfra_h

    # delete netns
    for ns in list_netns(h):
        h.run("ip netns del {0}".format(ns))
    list_netns(h)

    # delete cgroups
    for cg in list_cgroups(h):
        h.run('cgdelete -r cpu,cpuset:{0}'.format(cg))

    # kill dangling sshd's
    h.run("ps ax | grep UseDNS=no | grep ssh | awk '{ print $1 }' | xargs kill")

def check_host_reachable_from_ns(h, ns, dest):
    return run_in_netns_ssh(h, ns, 'ping -c 1 {0} >/dev/null && echo $?'.format(dest)).stdout.rstrip(os.linesep) == '0'

def check_output_netns(h, ns, cmd):
    return run_in_netns_ssh(h, ns, cmd).stdout.rstrip(os.linesep)

def check_ip_properly_set_in_netns(hname, ifname, hobj, h=None):
    if h is None:
        h = globals()['testinfra_h']
    return get_iface_addr_from_netns(h, hname, ifname) == getattr(hobj, ifname).ip

def no_netns_in_list_is_up(h, l):
    ns_list = list_netns(h)
    for ns in l:
        if ns in ns_list:
            return False
    return True

def define_host(name, args=None):
    global ip
    if args is None:
        args = globals()['args']
    return sherlockfog.Host(name, ip, args=args)

def init_host_pool():
    sherlockfog.RealHostPool.reset()
    topo0 = sherlockfog.Topo()
    return sherlockfog.HostPool('lan0',
            base=args.base_prefix,
            use_adm=False,
            args=args,
            topo=topo0)

def create_tmpfile(content=None, mode=None):
    tmpfile = tempfile.NamedTemporaryFile('w')
    if content is not None:
        print(content, file=tmpfile.file)
    if mode is not None:
        pathlib.Path(tmpfile.name).chmod(mode)
    return tmpfile

def drop_privileges(uid_name='nobody', gid_name='nogroup'):
    if os.getuid() != 0:
        return False

    # Get the uid/gid from the name
    running_uid = pwd.getpwnam(uid_name).pw_uid
    running_gid = grp.getgrnam(gid_name).gr_gid

    # Remove group privileges
    os.setgroups([])

    # Try setting the new uid/gid
    os.setgid(running_gid)
    os.setuid(running_uid)

    # Ensure a very conservative umask
    os.umask(0o077)

    return True

# setup default config arguments
ip = os.environ['IP']
assert ip is not None
testinfra_h = testinfra.get_host('paramiko://root@{0}'.format(ip))
_args = {
    'node_name_prefix': 'n',
    'base_prefix': '10.67.0.0/16',
    'dry_run': False,
    'cpu_exclusive': False,
    'use_iface_prefix': False,
    'routing_algo': 'shortest_path_compressed',
    'debug': False,
    'geneve_tunnels': True,
    'max_parallel_workers': 1,
    'parallel_vhost_creation': False,
    'docker': False,
    'docker_image': None,
    'rest_api': True,
    'rest_api_port': 8888,
    'adm_iface_addr': None,
    'use_adm_ns': False,
    'expose_adm': False,
}

class A(object):
    def __init__(self):
        self.__dict__ = { k: v for k, v in _args.items() }
    def new(self):
        return type(self)()
args = A()

# disable logging messages from sherlockfog impl
logger = sherlockfog.init_logging(args, silent=True)
logging.disable()
