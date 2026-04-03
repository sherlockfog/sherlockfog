import pytest
import sherlockfog
import random

from misc import *

def test_define_duplicate_host():
    ensure_env_is_clean()

    h = define_host('n0')

    with pytest.raises(IOError):
        define_host('n0')

    h.close()

def test_create_destroy_host():
    '''Test if it is possible to create a Host object with basic connectivity and destroy it:
       # network container (netns) with the same name as the vhost
       # cgroup (cpuset) with the same name as the vhost
       # reachable via ssh (from within the netns)
       # UTS namespace with the same name as the vhost (reachable via ssh)
       # netns/cgroup/sshd must be gone after close()
    '''
    global testinfra_h
    ensure_env_is_clean()
    ns = 'n0'

    h = define_host(ns)

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

def test_exec_host():
    '''Test if it is possible to create a host and execute some commands on it.'''
    ensure_env_is_clean()

    h = define_host('n0')

    assert h.exec_('pwd', ns='n0') == os.getenv('HOME')
    assert h.get_exec_exit_code() == 0

    with pytest.raises(IOError):
        h.exec_('ls /this_is_a_non_existant_path/this_is_a_non_existant_file_{0}'.format(random.randint(1, 10000)), ns='n0')

    h.close()

def test_create_host_veth():
    '''Test if it is possible to create a virtual network interface on a host'''
    global args
    assert args.base_prefix == '10.67.0.0/16'
    ensure_env_is_clean()

    ns = 'n0'
    h = define_host(ns)

    new_iface_name = h.new_iface_name()
    assert new_iface_name == 'veth0'

    veth_h = h.register_veth(ns, h.real_default_iface.name, 'veth0', '10.67.0.1/30', now=True)

    assert get_iface_cidr_from_netns(testinfra_h, ns, 'veth0') == str(veth_h)
    assert get_iface_mac_from_netns(testinfra_h, ns, 'veth0') == veth_h.mac
    assert check_host_reachable_from_ns(testinfra_h, ns, '10.67.0.1')

    assert h.veth0 == h.default_iface
    assert h.veth0.ip == '10.67.0.1'

    h.close()

def test_create_two_connected_hosts_p2p():
    global args
    assert args.base_prefix == '10.67.0.0/16'
    ensure_env_is_clean()

    n0 = define_host('n0')
    n1 = define_host('n1')

    iface_name_n0 = n0.new_iface_name()
    iface_name_n1 = n1.new_iface_name()

    veth_n0 = n0.register_veth('n0', n0.real_default_iface.name, iface_name_n0, '10.67.0.1/30', now=True)
    veth_n1 = n0.register_veth('n1', n1.real_default_iface.name, iface_name_n1, '10.67.0.2/30', now=True)

    n0.arp('add', veth_n1.ip, veth_n1.mac, ns='n0')
    n0.exec_batch_commit() # FIXME
    n1.arp('add', veth_n0.ip, veth_n0.mac, ns='n1')
    n1.exec_batch_commit() # FIXME

    assert check_host_reachable_from_ns(testinfra_h, 'n0', '10.67.0.2')

    n0.close()
    n1.close()

def test_create_three_connected_hosts_line_topo():
    global args
    assert args.base_prefix == '10.67.0.0/16'
    ensure_env_is_clean()

    n0 = define_host('n0')
    n1 = define_host('n1')
    n2 = define_host('n2')

    iface_name_n0_n1 = n0.new_iface_name()
    iface_name_n1_n0 = n1.new_iface_name()
    iface_name_n1_n2 = n1.new_iface_name()
    iface_name_n2_n1 = n2.new_iface_name()

    veth_n0_n1 = n0.register_veth('n0', n0.real_default_iface.name, iface_name_n0_n1, '10.67.0.1/30', now=True)
    veth_n1_n0 = n1.register_veth('n1', n1.real_default_iface.name, iface_name_n1_n0, '10.67.0.2/30', now=True)
    veth_n0_n1.connect(veth_n1_n0)
    veth_n1_n2 = n1.register_veth('n1', n1.real_default_iface.name, iface_name_n1_n2, '10.67.0.5/30', now=True)
    veth_n2_n1 = n2.register_veth('n2', n2.real_default_iface.name, iface_name_n2_n1, '10.67.0.6/30', now=True)
    veth_n1_n2.connect(veth_n2_n1)

    n0.arp('add', veth_n1_n0.ip, veth_n1_n0.mac, ns='n0')
    n0.exec_batch_commit() # FIXME
    n1.arp('add', veth_n0_n1.ip, veth_n0_n1.mac, ns='n1')
    n1.arp('add', veth_n2_n1.ip, veth_n2_n1.mac, ns='n1')
    n1.exec_batch_commit() # FIXME
    n2.arp('add', veth_n1_n2.ip, veth_n1_n2.mac, ns='n2')
    n2.exec_batch_commit() # FIXME

    n0.route(veth_n1_n2.ip, iface_name_n0_n1, batch=False, ns='n0')
    n0.route(veth_n2_n1.ip, iface_name_n0_n1, batch=False, ns='n0')

    n2.route(veth_n0_n1.ip, iface_name_n2_n1, batch=False, ns='n2')
    n2.route(veth_n1_n0.ip, iface_name_n2_n1, batch=False, ns='n2')

    # check if IP addresses have been properly set
    assert check_ip_properly_set_in_netns('n0', iface_name_n0_n1, n0)
    assert check_ip_properly_set_in_netns('n1', iface_name_n1_n0, n1)
    assert check_ip_properly_set_in_netns('n1', iface_name_n1_n2, n1)
    assert check_ip_properly_set_in_netns('n2', iface_name_n2_n1, n2)

    # check reachability
    assert check_host_reachable_from_ns(testinfra_h, 'n0', '10.67.0.5')
    assert check_host_reachable_from_ns(testinfra_h, 'n0', '10.67.0.6')

    assert check_host_reachable_from_ns(testinfra_h, 'n1', '10.67.0.1')
    assert check_host_reachable_from_ns(testinfra_h, 'n1', '10.67.0.6')

    assert check_host_reachable_from_ns(testinfra_h, 'n2', '10.67.0.1')
    assert check_host_reachable_from_ns(testinfra_h, 'n2', '10.67.0.2')

    n0.close()
    n1.close()
    n2.close()
