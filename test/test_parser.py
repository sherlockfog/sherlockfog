import pytest
import random
import multiprocessing
import sys, traceback

import sherlockfog

from misc import *

def init_environment():
    locals = {}
    lan0 = init_host_pool()
    topo0 = lan0.topo

    return sherlockfog.ExecutionEnvironment(topo0, lan0, locals=locals, args=args)

def test_parser_def_single_host_syntax_ok():
    ensure_env_is_clean()

    e = init_environment()

    ns1 = 'n0'
    ns2 = 'n1'

    lan0 = e.hp
    lan0.add_real_host(ip, 'h0')
    lan0.add_real_host(ip, 'h1')

    e.exec_('def {0}'.format(ns1))

    assert ns1 in list_netns()
    assert ns1 in list_cgroups()

    e.exec_('def {0} {1}'.format(ns2, ip))

    assert ns2 in list_netns()
    assert ns2 in list_cgroups()

    lan0.close()

def test_parser_def_single_host_syntax_bad():
    ensure_env_is_clean()

    e = init_environment()

    with pytest.raises(SyntaxError):
        e.exec_('def')

    with pytest.raises(SyntaxError):
        e.exec_('def -1')

    with pytest.raises(SyntaxError):
        e.exec_('def n7 1.2.3.256')

    with pytest.raises(SyntaxError):
        e.exec_('def n0 -1.2.34.234423')

    assert len(list_netns()) == 0

def test_parser_let_syntax_ok():
    ensure_env_is_clean()

    e = init_environment()

    e.exec_('let a 10')
    assert 'a' in e.locals
    assert e.locals['a'] == 10

    e.exec_('let b myvar')
    assert 'b' in e.locals
    assert e.locals['b'] == 'myvar'

    assert len(e.locals) == 2

def test_parser_let_syntax_bad():
    ensure_env_is_clean()

    e = init_environment()

    with pytest.raises(SyntaxError):
        e.exec_('let')

    with pytest.raises(SyntaxError):
        e.exec_('let a')

    with pytest.raises(SyntaxError):
        e.exec_('let 34 42')

    with pytest.raises(SyntaxError):
        e.exec_('let -foo 42')

    assert len(e.locals) == 0

def test_parser_connect_syntax_ok():
    ensure_env_is_clean()

    e = init_environment()
    lan0 = e.hp

    n1 = define_host('n1')
    n2 = define_host('n2')
    n3 = define_host('n3')

    lan0.add_host(n1)
    lan0.add_host(n2)
    lan0.add_host(n3)

    e.exec_('connect n1 n2')
    assert set(lan0.link_iter()) == set([('n1','n2')])
    #assert lan0.topo.get_link_addr('n1','n2').ips() == ['10.67.0.1/30','10.67.0.2/30']

    e.exec_('connect n2 n3 10ms')
    assert ('n2','n3') in set(lan0.link_iter())
    assert lan0.topo.get_delay('n2','n3') == '10ms'

    with pytest.raises(RuntimeError):
        e.exec_('connect n9 n1 20ms')

    with pytest.raises(RuntimeError):
        e.exec_('connect n2 n7 10ms')

    with pytest.raises(RuntimeError):
        e.exec_('connect n1 n4')

    with pytest.raises(RuntimeError):
        e.exec_('connect n3 n1 asdf')

    lan0.close()

    assert len(list_netns(testinfra_h)) == 0

def test_parser_connect_syntax_bad():
    ensure_env_is_clean()

    e = init_environment()

    with pytest.raises(SyntaxError):
        e.exec_('connect -2 a32')

    with pytest.raises(SyntaxError):
        e.exec_('connect a23 -645')

    with pytest.raises(SyntaxError):
        e.exec_('connect asdasd')

def test_parser_include_syntax_ok():
    ensure_env_is_clean()

    e = init_environment()

    with pytest.raises(FileNotFoundError):
        e.exec_('include /tmp/this_file_does_not_exit_{0}'.format(random.randint(1, 10000)))

    tmpfile = create_tmpfile(content='# this file is readable')
    e.exec_('include {0}'.format(tmpfile.name))

    tmpfile.close()

