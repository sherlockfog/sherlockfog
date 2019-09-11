import pytest
import sherlockfog

from misc import *

def test_create_destroy_host():
    '''
    Check if it's possible to create a Host object with basic connectivity and destroy it:

       # network container (netns) with the same name as the vhost
       # cgroup (cpuset) with the same name as the vhost
       # reachable via ssh (from within the netns)
       # UTS namespace with the same name as the vhost (reachable via ssh)
       # netns/cgroup/sshd must be gone after close()
    '''
    ensure_env_is_clean(testinfra_h)
    ns = 'n0'

    h = sherlockfog.Host(ns, ip)

    assert ns in list_netns(testinfra_h)
    assert ns in list_cgroups(testinfra_h)

    sshd_pid = h.service_pids()[0]
    assert sshd_pid in list_pids(testinfra_h)

    assert check_host_reachable_from_ns(testinfra_h, ns, '127.0.0.1')
    assert check_output_netns(testinfra_h, ns, 'hostname') == ns

    h.close()

    assert ns not in list_netns(testinfra_h)
    assert ns not in list_cgroups(testinfra_h)
    assert sshd_pid not in list_pids(testinfra_h)
