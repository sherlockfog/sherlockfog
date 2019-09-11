import pytest
import sherlockfog

from misc import *

def test_create_three_hosts_reachable_unreachable():
    ensure_env_is_clean(testinfra_h)

    vhosts = ('n0', 'n1', 'n2')

    topo0 = sherlockfog.Topo()
    lan0 = sherlockfog.HostPool('lan0',
            base=args.base_prefix,
            use_adm=False,
            args=args)
    lan0.topo = topo0 # FIXME

    n0 = sherlockfog.Host('n0', ip, args=args)
    n1 = sherlockfog.Host('n1', ip, args=args)
    n2 = sherlockfog.Host('n2', ip, args=args)

    lan0.add_host(n0)
    lan0.add_host(n1)
    lan0.add_host(n2)

    hl = [x.name for x in lan0.hosts] # FIXME
    for vh in vhosts:
        assert vh in hl

    lan0.connect('n0', 'n1')

    # FIXME this should be a single step
    lan0.build_namespaces_parallel()
    lan0.static_routes()

    assert check_host_reachable_from_ns(testinfra_h, 'n0', n1.default_iface.ip)
    assert check_host_reachable_from_ns(testinfra_h, 'n1', n0.default_iface.ip)
    assert not check_host_reachable_from_ns(testinfra_h, 'n2', n0.default_iface.ip)
    assert not check_host_reachable_from_ns(testinfra_h, 'n2', n1.default_iface.ip)

    n0.close()
    n1.close()
    n2.close()

    assert no_netns_in_list_is_up(testinfra_h, vhosts)
