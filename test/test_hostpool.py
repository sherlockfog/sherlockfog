import pytest
import sherlockfog

from misc import *

def test_add_host_and_find_it():
    ensure_env_is_clean()

    lan0 = init_host_pool()
    h = define_host('n0')

    lan0.add_host(h)

    assert len(lan0.hosts) == 1
    assert lan0.find_host('n0') == h

    lan0.close()

def test_create_two_connected_hosts():
    global testinfra_h
    ensure_env_is_clean()

    vhosts = ('n0', 'n1')

    lan0 = init_host_pool()

    n0, n1 = vhostobj = (define_host(x) for x in vhosts)

    lan0.add_host(n0)
    lan0.add_host(n1)

    hl = [x.name for x in lan0.hosts] # FIXME
    for vh in vhosts:
        assert vh in hl
    assert len(hl) == len(vhosts)

    lan0.connect('n0', 'n1')

    lan0.build_network()

    # check if host file produces the right output on every container
    for runner in vhosts:
        for vh in vhostobj:
            assert run_in_netns_ssh(testinfra_h, runner, 'getent hosts {0}'.format(vh.default_iface.ip)).stdout.split()[1] == vh.name

    # check if the link is also searchable in the underlying topology
    assert str(lan0.get_topo().get_link_addr('n0', 'n1')) == str(n0.veth0.network())

    lan0.close()

    assert no_netns_in_list_is_up(testinfra_h, vhosts)

def test_create_three_hosts_reachable_unreachable():
    global testinfra_h
    ensure_env_is_clean()

    vhosts = ('n0', 'n1', 'n2')

    lan0 = init_host_pool()

    n0, n1, n2 = vhostobj = (define_host(x) for x in vhosts)

    lan0.add_host(n0)
    lan0.add_host(n1)
    lan0.add_host(n2)

    lan0.connect('n0', 'n1')

    lan0.build_network()

    # check if interfaces for the (n0, n1) link are searchable
    assert lan0.get_endpoint_iface(n0, n1) == n0.veth0
    assert lan0.get_endpoint_iface(n1, n0) == n1.veth0
    # on the other hand, (n0, n2) shouldn't exist
    assert lan0.get_endpoint_iface(n0, n2) is None

    # check reachability
    assert check_host_reachable_from_ns(testinfra_h, 'n0', n1.default_iface.ip)
    assert check_host_reachable_from_ns(testinfra_h, 'n1', n0.default_iface.ip)
    assert not check_host_reachable_from_ns(testinfra_h, 'n2', n0.default_iface.ip)
    assert not check_host_reachable_from_ns(testinfra_h, 'n2', n1.default_iface.ip)

    lan0.close()

    assert no_netns_in_list_is_up(testinfra_h, vhosts)
