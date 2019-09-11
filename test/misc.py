import testinfra
import os

def list_netns(h):
    return h.run('ip netns list').stdout.splitlines()

def list_cgroups(h):
    return [os.path.basename(x) for x in h.run('cd /sys/fs/cgroup/cpuset && find . -maxdepth 1 -type d').stdout.splitlines() if x != '.']

def list_pids(h):
    return [x.strip() for x in h.run('ps ax -o pid=').stdout.splitlines()]

def run_in_netns_ssh(h, ns, cmd):
    return h.run("ip netns exec {0} ssh 127.0.0.1 '{1}'".format(ns, cmd))

def ensure_env_is_clean(h):
    # delete netns
    for ns in list_netns(h):
        h.run("ip netns del {0}".format(ns))

    # delete cgroups
    for cg in list_cgroups(h):
        h.run('cgdelete -r cpu,cpuset:{0}'.format(cg))

    # kill dangling sshd's
    h.run("ps ax | grep UseDNS=no | grep ssh | awk '{ print $1 }' | xargs kill")

def check_host_reachable_from_ns(h, ns, dest):
    return run_in_netns_ssh(h, ns, 'ping -c 1 {0} >/dev/null && echo $?'.format(dest)).stdout.rstrip(os.linesep) == '0'

def check_output_netns(h, ns, cmd):
    return run_in_netns_ssh(h, ns, cmd).stdout.rstrip(os.linesep)

def no_netns_in_list_is_up(h, l):
    ns_list = list_netns(h)
    for ns in l:
        if ns in ns_list:
            return False
    return True

ip = os.environ['IP']
assert ip is not None
testinfra_h = testinfra.get_host('paramiko://root@{0}'.format(ip))
_args = {
    'base_prefix': '10.67.0.0/16',
    'dry_run': False,
    'cpu_exclusive': False,
    'use_iface_prefix': False,
    'routing_algo': 'shortest_path',
}
class A(object):
    def __init__(self):
        self.__dict__ = _args
args = A()