def test_parser_include_syntax_ok_file_unreadable():
    # Try to open an unreadable file
    # Involves the following steps:
    # 
    # 0. create temp file with owner our user and no read permissions
    # 1. fork to a new process
    # 2. drop privileges to nobody/nogroup
    # 3. exec include
    # 4. get exception (or not) and send back to parent
    tmpfile = create_tmpfile(content='# this file is not readable', mode=0000)
    def read_with_dropped_privileges(conn):
        if drop_privileges():
            # create environment on forked process
            e = init_environment()
            try:
                e.exec_('include {0}'.format(tmpfile.name))
            except Exception as ex:
                conn.send(ex)
        conn.send(0)

    parent_conn, child_conn = multiprocessing.Pipe()
    p = multiprocessing.Process(target=read_with_dropped_privileges, args=(child_conn,))
    p.start()

    with pytest.raises(OSError):
        raise parent_conn.recv()

    p.join()
    tmpfile.close()

def test_parser_include_syntax_bad():
    e = init_environment()

    with pytest.raises(SyntaxError):
        e.exec_('include')

def test_parser_set_delay_syntax_ok():
    ensure_env_is_clean()

    e = init_environment()
    lan0 = e.hp

    lan0.add_host(define_host('n0'))
    lan0.add_host(define_host('n1'))

    lan0.connect('n0', 'n1')

    lan0.build_network()

    e.exec_('set-delay n0 n1 20ms')

    assert lan0.find_host('n0').topo.get_delay('n0', 'n1') == "20ms"

    with pytest.raises(RuntimeError):
        e.exec_('set-delay n0 n1 --')

    with pytest.raises(RuntimeError):
        e.exec_('set-delay n0 n2 20ms')

    with pytest.raises(RuntimeError):
        e.exec_('set-delay n0 n1 100mbps')

    lan0.close()

def test_parser_set_delay_syntax_bad():
    ensure_env_is_clean()

    e = init_environment()
    lan0 = e.hp

    lan0.add_host(define_host('n0'))
    lan0.add_host(define_host('n1'))

    with pytest.raises(SyntaxError):
        e.exec_('set-delay n0')

    with pytest.raises(SyntaxError):
        e.exec_('set-delay n0 n1')

    with pytest.raises(SyntaxError):
        e.exec_('set-delay // -- 20ms')

    lan0.close()

def test_parser_set_bandwidth_syntax_ok():
    ensure_env_is_clean()

    e = init_environment()
    lan0 = e.hp

    lan0.add_host(define_host('n0'))
    lan0.add_host(define_host('n1'))

    lan0.connect('n0', 'n1')
    lan0.set_delay('n0', 'n1', '0.2ms')

    lan0.build_network()

    e.exec_('set-bandwidth n0 n1 20mbps')

    # Check if bandwidth defined in topology abstraction
    assert lan0.find_host('n0').topo.get_bandwidth('n0', 'n1') == "20mbps"

    # Invalid tc argument
    with pytest.raises(IOError):
        e.exec_('set-bandwidth n0 n1 --')

    # Unknown host name n2
    with pytest.raises(RuntimeError):
        e.exec_('set-bandwidth n0 n2 20mbps')

    lan0.close()

def test_parser_set_bandwidth_syntax_bad():
    ensure_env_is_clean()

    e = init_environment()
    lan0 = e.hp

    lan0.add_host(define_host('n0'))
    lan0.add_host(define_host('n1'))

    with pytest.raises(SyntaxError):
        e.exec_('set-bandwidth n0')

    with pytest.raises(SyntaxError):
        e.exec_('set-bandwidth n0 n1')

    with pytest.raises(SyntaxError):
        e.exec_('set-bandwidth // -- 100mbps')

    lan0.close()

def test_parser_build_network_syntax_ok():
    ensure_env_is_clean()

    e = init_environment()
    lan0 = e.hp

    lan0.add_host(define_host('n0'))
    lan0.add_host(define_host('n1'))

    lan0.connect('n0', 'n1')

    e.exec_('build-network')

    assert check_host_reachable_from_ns(testinfra_h, 'n0', 'n1')

    lan0.close()
