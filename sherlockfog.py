#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from collections import defaultdict, deque
import os, re, sys, collections, pexpect, struct, argparse, shutil, itertools, time, random, string, ipaddress
import pathlib
import platform

import signal
import http.server, json

import concurrent.futures
import subprocess
import threading

import traceback
import inspect
import logging

from functools import wraps

import paramiko
import requests

import importlib.resources as pkg_resources

global logger, docker_info
logger = None
docker_info = None

if tuple(int(x) for x in platform.python_version_tuple()) < (3, 9, 0):
    sys.stderr('Requires Python version >= 3.9.0')
    sys.exit(-1)

class DevnullWrapper(object):
    def __init__(self, mod):
        self.mod = mod
    def __getattr__(self, name):
        def _f(*args, **kwargs):
            global logger
            logger.warning("Ignoring {0} call: {1}".format(self.mod, name))
        return _f

import networkx as nx
try:
    import matplotlib
    # change matplotlib backend if DISPLAY is not set
    if 'DISPLAY' not in os.environ:
         matplotlib.use('Agg')
    import matplotlib.pyplot as plt
except:
    # Define plt object that ignores pyplot calls (or otherwise)
    class PyplotDevnullWrapper(DevnullWrapper):
        def __init__(self):
            super().__init__('pyplot')
    plt = PyplotDevnullWrapper()

"""
High Level Commands
===================

    * def <node> <ip>: inits ssh connection to ip and maps connection to <name>.

    * let <var> <value>: bind variable name <var> to immutable value <value>.

    * build-network: initialize static routing tables, static ARP and local /etc/hosts.

    * for <var> in <start..end> do <cmd>: executes <cmd> binding {var} to values in range <start..end>.

    * include <file>: executes commands in file <file>

    * set-delay [at=delay] <node1> <node2> <extra args>: sets bidirectional latency between <node1> and <node2>.
    Nodes must be connected. See set-latency for reference on <extra args> (netem args).
    Optional argument [at=delay] queues command to be executed after <delay> seconds.

    * set-bandwidth [at=delay] <node1> <node2> <extra args>: sets bidirectional bandwidth between <node1> and <node2>.
    Nodes must be connected. See set-latency for reference on <extra args> (netem args).
    Optional argument [at=delay] queues command to be executed after <delay> seconds.

    * shell <node> [args]: launches terminal in node using args to setup connection (supported args: username='blah' ns='ns')
    * shell: launches local terminal
    * shelladm [args]: launches admin terminal in using args to setup connection (supported args: username='blah' ns='ns')

    * xterm: launches local xterm

Low Level Commands
==================

    * netns <node> <name>: create netns named <name> on <node>
    * cgroup-set-cpu-shares <node> <shares>: limit cgroup in <node> to <shares> CPU shares.
    * cgroup-set-cfs-quota <node> <quota>: set cgroup scheduler quota in <node> to <quota>/100000.
    * set-link <node> dev <dev> <extra args>: runs ip link set on <node> on iface <dev> using <extra args>
    * <commented out>route <node> netns <ns> <net> via <dev>: sets routing entry for network <net> on node <node> in namespace <ns> via device <dev></commented out>
    * run <node> <cmd>: executes <cmd> in <node>, raises IOError on stderr
    * run <node> netns <ns> <cmd>: executes <cmd> on <node> in namespace <ns>, raises IOError on stderr
    * runas <node> <user> <cmd>: executes <cmd> on <node> as user <user> (only if remote user is root), raises IOError on stderr
    * runas <node> netns <ns> <user> <cmd>: executes <cmd> on <node> in namespace <ns> as user <user> (only if remote user is root), raises IOError on stderr
    * service <node> netns <ns> <cmd>: executes <cmd> on <node> in namespace <ns>, raises IOError on stderr, kills PID on close. Command must return PID on readline.
    * sysctl <node> <var> <value>: sets sysctl variable <var> on node <node> to <value>
    * tc <node> dev <dev> <extra args>: shapes <dev> on <node> using <extra args> (netem arguments)
    * tc <node> netns <name> dev <dev> <extra args>: shapes <dev> on <node> in namespace <name> using <extra args> (netem arguments)
    * tcraw <node> <extra args>: runs tc on <node> using <extra args>
"""

class ColorFormatter(logging.Formatter):
    grey = '\x1b[38;21m'
    green = '\x1b[32;25m'
    blue = '\x1b[38;5;39m'
    yellow = '\x1b[38;5;226m'
    red = '\x1b[38;5;196m'
    bold_red = '\x1b[31;1m'
    reset = '\x1b[0m'

    def __init__(self, fmt, **kwargs):
        super().__init__(fmt, **kwargs)
        self.kwargs = kwargs
        self.base_fmt = fmt
        self.level_colors = {
            logging.DEBUG: self.grey,
            logging.INFO: self.blue,
            logging.WARNING: self.yellow,
            logging.ERROR: self.red,
            logging.CRITICAL: self.bold_red
        }

    def format(self, record):
        fmt_tokens = self.base_fmt.split()
        log_fmt = '{0}{1}{2} {3}{4}{5} {6}{7}{8}'.format(
            self.green,
            fmt_tokens[0],
            self.reset,
            self.level_colors.get(record.levelno),
            fmt_tokens[1],
            self.reset,
            self.reset,
            fmt_tokens[2],
            self.reset
        )
        formatter = logging.Formatter(log_fmt, **self.kwargs)
        return formatter.format(record)

def init_logging(args, silent=False):
    global logger
    logger = logging.getLogger(__name__)
    level = logging.INFO
    # override logging level if silent is set - even if args.debug is set
    if silent:
        level = logging.ERROR
    elif args.debug:
        level = logging.DEBUG
    logger.setLevel(level)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    fmt = '[%(asctime)s] %(levelname)s %(message)s'
    # enable ANSI color codes only if stdout is connected to a TTY, use default
    # formatter otherwise
    if hasattr(sys.stdout, 'isatty') and sys.stdout.isatty():
        formatter = ColorFormatter(fmt, datefmt='%c')
    else:
        formatter = logging.Formatter(fmt, datefmt='%c')
    ch.setFormatter(formatter)
    logger.addHandler(ch)
    return logger

def debug_route(host, r, if1, ns=None):
    logger.debug("ROUTE {0} -> {1} via {2} ns:{3}".format(host.name, r, if1, ns))

# https://docs.python.org/3/library/itertools.html
def pairwise(iterable):
    "s -> (s0,s1), (s1,s2), (s2, s3), ..."
    a, b = itertools.tee(iterable)
    next(b, None)
    return zip(a, b)

def random_string(n):
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

def log_command(ip, cmd):
    logger.debug('{0} -> {1}'.format(ip, cmd))

def future_wrapper(o):
    if isinstance(o, concurrent.futures.Future):
        o = o.result()
    return o

class IPUtil(object):
    @staticmethod
    def bcast_addr(ip, mask):
        ip = IPUtil.inet_aton(ip)
        addr = ip | ((1 << (32-mask))-1)
        return IPUtil.inet_ntoa(addr)
    @staticmethod
    def network_addr(ip, mask):
        ip = IPUtil.inet_aton(ip)
        addr = ip & (((1 << mask)-1) << (32-mask))
        return IPUtil.inet_ntoa(addr)
    @staticmethod
    def inet_aton(ip):
        m = re.match(r'(\d+)\.(\d+)\.(\d+)\.(\d+)', ip)
        packed_ip = struct.pack('BBBB',
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4)))
        ip = struct.unpack('>I', packed_ip)[0]
        return ip
    @staticmethod
    def inet_ntoa(addr):
        t = struct.unpack('BBBB', struct.pack('>I', addr))
        return "{0}.{1}.{2}.{3}".format(*t)
    @staticmethod
    def split_ipmask(m):
        ip, mask = m.split('/')
        mask = int(mask)
        return ip, mask
    @staticmethod
    def join_ipmask(ip, m):
        return '{0}/{1}'.format(ip, m)

class Topo(object):
    def __init__(self, name='topo0'):
        self.g = nx.Graph()
        self.root = None
    def add_host(self, hn):
        if self.root is None:
            self.root = hn
        self.g.add_node(hn)
    def connect(self, h1, h2):
        self.g.add_edge(h1, h2)
    def get_delay(self, h1, h2):
        return self.g[h1][h2]['delay']
    def set_delay(self, h1, h2, delay):
        if type(delay) is str:
            delay = self.__parse_delay(delay)
        self.g[h1][h2]['delay'] = delay
    def get_bandwidth(self, h1, h2):
        return self.g[h1][h2]['bandwidth']
    def set_bandwidth(self, h1, h2, bw):
        self.g[h1][h2]['bandwidth'] = bw
    def get_link_addr(self, h1, h2):
        return self.g[h1][h2]['addr']
    def set_link_addr(self, h1, h2, addr):
        self.g[h1][h2]['addr'] = addr
    def links(self, data=False):
        return self.g.edges(data=data)
    def all_pairs_shortest_path(self):
        return nx.all_pairs_dijkstra_path(self.g, weight='delay')
    def save(self, *args):
        if len(args) == 0:
            out = '{0}.pdf'.format(self.name)
        else:
            out = args[0]
        # root node is the node with the highest degree
        root_node = max((y, x) for x, y in dict(self.g.degree()).items())[1]
        # calculate node layout
        #pos = nx.nx_pydot.graphviz_layout(self.g, prog='twopi', root=root_node)
        pos = nx.nx_pydot.graphviz_layout(self.g, prog='fdp', root=root_node)
        plt.figure(figsize=(12,8))
        nx.draw(self.g, pos=pos, with_labels=True, node_size=600)

        # build edge labels using delay and addr info
        edge_labels_delay = nx.get_edge_attributes(self.g, 'delay')
        edge_labels_addr = nx.get_edge_attributes(self.g, 'addr')
        #print(edge_labels_delay)
        #print({k:str(v) for k,v in edge_labels_addr.items()})
        edge_labels = {k: '{0} {1}'.format(edge_labels_addr[k], edge_labels_delay[k]) for k in edge_labels_delay.keys()}
        #print('edge_labels: {0}'.format(edge_labels))
        #print(self.g.edges())

        try:
            nx.draw_networkx_edge_labels(self.g, pos=pos, edge_labels=edge_labels, edge_size=1600)
        except TypeError:
            # forward compatibility - NX 2.5
            nx.draw_networkx_edge_labels(self.g, pos=pos, edge_labels=edge_labels)
        plt.savefig(out)
        #IPython.embed()
    def __parse_delay(self, delay):
        tokens = re.split(r'(\d+(\.|)\d*)( *(\w+|))', delay)
        value, suffix = tokens[1], tokens[-1]
        # default to ms
        mult = 1.0
        if suffix == 's':
            mult = 0.001
        elif suffix == 'ms':
            mult = 1.0
        elif suffix == 'ns':
            mult = 1000.0
        elif suffix == 'us':
            mult = 1000000.0
        return mult*float(value)

class IPPool(object):
    BASE = '10.67.0.0/16'
    def __init__(self, base=None):
        if base is None:
            base = self.BASE
        self.addr = ipaddress.ip_network(base)
        self.mask = None
        self.cur = None
    def bcast(self):
        return self.addr.broadcast_address
    def next_subnet(self, mask):
        if mask != self.mask:
            self.mask = mask
            self.cur = self.addr.subnets(new_prefix=self.mask)
        net = next(self.cur)
        return IPPool(str(net))
    def ips(self):
        return list('{0}/{1}'.format(x, self.addr.prefixlen) for x in self.addr.hosts())
    def __str__(self):
        return str(self.addr)
    def __iter__(self):
        return (str(x) for x in self.addr)

class Bridge(object):
    topo_ns = 'topo'
    def __init__(self, manager, name, network):
        self.manager = manager
        self.name = name
        self.network = network
        self.initialized = {}
    def add(self, ifname, iface, topo_ns=None):
        if topo_ns is None:
            if self.manager is not None:
                topo_ns = self.manager.topo_ns
            else:
                topo_ns = self.topo_ns
        h = iface.parent
        real_name = h.real_host.name
        state = None
        try:
            state = self.initialized[real_name]
        except KeyError:
            self.initialized[real_name] = state = False
        if not state:
            try:
                h.exec_('ip link add name {0} type bridge'.format(self.name), ns=topo_ns)
                h.exec_('ip link set dev {0} up'.format(self.name), ns=topo_ns)
            except IOError:
                # Ignore errors if the bridge already exists
                pass
            finally:
                self.initialized[real_name] = True
        h.exec_('ip link set dev {0} master {1} up'.format(ifname, self.name), ns=topo_ns)

class BridgeManager(object):
    connection_timeout = 60
    topo_ns = 'topo'
    def __init__(self, pool):
        self.pool = pool
        self.ns_dict = {}
        self.__lock = threading.Lock()
        self.bridges_dict = {}
        self.bridge_counter = 0
        self.tunnels_dict = {}
        self.tunnel_counter = 0
    def __del__(self):
        self.close_real_hosts()
    def lock(self):
        self.__lock.acquire()
    def unlock(self):
        self.__lock.release()
    def get_bridge(self, net):
        try:
            br = self.bridges_dict[net]
        except KeyError:
            name = 'br{0}'.format(self.bridge_counter)
            self.bridge_counter += 1
            self.bridges_dict[net] = br = Bridge(self, name, net)
        return br
    def get_tunnel(self, net):
        try:
            tn = self.tunnels_dict[net]
        except KeyError:
            tifname = 'gv{0}'.format(self.tunnel_counter)
            self.tunnel_counter += 1
            self.tunnels_dict[net] = tn = (tifname, self.tunnel_counter)
        return tn
    def run(self, real_host, cmd):
        return real_host.run(cmd, timeout=self.connection_timeout)
    def init_real_host(self, real_host):
        # Initialize only once
        if real_host.name not in self.ns_dict:
            logger.info('Creating topology container for real host {0}'.format(real_host.name))
            self.run(real_host, 'ip netns add {0}'.format(self.topo_ns))
            self.ns_dict[real_host.name] = {
                'real_host': real_host,
                'ns': self.topo_ns,
            }
    def close_real_hosts(self):
        hosts = list(self.ns_dict.keys())
        for h in hosts:
            self.close_real_host(h)
    def close_real_host(self, real_host):
        try:
            d = self.ns_dict[real_host]
            logger.info('Destroying topology container for real host {0}'.format(real_host))
            # FIXME doesn't show the command in debug mode when underlying host is a RealHost
            self.run(d['real_host'], 'ip netns del {0}'.format(d['ns']))
            del self.ns_dict[real_host]
        except KeyError:
            # Ignore multiple calls
            pass
    def add_to_bridge(self, ifname, iface):
        h = iface.parent
        topo_ns = self.ns_dict[h.real_host.name]['ns']
        h.exec_('ip link set dev {0} netns {1}'.format(ifname, topo_ns))
        logger.debug('add_to_bridge ##### {0} {1}|{2}|{3}|{4}|{5} {6}|{7}|{8}|{9}'.format(ifname,
            iface.name, iface, iface.parent.name, iface.parent.real_host.name, iface.network_addr(),
            iface.endpoint,
            iface.endpoint.parent.name if iface.endpoint is not None else None,
            iface.endpoint.parent.real_host.name if iface.endpoint is not None else None,
            iface.endpoint.network_addr() if iface.endpoint is not None else None))
        net = iface.network_addr()
        bridge = self.get_bridge(net)
        bridge.add(ifname, iface, topo_ns=topo_ns)
        if iface.endpoint is not None and iface.parent.real_host.name != iface.endpoint.parent.real_host.name:
            tifname, vni = self.get_tunnel(net)
            dest = iface.endpoint.parent.real_host.name
            temp_dev_name = 'gv{0}'.format(random_string(6))
            # Ignore multiple initialization of tunnel - adm tunnel is initialized twice if adm node is also one of the running nodes
            try:
                h.exec_('ip link add name {0} type geneve id {1} remote {2}'.format(temp_dev_name, vni, dest))
                h.exec_('ip link set dev {0} name {1} netns {2}'.format(temp_dev_name, tifname, topo_ns))
                bridge.add(tifname, iface, topo_ns=topo_ns)
                # AdminHost needs the tunnel on the other side in case the hosts are different
                if isinstance(iface.endpoint.parent, AdminHost):
                    src = h.real_host.name
                    e = iface.endpoint.parent
                    e.exec_('ip link add name {0} type geneve id {1} remote {2}'.format(temp_dev_name, vni, src))
                    e.exec_('ip link set dev {0} netns {1}'.format(temp_dev_name, topo_ns))
                    e.exec_('ip link set dev {0} master {1} up'.format(temp_dev_name, bridge.name), ns=topo_ns)
            except IOError:
                pass

def ignore_exceptions(fn, *args, **kwargs):
    ret = None
    try:
        ret = fn(*args, **kwargs)
    except Exception as e:
        logger.error("Ignoring exception: {0}".format(e))
    return ret

class RestAPIJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, Interface) or isinstance(o, nx.reportviews.EdgeView) or isinstance(o, IPPool):
            return str(o)
        elif isinstance(o, argparse.Namespace):
            return vars(o)
        return super().default(o)

rest_api_entities = {}

class RestAPIEntity(object):
    def __repr__(self):
        return vars(self)

class RestAPIHostsEntity(RestAPIEntity):
    name = 'hosts'
    def get(self, pool, *args):
        if len(args) == 0:
            return {'hosts': dict(pool.host_list())}
        else:
            name = args[0]
            host = pool.find_host(name)
            return {'hosts': {name: host.ifaces}}

class RestAPITopoEntity(RestAPIEntity):
    name = 'topo'
    def get(self, pool, *args):
        link_list = list(pool.topo.links(data=True))
        if len(args) == 0:
            return {'topo': [(x[0], x[1]) for x in link_list]}
        else:
            pair = tuple(args[0].split(','))
            return {'topo': [x[2] for x in link_list if tuple(x[:2]) == pair]}

class RestAPIGlobalStatusEntity(RestAPIEntity):
    name = 'global_status'
    def get(self, pool, *args):
        return {'global_status': pool.global_status()}

class RestAPINetworkStatusEntity(RestAPIEntity):
    name = 'network_status'
    def get(self, pool, *args):
        return {'network_status': pool.network_status()}

class RestAPIRequestHandler(http.server.BaseHTTPRequestHandler):
    # List entity classes based on RestAPIEntity subclassing and existence of 'name' attribute.
    # Newly defined entities with those characteristics will be registered automatically here.
    entities = { cls.name: cls for cls in globals().values() if isinstance(cls, type(object)) and \
            issubclass(cls, RestAPIEntity) and \
            hasattr(cls, 'name') }
    def __init__(self, *args, **kwargs):
        self.json_encoder = RestAPIJSONEncoder()
        super().__init__(*args, **kwargs)
    def log_message(self, format, *args):
        logger.info("REST API: " + format % args)
    def write_good_json(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
    def write_bad_json(self):
        self.send_response(403)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
    def write_json_response(self, obj):
        if obj:
            self.write_good_json()
            self.wfile.write(bytes(self.json_encoder.encode(obj) + '\r\n', 'UTF-8'))
        else:
            self.write_bad_json()
    def get_entity(self, name, *args):
        return self.entities.get(name)().get(self.server.pool, *args)
    def get_entity_by_path(self):
        levels = list(pathlib.PurePath(self.path).parts)
        try:
            levels.pop(0)
            name = levels.pop(0)
            return self.get_entity(name, *levels)
        except Exception:
            pass
        # no valid entity
        return None
    def do_GET(self):
        self.write_json_response(self.get_entity_by_path())
    def do_POST(self):
        pass

class RestAPIManager(object):
    def __init__(self, pool):
        self.pool = pool
        self.server = None
        self.thread = None
        self.started = False
    def start(self):
        port = self.pool.args.rest_api_port
        logger.info('Starting REST API adm interface on port {0}...'.format(port))
        self.server = http.server.ThreadingHTTPServer(
                ('', port),
                RestAPIRequestHandler)
        self.server.pool = self.pool

        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.started = True

class HostPool(object):
    P2P_MASK = 30
    def __init__(self, name, base=None, args=None, use_adm=False, topo=None):
        self.name = name
        self.hosts_dict = {}
        self.ippool = IPPool(base=base)
        self.networks = {}
        self.topo = topo
        self.real_hosts = []
        self.args = args
        self.generate_routes = self.static_routes
        if self.args is not None:
            self.set_route_algorithm()
        self.bridges = None
        if self.args and self.args.geneve_tunnels:
            self.bridges = BridgeManager(self)
        # setup administrative vhost
        self.adm_host = None
        if use_adm:
            self.adm_host = AdminHost(args=args)
            self.adm_host.pool = self
            # Init local topology container if using geneve tunnels and adm interface
            if self.bridges is not None:
                self.bridges.init_real_host(self.adm_host.real_host)
            self.adm_pool = iter(IPPool(base=args.base_adm_prefix).ips())
            #print('DEBUG  adm', self.adm_host.real_default_iface.name, 'adm0', next(self.adm_pool))
            self.adm_host.init_adm_gateway(self.adm_host.real_default_iface.name, self.adm_pool)
            if self.args.expose_adm:
                self.adm_host.init_expose_p2p_link(IPPool(base=args.expose_adm_prefix))
        self.executor = None
        self.network_built = False
        self.pending_tasks = []
        self.main_pid = os.getpid()
        self.rest_api_manager = RestAPIManager(self)
    def global_status(self):
        return {
            'main_pid': self.main_pid,
            'network_status': self.network_status(),
            'args': self.args,
        }
    def network_status(self):
        if self.network_built:
            return 'BUILT'
        else:
            return 'CREATING'
    def get_topo(self):
        return self.topo
    def set_topo(self, topo):
        self.topo = topo
    def get_executor(self):
        return self.executor
    def set_executor(self, e):
        self.executor = e
    def add_real_host(self, x, name):
        self.real_hosts.append(name)
        # Initialize RealHost instances as they are being added to the HostPool
        real_host = RealHostPool.get_real_host(name, vhost=BaseHost('test', x, args=self.args), args=self.args)
        if self.bridges is not None:
            self.bridges.init_real_host(real_host)
    def close(self):
        def stop_host(h):
            logger.info('Stopping virtual host: {0}'.format(h.name))
            ignore_exceptions(h.close)
        ignore_exceptions(self.waitall)
        if self.adm_host:
            logger.info('Stopping adm virtual host')
            ignore_exceptions(self.adm_host.close)
        self.parallel_foreach_host(stop_host)
        executor = self.get_executor()
        if executor is not None:
            executor.shutdown(wait=True)
        if self.bridges is not None:
            self.bridges.close_real_hosts()
    def new_network(self, mask):
        return self.ippool.next_subnet(mask)
    def set_p2p_route(self, if1, if2):
        ns1 = if1.parent.name
        ns2 = if2.parent.name
        if1.parent.exec_('ip route flush dev {0}'.format(if1.name), ns=ns1)
        if1.parent.exec_('ip route add {0} dev {1}'.format(if2.ip, if1.name), ns=ns1)
        #if1.parent.exec_batch_commit(ignore_stderr=True)
        if2.parent.exec_('ip route flush dev {0}'.format(if2.name), ns=ns2)
        if2.parent.exec_('ip route add {0} dev {1}'.format(if1.ip, if2.name), ns=ns2)
        #if2.parent.exec_batch_commit(ignore_stderr=True)
    def connect(self, h1, h2, *args):
        h1 = self.find_host(h1)
        h2 = self.find_host(h2)

        logger.info('Connect: {0} {1}'.format(h1.name, h2.name))

        # create new P2P interface
        net = self.new_network(self.P2P_MASK)
        net_ips = net.ips()
        vif_names = (h1.new_iface_name(), h2.new_iface_name())

        veth_h1 = h1.register_veth(h1.name, h1.real_default_iface.name, vif_names[0], net_ips[0])
        veth_h2 = h2.register_veth(h2.name, h2.real_default_iface.name, vif_names[1], net_ips[1], connect_to=veth_h1)

        def create_p2p_link(_, net_ips, h1, h2, vif_names):
            h1_ip, h2_ip = net_ips
            veth_h1 = h1.veth(h1.name, h1.real_default_iface.name, vif_names[0], h1_ip)
            veth_h2 = h2.veth(h2.name, h2.real_default_iface.name, vif_names[1], h2_ip)

            if self.args.routing_algo == 'world_topo':
                # change default network-based routing to P2P - compat with old routing algo
                self.set_p2p_route(veth_h1, veth_h2)

            logger.info('Init traffic shaper for link {0} {1} => {2}'.format(h1.name, h2.name, 'default' if len(args) == 0 else args[0]))
            veth_h1.init_shaper(*args, ns=h1.name)
            veth_h2.init_shaper(*args, ns=h2.name)

        def queue_pending_task_internal(_, future):
            self.pending_tasks.append(future)

        schedule_maybe_parallel_task(create_p2p_link, net_ips,
                h1, h2,
                vif_names,
                register_callback=queue_pending_task_internal,
                executor=self.get_executor())

        # record link and netaddr in graph abstraction
        if self.topo is not None:
            self.topo.connect(h1.name, h2.name)
            self.topo.set_link_addr(h1.name, h2.name, net)
            if len(args) > 0:
                self.topo.set_delay(h1.name, h2.name, *args)

    def queue_pending_task(self, future):
        self.pending_tasks.append(future)

    def link_iter(self):
        assert self.topo is not None
        for e in self.get_topo().links():
            #print('DEBUG ', e)
            yield e
    def set_delay(self, h1, h2, *args, **kwargs):
        h1 = self.find_host(h1)
        h2 = self.find_host(h2)
        if 'veth_h1' in kwargs:
            veth_h1 = kwargs['veth_h1']
        else:
            veth_h1 = self.get_endpoint_iface(h1, h2)
        if 'veth_h2' in kwargs:
            veth_h2 = kwargs['veth_h2']
        else:
            veth_h2 = veth_h1.endpoint
        if len(args) > 0:
            # shape inbound traffic in both directions
            h1.shape_delay(veth_h1.name, *args, ns=h1.name, **kwargs)
            h2.shape_delay(veth_h2.name, *args, ns=h2.name, **kwargs)
            logger.info('Set delay: {0} {1} => {2}'.format(h1.name, h2.name, ' '.join(args)))
            # record delay in graph abstraction
            if self.topo is not None:
                self.topo.set_delay(h1.name, h2.name, args[0])
    def set_bandwidth(self, h1, h2, *args, **kwargs):
        h1 = self.find_host(h1)
        h2 = self.find_host(h2)
        #print('DEBUG  set_bandwidth 1', h1, h2, *args, **kwargs)
        if 'veth_h1' in kwargs:
            veth_h1 = kwargs['veth_h1']
        else:
            veth_h1 = self.get_endpoint_iface(h1, h2)
        #print('DEBUG  set_bandwidth 2', veth_h1)
        if 'veth_h2' in kwargs:
            veth_h2 = kwargs['veth_h2']
        else:
            veth_h2 = veth_h1.endpoint
        if len(args) > 0:
            # change inbound bw in both directions
            h1.shape_bandwidth(veth_h1.name, args[0], ns=h1.name, **kwargs)
            h2.shape_bandwidth(veth_h2.name, args[0], ns=h2.name, **kwargs)
            logger.info('Set bandwidth: {0} {1} => {2}'.format(h1.name, h2.name, args[0]))
            # record bandwidth in graph abstraction
            if self.topo is not None:
                self.topo.set_bandwidth(h1.name, h2.name, args[0])
    def register_host(self, name, host):
        self.hosts_dict[name] = host
        self.topo.add_host(name)
    def add_host(self, host):
        host = future_wrapper(host)
        # check if using reserved name, this is used for magic placeholder replacement
        if host.name == 'nextRealHost':
            raise NameError('invalid node name')
        self.register_host(host.name, host)
        host.pool = self
        host.topo = self.topo
        # add administrative interface
        if self.adm_host:
            ip = next(self.adm_pool)
            iface_name = host.real_default_iface.name
            def create_adm_link(_, ip):
                h = host.veth(host.name, iface_name, 'adm0', ip, is_adm=True)
                self.adm_host.add_host(h)
            def queue_pending_task_internal(_, future):
                self.pending_tasks.append(future)
            host.register_veth(host.name, iface_name, 'adm0', ip, is_adm=True)
            schedule_maybe_parallel_task(create_adm_link, ip,
                register_callback=queue_pending_task_internal,
                executor=self.get_executor())
    def find_host(self, name):
        host = None
        try:
            host = future_wrapper(self.hosts_dict[name])
        except KeyError:
            raise RuntimeError("Unknown host: '{0}'".format(name))
        return host
    def ping(self, hn1, hn2, silent=False):
        h1 = self.find_host(hn1)
        h2 = self.find_host(hn2)
        h1.exec_('ping -c 5 -i 0.2 {0}'.format(hn2), ns=hn1)
        if h1.get_exec_exit_code() == 0:
            if self.args and self.args.dry_run:
                # Return random latency if dry-run
                mean_lat = '{:.2f}'.format(random.random())
            else:
                mean_lat = h1.get_exec_output('stdout').splitlines()[-1].split('=')[1].split('/')[1]
            if not silent:
                logger.info('Ping: {0} -> {1} {2}ms'.format(hn1, hn2, mean_lat))
            return mean_lat
        raise RuntimeError('Cannot ping: {0} -> {1}'.format(hn1, hn2))
    def ping_all(self):
        logger.info('Ping all...')
        for h1 in self:
            row = []
            hn1 = h1.name
            for h2 in self:
                hn2 = h2.name
                row.append(self.ping(hn1, hn2, silent=True))
            logger.info('{0} -> {1}'.format(hn1, ' '.join(row)))
    def shell(self):
        dry_run = self.args.dry_run
        if not dry_run:
            p = pexpect.spawn('/bin/bash', env=self.environ())
            p.interact(chr(29))
    def environ(self):
        env = os.environ.copy()
        for name, h in self.hosts_dict.items():
            env[name] = h.ip
        return env
    def get_endpoint_iface(self, h1, h2):
        # get iface from h1 that is connected to h2
        for if1 in h1.ifaces.values():
            if if1.endpoint is not None and if1.endpoint.parent == h2:
                return if1
    def wait_on_pending_tasks(self):
        logger.debug('pending tasks: {0}'.format(self.pending_tasks))
        for future in concurrent.futures.as_completed(self.pending_tasks):
            logger.debug('future completed: {0}'.format(future))
            future.result()
        self.pending_tasks = []
    def waitall(self):
        self.wait_on_pending_tasks()
        for hn in self.hosts_dict.keys():
            logger.debug('waiting on host {}'.format(hn))
            self.find_host(hn).wait()
    def static_routes(self):
        def static_routes_for_host(h, all_pairs, ifaces_dict):
            shortest_from_h = all_pairs[h.name]
            for dest, shortest_path in shortest_from_h.items():
                # add routes to every end node on every path starting from h
                ### we need two nodes
                #### first -> outgoing interface
                #### last -> destination node
                if len(shortest_path) > 1:
                    shortest_path.pop(0) # that's always us, remove it
                    via = self.get_endpoint_iface(h, self.find_host(shortest_path[0]))
                    #print(h.name, 'via', via, shortest_path)
                    #print('dest', shortest_path[-1], self.hosts_dict[shortest_path[-1]].ifaces)
                    for ifn, ifaddr in self.find_host(shortest_path[-1]).ifaces_non_adm().items():
                        if ifaddr.network_addr() == via.network_addr(): # FIXME ugly
                            continue
                        #print('if:', ifn, ifaddr)
                        #debug_route(h, ifaddr.ip, via, ns=h.name)
                        h.route(ifaddr.ip, via.name, batch=True, ns=h.name)
            h.exec_batch_commit()

        if self.topo is not None:
            all_pairs = dict(self.topo.all_pairs_shortest_path())
            ifaces_dict = {}
            for k in self.hosts_dict.keys():
                ifaces_dict[k] = self.find_host(k).ifaces_non_adm().items()
            self.parallel_foreach_host(static_routes_for_host, all_pairs, ifaces_dict)

    def static_routes_compressed(self):
        def static_routes_for_host(h, all_pairs, ifaces_dict):
            shortest_from_h = all_pairs[h.name]
            routes_from_h = defaultdict(list)
            for dest, shortest_path in shortest_from_h.items():
                #print('start from', h.name, 'path', shortest_path)
                # add routes to every end node on every path starting from h
                ### we need two nodes
                #### first -> outgoing interface
                #### last -> destination node
                if len(shortest_path) > 1:
                    shortest_path.pop(0) # that's always us, remove it
                    via = self.get_endpoint_iface(h, self.find_host(shortest_path[0]))
                    #print(h.name, 'via', via, shortest_path)
                    #print('dest', shortest_path[-1], self.hosts_dict[shortest_path[-1]].ifaces)
                    for ifn, ifaddr in self.find_host(shortest_path[-1]).ifaces_non_adm().items():
                        if ifaddr.network_addr() == via.network_addr(): # FIXME ugly
                            continue
                        #print('if:', ifn, ifaddr)
                        #debug_route(h, ifaddr.ip, via, ns=h.name)
                        #h.route(ifaddr.ip, via.name, batch=True, ns=h.name)
                        routes_from_h[via.name].append(ipaddress.ip_address(ifaddr.ip))

            for iface in routes_from_h.keys():
                routes_from_h[iface].sort()
            for iface, ips in routes_from_h.items():
                for i in range(len(ips)-1):
                    iface_i = ipaddress.ip_interface('{0}/30'.format(ips[i]))
                    iface_j = ipaddress.ip_interface('{0}/30'.format(ips[i+1]))
                    if iface_i.network == iface_j.network:
                        ips.append(iface_i.network.network_address)
                        ips.append(iface_i.network.broadcast_address)
            # sort again
            for iface, ips in routes_from_h.items():
                routes_from_h[iface] = sorted([ipaddress.ip_network(x) for x in ips])
            for iface, nets in routes_from_h.items():
                valid_nets = ipaddress.collapse_addresses(nets)
                for net in valid_nets:
                    h.route(str(net), iface, batch=True, ns=h.name)
            h.exec_batch_commit()

        if self.topo is not None:
            all_pairs = dict(self.topo.all_pairs_shortest_path())
            #print('all pairs', all_pairs)
            ifaces_dict = {}
            for k in self.hosts_dict.keys():
                ifaces_dict[k] = self.find_host(k).ifaces_non_adm().items()
            self.parallel_foreach_host(static_routes_for_host, all_pairs, ifaces_dict)

    def static_routes_world_topo(self):
        def find_country_gw(d, country):
            return next(iter(x for x in d[country] if x.name.endswith(country)))
        def find_connecting_iface(h1, h2):
            for ifn, ifaddr in h1.ifaces_non_adm().items():
                if ifaddr.endpoint.parent == h2:
                    return ifaddr
        # this routing strategy is heavily based on the names of the nodes
        # make sure that:
        #   end nodes               -> h{num}
        #   intermediate switches   -> s{num}
        #   world backbone switches -> s{num}-{cTLD}
        #   nodes MUST have a country property (cTLD) to route them correctly
        def static_routes_world_topo_for_host(h, nodes_by_country):
            ifaces = h.ifaces_non_adm()
            if h.name.startswith('h'):
                # end node, must be a leaf: connect to every other node using neighboring switch
                if len(ifaces.keys()) != 1:
                    raise ValueError('{0} node is not a leaf'.format(h.name))
                via = ifaces[next(iter(ifaces.keys()))]
                h.route('default', via.name, batch=True, ns=h.name) # default gateway
            elif re.match(r'^s\d+$', h.name):
                # node is a switch, default route is the switch next to it
                # end nodes are connected directly so a route is not required
                for ifn, ifaddr in ifaces.items():
                    if not ifaddr.endpoint.parent.name.startswith('h'):
                        h.route('default', ifaddr.name, batch=True, ns=h.name)
            else:
                m = re.match(r'^s(\d+)-(\w+)$', h.name)
                if m is not None:
                    # node is a world backbone switch
                    # -> route nodes in the same country through corresponding country switch
                    # -> route nodes in a different country through that country's backbone switch
                    country_src = h.get_property('country')
                    for h_dst in (x for x in self.hosts_dict.keys() if x.name.startswith('h')):
                        country_dst = h_dst.get_property('country')
                        if country_src == country_dst:
                            same_country_via = find_connecting_iface(h, next(iter(h_dst.ifaces_non_adm().values())).endpoint.parent)
                            for ifn, ifaddr in h_dst.ifaces_non_adm().items():
                                logger.debug('route: same country {0} from:{1} to:{2}({3}) via:{4}'.format(country_src, h.name, h_dst.name, ifaddr.ip, same_country_via.name))
                                h.route(ifaddr.ip, same_country_via.name, batch=False, ns=h.name)
                        else:
                            dst_country_gw = find_country_gw(nodes_by_country, country_dst)
                            dst_country_via = next(iter(x for x in h.ifaces_non_adm().values() if x.endpoint.parent == dst_country_gw))
                            for ifn, ifaddr in h_dst.ifaces_non_adm().items():
                                logger.debug('route: diff country {0}->{5} from:{1} to:{2}({3}) via:{4}'.format(country_src, h.name, h_dst.name, ifaddr.ip, dst_country_via.name, country_dst))
                                h.route(ifaddr.ip, dst_country_via.name, batch=False, ns=h.name)
                else:
                    raise KeyError('Invalid node name for world_topo routing: {0}'.format(h.name))
            h.exec_batch_commit()
        nodes_by_country = self.get_nodes_by_property('country')
        self.parallel_foreach_host(static_routes_world_topo_for_host, nodes_by_country)

    def static_routes_world_topo_flat(self):
        def find_country_gw(d, country):
            return next(iter(x for x in d[country] if x.name.endswith(country)))
        def find_connecting_iface(h1, h2):
            for ifn, ifaddr in h1.ifaces_non_adm().items():
                if ifaddr.endpoint.parent == h2:
                    return ifaddr
        # this routing strategy is heavily based on the names of the nodes
        # make sure that:
        #   end nodes               -> h{num}
        #   world backbone switches -> s{num}
        #   nodes MUST have a country property (cTLD) to route them correctly
        nodes_by_country = self.get_nodes_by_property('country')
        for h in self.hosts_dict.keys():
            ifaces = self.find_host(h).ifaces_non_adm()
            if h.name.startswith('h'):
                # end node, must be a leaf: connect to every other node using neighboring switch
                if len(ifaces.keys()) != 1:
                    raise ValueError('{0} node is not a leaf'.format(h.name))
                via = ifaces[next(iter(ifaces.keys()))]
                h.route('default', via.name, batch=False, ns=h.name) # default gateway
            else:
                m = re.match(r'^s(\d+)$', h.name)
                if m is not None:
                    # node is a world backbone switch
                    # -> route nodes in the same country through corresponding country switch
                    # -> route nodes in a different country through that country's backbone switch
                    country_src = h.get_property('country')
                    for h_dst in (x for x in self.hosts_dict.keys() if x.name.startswith('h')):
                        country_dst = h_dst.get_property('country')
                        if country_src == country_dst:
                            same_country_via = find_connecting_iface(h, next(iter(h_dst.ifaces_non_adm().values())).endpoint.parent)
                            for ifn, ifaddr in h_dst.ifaces_non_adm().items():
                                logger.debug('route: same country {0} from:{1} to:{2}({3}) via:{4}'.format(country_src, h.name, h_dst.name, ifaddr.ip, same_country_via.name))
                                h.route(ifaddr.ip, same_country_via.name, batch=True, ns=h.name)
                        else:
                            dst_country_gw = find_country_gw(nodes_by_country, country_dst)
                            dst_country_via = next(iter(x for x in h.ifaces_non_adm().values() if x.endpoint.parent == dst_country_gw))
                            for ifn, ifaddr in h_dst.ifaces_non_adm().items():
                                logger.debug('route: diff country {0}->{5} from:{1} to:{2}({3}) via:{4}'.format(country_src, h.name, h_dst.name, ifaddr.ip, dst_country_via.name, country_dst))
                                h.route(ifaddr.ip, dst_country_via.name, batch=True, ns=h.name)
                else:
                    raise KeyError('Invalid node name for world_topo_flat routing: {0}'.format(h.name))
            h.exec_batch_commit()

    def build_arp_tables_parallel(self):
        def build_arp_table(h):
            h.static_arp()
        self.parallel_foreach_host(build_arp_table)

    def parallel_foreach_host(self, f, *args):
        executor = self.get_executor()
        logger.debug('Parallel foreach host, {0} {1}'.format(f, args))
        if executor is not None:
            for h in self:
                self.queue_pending_task(executor.submit(f, h, *args))
        else:
            thrds = []
            for h in self:
                t = threading.Thread(target=f, args=(h,) + args)
                t.start()
                thrds.append(t)
            for t in thrds:
                t.join()

    def build_network(self):
        if self.network_built:
            logger.warning('Network already built, ignoring...')
            return
        def build_etchosts(h):
            h.ns_hosts()
        logger.info('Building network...')
        self.waitall()
        if self.args and not self.args.geneve_tunnels:
            logger.info('Building ARP tables...')
            self.build_arp_tables_parallel()
        logger.info('Building routing tables...')
        self.generate_routes()
        self.waitall()
        logger.info('Building /etc/hosts...')
        self.parallel_foreach_host(build_etchosts)
        self.waitall()
        #logger.debug('adm_host {0}'.format(self.adm_host))
        if self.adm_host:
            self.adm_host.ns_hosts()
        self.network_built = True

    def generate_tree_subnets_routes(self):
        for h in self:
            h.static_routes_tree_only()

    def set_route_algorithm(self):
        routing_algo_name = self.args.routing_algo
        if routing_algo_name == 'shortest_path':
            self.generate_routes = self.static_routes
        elif routing_algo_name == 'shortest_path_compressed':
            self.generate_routes = self.static_routes_compressed
        elif routing_algo_name == 'tree_subnets':
            self.generate_routes = self.generate_tree_subnets_routes
        elif routing_algo_name == 'world_topo':
            self.generate_routes = self.static_routes_world_topo
        elif routing_algo_name == 'world_topo_flat':
            self.generate_routes = self.static_routes_world_topo_flat
        elif routing_algo_name == 'none':
            self.generate_routes = lambda: None
        else:
            raise RuntimeError("Invalid routing algorithm: '{0}'".format(routing_algo_name))

    def get_nodes_by_property(self, attr):
        d = defaultdict(list)
        for h in self.hosts_dict.keys():
            try:
                prop = self.find_host(h).get_property(attr)
                d[prop].append(h)
            except KeyError as e:
                raise KeyError('Node {0} has no property: {1}'.format(h, attr))
        return d
    def host_list(self):
        #self.waitall()
        return [(name, h.default_iface.ip) for name, h in sorted(self.hosts_dict.items(), key=lambda x: x[0]) if h.default_iface is not None]
    def etchosts(self):
        return '127.0.0.1\tlocalhost\n' + ''.join(['{1}\t{0}\n'.format(*x) for x in self.host_list()])
    def adm_etchosts(self):
        return '127.0.0.1\tlocalhost\n' + ''.join(['{1}\t{0}\n'.format(*x) for x in self.adm_host.node_list()])
    def __getitem__(self, key):
        if key == 'nextRealHost': # nextRealHost is magic item to get host IP from pool
            if self.args and self.args.dry_run:
                ret = '127.0.0.1' # placeholder
            else:
                ret = self.real_hosts.pop(0)
        elif key == 'hosts':
            ret = str(list(self.hosts_dict.keys()))
        elif key == 'hostList':
            ret = ' '.join(h.name for h in sorted(self.hosts_dict.keys()))
        elif key == 'pwd':
            ret = os.getcwd()
        else:
            ret = self.find_host(key)
        return ret
    def __iter__(self):
        for h in self.hosts_dict.values():
            yield future_wrapper(h)
    def rest_api(self):
        try:
            self.rest_api_manager.start()
        except OSError as e:
            # If we cannot bind to the REST API endpoint, make sure we clean
            # up properly before passing the exception up the stack
            if self.adm_host:
                self.adm_host.close()
            if self.bridges:
                self.bridges.close_real_hosts()
            raise e

class HostPoolSubstitutionDict(dict):
    def __init__(self, hp, locals=None, extra=None):
        self.parent = hp
        kwargs = self.parent.hosts_dict
        super().__init__(**kwargs)
        if locals is not None:
            self.update(locals)
        if extra is not None:
            self.update(extra)
    def __missing__(self, key):
        #print("missing called")
        try:
            return self.parent[key]
        except KeyError:
            return '{0}{1}{2}'.format('{', key, '}')

class InlineExpressionEvaluator(object):
    builtins = {
        fn: getattr(__import__('builtins'), fn) for fn in \
            ('sum', 'min', 'max', 'len',
            'oct', 'chr', 'ord', 'ascii',
            'float', 'int', 'str', 'bool', 'list', 'tuple', 'dict',)
    }
    @classmethod
    def safe_eval(cls, expr, locals=None, no_builtins=False):
        return eval(expr,
                {'__builtins__': {} if no_builtins else cls.builtins},
                {} if locals is None else locals)
    def __init__(self, line, locals=None):
        if locals is None:
            locals = {}
        self.line = re.sub(r'({{(.*?)}})', lambda m: str(self.safe_eval(m.group(2), locals=locals)), line)
    def get_line(self):
        return self.line

class Interface(object):
    DEFAULT_NAME = 'eth0'
    def __init__(self, parent=None):
        self.parent = parent
        self.name = self.DEFAULT_NAME
        self.addr = None
        self.__mac = None
        self.latency_class = 1
        self.__endpoint = None
        self.__neighbors = set([])
        self.tc_callback = False
        self.shaper = {
            'burst': '15k',
            'latency': 15 * 8,
            'delay': '0.05ms',
        }
        self.__lock = threading.Lock()
        # Interface starts locked to keep other threads from changing parameters of the underlying interface until the link has been created and root TBF has been configured
        # In case there is no underlying interface, call self.unlock() for self.init_shaper() with no parent
        self.lock()
    def init_shaper(self, *args, **kwargs):
        if self.parent is not None:
            # init root TBF
            self.parent.tcraw('qdisc add dev {0} root handle 1: tbf rate 100Mbit burst {1} latency {2}ms'.format(
                self.name,
                self.shaper['burst'],
                self.shaper['latency']), **kwargs)
            self.parent.tcraw('qdisc add dev {0} parent 1: handle {1}0: netem delay {2}'.format(
                self.name,
                self.latency_class,
                args[0] if len(args) > 0 else self.shaper['delay']), **kwargs)
            # add del callback if parent is set, even if exec_ failed
            if 'ns' not in kwargs:
                self.parent.schedule_cleanup_command('tc qdisc del dev {0} root'.format(self.name))
            self.tc_callback = True
        self.unlock()
    def shape_delay(self, *args, **kwargs):
        self.lock()
        dev = self.name
        if 'modifier' in kwargs:
            modifier = kwargs['modifier']
        else:
            modifier = 'add' if not self.tc_callback else 'change'
        cmd = 'tc qdisc {0} dev {2} parent 1: handle {1}0: netem delay {3}'.format(modifier, self.latency_class, dev, ' '.join(args))
        self.parent.exec_(cmd, **kwargs)
        self.unlock()
    def shape_bandwidth(self, bw, **kwargs):
        self.lock()
        self.parent.tcraw('qdisc change dev {0} root handle 1: tbf rate {1} burst {2} latency {3}ms'.format(
            self.name,
            bw,
            self.shaper['burst'],
            self.shaper['latency']),
            **kwargs)
        self.unlock()
    def connect(self, if2):
        self.endpoint = if2
        if self.endpoint is not None:
            self.endpoint.endpoint = self
    @property
    def ip(self):
        return str(self.addr.ip)
    @property
    def mask(self):
        return str(self.addr.network.prefixlen)
    def bcast_addr(self):
        return str(self.addr.network.broadcast_address)
    def network(self):
        return IPPool(str(self.addr))
    def network_addr(self):
        return str(self.addr.network)
    @property
    def mac(self):
        return self.__mac
    @mac.setter
    def mac(self, mac):
        self.__mac = mac
    @property
    def endpoint(self):
        return self.__endpoint
    @endpoint.setter
    def endpoint(self, e):
        self.__endpoint = e
        if e is None:
            self.__neighbors = set([])
        else:
            self.__neighbors.add(e)
    @property
    def neighbors(self):
        return iter(self.__neighbors)
    def lock(self):
        self.__lock.acquire()
    def unlock(self):
        self.__lock.release()
    def __repr__(self):
        return str(self)
    def __str__(self):
        return str(self.addr)
    @staticmethod
    def build(dev, ipmask, mac, parent=None):
        # FIXME inconsistency: building w/ip,mask vs. ipmask (as str)
        iface = Interface(parent=parent)
        iface.name = dev
        iface.addr = ipaddress.ip_interface(ipmask)
        iface.mac = mac
        return iface

class CGroup(object):
    def __init__(self, name, types, parent=None):
        self.parent = parent
        self.name = name
        # cpuset params
        self.cfs_period = 100000
        self.cfs_quota = -1
        self.shares = 1024
        #
        self.types = types
        self.type_list = types.split(',')
        controller_name = '{0}:{1}'.format(types, name)
        self.parent.exec_('cgcreate -g {0}'.format(controller_name))
        self.parent.del_cmds.append('sync') # FIXME workaround
        self.parent.del_cmds.append('cgdelete -g {0}'.format(controller_name))
        if 'cpuset' in self.type_list:
            numa_node, unused_core = self.parent.real_host.get_unused_core()
            #print("DEBUG ", numa_node, unused_core, name)
            # init cpuset.mem and cpuset.cpus since debian doesn't do it for us
            if self.parent and self.parent.args and self.parent.args.cpu_exclusive:
                self.parent.exec_('cgset -r cpuset.mems={0} {1}'.format(numa_node, name))
                self.parent.exec_('cgset -r cpuset.cpus={0} {1}'.format(unused_core, name))
                self.parent.exec_('cgset -r cpuset.cpu_exclusive=1 {0}'.format(name))
            else:
                self.parent.exec_('cgset -r cpuset.mems={0} {1}'.format(self.parent.real_host.get_numa_range(), name))
                self.parent.exec_('cgset -r cpuset.cpus={0} {1}'.format(self.parent.real_host.get_core_range(), name))
    def set_cpu_shares(self, shares):
        self.shares = shares
        self.parent.exec_('cgset -r cpu.shares={1} {0}'.format(self.name, shares))
    def set_cfs_period(self, period):
        self.cfs_period = period
    def set_cfs_quota(self, quota):
        self.cfs_quota = quota
        self.parent.exec_('cgset -r cpu.cfs_period_us={0} {1}'.format(self.cfs_period, self.name))
        self.parent.exec_('cgset -r cpu.cfs_quota_us={0} {1}'.format(self.cfs_quota, self.name))

class Range(object):
    def __init__(self, r):
        self.tokens = r.split('-')
    def __iter__(self):
        start = int(self.tokens[0])
        end = start
        if len(self.tokens) > 1:
            end = int(self.tokens[1])
        for r in range(start, end+1):
            yield r

class CoreRange(object):
    def __init__(self, r):
        self.r = r
        self.range_tokens = r.split(',')
        self.iter = iter(self)
    def get_core_range(self):
        return self.r
    def get_unused_core(self):
        return next(self.iter)
    def __iter__(self):
        for token in self.range_tokens:
            for core in Range(token):
                yield core
    def __str__(self):
        return self.r
    def __repr__(self):
        return str(self)

class RealHostTopoVhostDummy(object):
    def exec_(self, cmd):
        return '''Architecture:          x86_64
CPU op-mode(s):        32-bit, 64-bit
Byte Order:            Little Endian
CPU(s):                4
On-line CPU(s) list:   0-3
Thread(s) per core:    2
Core(s) per socket:    2
Socket(s):             1
NUMA node(s):          1
Vendor ID:             GenuineIntel
CPU family:            6
Model:                 58
Model name:            Intel(R) Core(TM) i7-3537U CPU @ 2.00GHz
Stepping:              9
CPU MHz:               817.285
CPU max MHz:           3100,0000
CPU min MHz:           800,0000
BogoMIPS:              4989.10
Virtualization:        VT-x
L1d cache:             32K
L1i cache:             32K
L2 cache:              256K
L3 cache:              4096K
NUMA node0 CPU(s):     0-3
Flags:                 fpu vme de pse tsc msr pae mce cx8 apic sep mtrr pge mca cmov pat pse36 clflush dts acpi mmx fxsr sse sse2 ss ht tm pbe syscall nx rdtscp lm constant_tsc arch_perfmon pebs bts rep_good nopl xtopology nonstop_tsc aperfmperf eagerfpu pni pclmulqdq dtes64 monitor ds_cpl vmx est tm2 ssse3 cx16 xtpr pdcm pcid sse4_1 sse4_2 x2apic popcnt tsc_deadline_timer xsave avx f16c rdrand lahf_lm epb tpr_shadow vnmi flexpriority ept vpid fsgsbase smep erms xsaveopt dtherm ida arat pln pts
'''

class RealHostTopoVhostDummyOpteron(object):
    def exec_(self, cmd):
        return '''Architecture:          x86_64
CPU op-mode(s):        32-bit, 64-bit
Byte Order:            Little Endian
CPU(s):                64
On-line CPU(s) list:   0-63
Thread(s) per core:    2
Core(s) per socket:    8
Socket(s):             4
NUMA node(s):          8
Vendor ID:             AuthenticAMD
CPU family:            21
Model:                 1
Model name:            AMD Opteron(TM) Processor 6276
Stepping:              2
CPU MHz:               1400.000
CPU max MHz:           2300,0000
CPU min MHz:           1400,0000
BogoMIPS:              4599.46
Virtualization:        AMD-V
L1d cache:             16K
L1i cache:             64K
L2 cache:              2048K
L3 cache:              6144K
NUMA node0 CPU(s):     0-7
NUMA node1 CPU(s):     8-15
NUMA node2 CPU(s):     16-23
NUMA node3 CPU(s):     24-31
NUMA node4 CPU(s):     32-39
NUMA node5 CPU(s):     40-47
NUMA node6 CPU(s):     48-55
NUMA node7 CPU(s):     56-63
'''

class RealHostTopo(object):
    '''Parses lscpu information to extract NUMA topology, iterates cores by NUMA core (round-robin)'''
    def __init__(self, vhost):
        self.numa_nodes = {}
        self.lscpu = vhost.exec_('lscpu')
        self.reset_iter()
    @staticmethod
    def __get_key(line):
        return line.split(':')[0].strip()
    @staticmethod
    def __get_value(line):
        return line.split(':')[-1].strip()
    def __parse_topo(self, lscpu):
        lines = lscpu.splitlines()
        for line in lines:
            if line.startswith('CPU(s)'):
                self.cpus = self.__get_value(line)
            elif line.startswith('On-line CPU(s)'):
                self.cpu_range = CoreRange(self.__get_value(line))
            elif line.startswith('NUMA node(s)'):
                self.numa_node_count = int(self.__get_value(line))
            elif line.startswith('NUMA'):
                k = self.__get_key(line)
                v = self.__get_value(line)
                numa_node = k.split()[1]
                self.numa_nodes[numa_node] = CoreRange(v)
    def get_unused_core(self):
        return next(self.core_generator)
    def get_numa_range(self):
        return '0' if self.numa_node_count <= 1 else '0-{0}'.format(self.numa_node_count-1)
    def get_core_range(self):
        prev = None; last = None
        r = []
        for num, c in self.numa_nodes.items():
            r.append('{0}'.format(c))
        return ','.join(r)
    def reset_iter(self):
        self.__parse_topo(self.lscpu)
        self.core_generator = iter(self)
    def __iter__(self):
        numa_num = 0
        for num in self.cpu_range:
            yield (numa_num, self.numa_nodes['node{0}'.format(numa_num)].get_unused_core())
            numa_num = (numa_num + 1) % self.numa_node_count

# RealHostTopo for dry-run
class FakeHostTopo(RealHostTopo):
    def __init__(self, vhost=None):
        self.numa_nodes = {}
        self.lscpu = RealHostTopoVhostDummyOpteron().exec_('lscpu')
        self.reset_iter()

class SSHConnectionWrapper(object):
    @classmethod
    def connect(cls, host):
        logger.debug("SSH Connect: {0}".format(host))
        client = paramiko.client.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.load_system_host_keys()
        client.connect(host,
                username='root',
                gss_trust_dns=False)
        #        #timeout=10000,
        #        #banner_timeout=100000)
        return client
    def __init__(self, conn, peer=None, release_action=None):
        self.conn = conn
        self.peer = peer
        if self.peer is None:
            self.peer = self.get_connection().get_transport().getpeername()[0]
        self.release_action = release_action
    def __del__(self):
        if self.release_action is not None:
            self.release_action(self)
    def get_connection(self):
        return self.conn
    def get_peername(self):
        return self.peer
    def get_channel(self):
        try:
            session = self.get_connection().get_transport().open_session()
        except paramiko.ssh_exception.SSHException:
            logger.debug('Reconnecting (host: {0}) ...'.format(self.peer))
            self.conn = self.connect(self.peer)
            session = self.get_connection().get_transport().open_session()
        return session

class SSHConnectionManager(object):
    def __init__(self, host, pool_size=2):
        self.host = host
        self.pool_size = pool_size
        self.lock = threading.Lock() # allocated_conns lock
        self.sem = threading.Semaphore(self.pool_size) # connection semaphore
        self.allocated_conns = pool = deque()
        logger.info("SSH Connection Init: {0} ({1} connections)".format(host, self.pool_size))
        # Use separate ThreadPoolExecutor to start connections with limited parallelism
        # Keep it below 10 due to MaxSessions default limit of 10 (in Debian/Ubuntu)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=9)
        for conn in executor.map(lambda _: self.create_connection(host), range(self.pool_size)):
            pool.append(conn)
        executor.shutdown(wait=True)
    def create_connection(self, host):
        return SSHConnectionWrapper.connect(host)
    def take(self):
        self.sem.acquire()
        self.__lock()
        conn = self.allocated_conns.pop()
        #logger.debug('Allocating connection conn={} sem={}'.format(conn, self.sem))
        self.__unlock()
        return conn
    def release(self, conn):
        self.__lock()
        self.allocated_conns.append(conn.get_connection())
        self.__unlock()
        self.sem.release()
        #logger.debug('Releasing connection conn={} sem={}'.format(conn, self.sem))
    def __lock(self):
        self.lock.acquire()
    def __unlock(self):
        self.lock.release()
    def connect(self):
        return SSHConnectionWrapper(self.take(),
                peer=self.host,
                release_action=self.release)

class RealHost(object):
    ssh_timeout = 60
    def __init__(self, name, vhost, cpu_exclusive=False):
        self.name = name
        self.conn_man = SSHConnectionManager(self.name, pool_size=vhost.args.max_parallel_workers+1)
        self.thread_local = threading.local()
        self.cpu_exclusive = cpu_exclusive
        self.vhost = vhost
        vhost.real_host = self
        self.topo = RealHostTopo(self.vhost)
    def get_unused_core(self):
        try:
            core = self.topo.get_unused_core()
        except StopIteration as e:
            if self.cpu_exclusive:
                raise e
            else:
                self.topo.reset_iter()
                core = self.topo.get_unused_core()
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            raise e
        #print("DEBUG  get_unused_core ->", core)
        return core
    def get_numa_range(self):
        return self.topo.get_numa_range()
    def get_core_range(self):
        return self.topo.get_core_range()
    def get_connection(self):
        conn = getattr(self.thread_local, 'connection', None)
        if conn is None:
            #logger.debug('get_connection on thread {} -> conn is None, creating a new one'.format(threading.currentThread()))
            conn = self.set_connection(self.conn_man.connect())
        return conn
    def get_channel(self):
        return self.get_connection().get_channel()
    def set_connection(self, conn):
        self.thread_local.connection = conn
        #logger.debug('set_connection on thread {} -> {}'.format(threading.currentThread(), self.thread_local.connection))
        return self.thread_local.connection
    def run(self, *args, timeout=None, **kwargs):
        retry_timeout = self.ssh_timeout if timeout is None else timeout
        timeout_start = time.time()
        success = False
        i = 0
        mult = 1
        chan = None
        while time.time() < timeout_start + retry_timeout:
            if i > 0:
                time.sleep(mult*random.random())
                mult <<= 1
            i += 1
            try:
                chan = self.get_channel()
                chan.exec_command(*args, **kwargs)
                success = True
                break
            except paramiko.ssh_exception.SSHException as e:
                logger.error(traceback.format_exc())
                continue
            except paramiko.ssh_exception.NoValidConnectionsError as e:
                logger.error(traceback.format_exc())
                continue
            except EOFError as e:
                logger.error(traceback.format_exc())
                continue
            except Exception as e:
                logger.error(traceback.format_exc())
                if str(e) == 'Error reading SSH protocol banner':
                    continue
                break
        if not success:
            raise RuntimeError('SSH connection timed out, check maximum number of connections.')
        return (chan.makefile_stdin(), chan.makefile(), chan.makefile_stderr())

class FakeChannelStream(object):
    def __init__(self, channel=None):
        self.__channel = channel
    @property
    def channel(self):
        return self.__channel
    @channel.setter
    def channel(self, value):
        self.__channel = value
    def read(self):
        return b""

class FakeChannel(object):
    def exec_command(self, *args, **kwargs):
        pass
    def makefile_stdin(self):
        return FakeChannelStream(self)
    def makefile(self):
        return FakeChannelStream(self)
    def makefile_stderr(self):
        return FakeChannelStream(self)
    def recv_exit_status(self):
        return 0

class FakeRealHost(RealHost):
    def __init__(self, name, vhost=None, cpu_exclusive=False):
        self.vhost = vhost
        self.topo = FakeHostTopo()
        self.cpu_exclusive = cpu_exclusive
        self.name = 'fake'
    def get_channel(self):
        return FakeChannel()

class RealHostPool(object):
    host_pool = {}
    @classmethod
    def get_real_host(cls, name, vhost=None, args=None):
        try:
            ret = cls.host_pool[name]
        except KeyError:
            if args.dry_run:
                ret = FakeRealHost(name, vhost=vhost)
            else:
                ret = RealHost(name, vhost, cpu_exclusive=args.cpu_exclusive)
            cls.host_pool[name] = ret
        return ret
    @classmethod
    def reset(cls):
        cls.host_pool = {}

def jointake(src_strlist, max_cmdline, sep=';'):
    count = 0
    i = 0
    padding = len(sep)
    while i < len(src_strlist) and count < max_cmdline:
        count += len(src_strlist[i]) + padding
        i += 1
    return (sep.join(src_strlist[:i]), src_strlist[i:])

def retry_until_success(fn, retries=3, delay=1):
    muted_exc = None
    while retries > 0:
        try:
            return fn()
        except Exception as e:
            muted_exc = e
        finally:
            retries -= 1
            time.sleep(delay)
    raise muted_exc

class PipeHandler(object):
    def __init__(self, host):
        self.host = host
        self.thread = None
        self.channels = None
    def cleanup(self):
        logger.debug('Shutting down PipeHandler {}'.format(self.channels))
        if self.channels:
            for c in self.channels:
                c.close()
    def set_thread(self, thread):
        self.thread = thread
    def set_pipe_channels(self, *args):
        self.channels = args

class BaseHost(object):
    DEFAULT_MTU = 1500
    GENEVE_HEADER_LEN = 64
    REMOTE_HELPER_DIR = '/tmp/helpers'
    LOCAL_HELPER_DIR = '/helpers'

    def __init__(self, name, ip, args=None):
        self.dry_run = args is not None and args.dry_run
        self.name = name
        self.ip = ip
        self.username = None
        self.pool = None
        self.topo = None
        self.args = args
        self.lock = threading.Lock()
        self.threads = []
        self.pipe_handler = PipeHandler(self)

        # services
        self.service_list = []

        # command list to be called on close
        self.del_cmds = collections.deque()
        self.pending_stdout = []

        # status
        self.mtu = None
        self.mtu_cache = {}
        self.tc_callback = False
        self.mtu_callback = False
        self.ns_callback = False
        self.ifaces = {}
        self.adm_iface = None
        self.__real_default_iface = None
        # TODO default_iface should be configured per netns
        self.default_iface = None
        self.iface_next_num = 0

        # registered helpers
        self.helpers = []

        # exec
        self.exec_exit_code = None
        self.exec_stdout = None
        self.exec_stderr = None

        self.current_exec_batch = None

        # node properties
        self.properties = {}

        # parameters
        self.connection_timeout = 60
    def __del__(self):
        ignore_exceptions(self.cleanup)
    def set_property(self, name, value):
        self.properties[name] = value
    def get_property(self, name):
        return self.properties[name]
    @property
    def real_default_iface(self):
        return self.__real_default_iface if self.args and not self.args.dry_run else Interface()
    @real_default_iface.setter
    def real_default_iface(self, value):
        self.__real_default_iface = value
    def __getattr__(self, name):
        # getattr shortcut to get iface info using dot notation
        if name in self.ifaces:
            return self.ifaces[name]
        else:
            try:
                value = self.__dict__[name]
            except KeyError:
                raise AttributeError('No attribute found: {0}'.format(name))
            return value
    def _service(self, cmd, ns=None, **kwargs):
        name = cmd.split()[0] # 'argv[0]'
        if name in self.helpers:
            return self.exec_(cmd, ns=ns, service=True, **kwargs)
    def service_pids(self):
        return self.service_list
    def new_iface_name(self):
        name = '{0}veth{1}'.format('{0}-'.format(self.name) if self.args.use_iface_prefix else '', self.iface_next_num)
        self.iface_next_num += 1
        return name
    def init_cgroup(self, cgname, types):
        self.cgroup = CGroup(cgname, types, parent=self)
    def cgroup_get(self):
        return self.cgroup
    def netns(self, name):
        logger.info('Creating virtual host: {0}'.format(name))
        self.exec_batch('ip netns add {0}'.format(name))
        self.exec_batch('ip link set dev lo up', ns=name)
        self.exec_batch('mkdir -p /etc/netns/{0}'.format(name))
        self.exec_batch('touch /etc/netns/{0}/hosts'.format(name))
        self.exec_batch_commit()
        self.schedule_cleanup_command('rm -rf /etc/netns/{0}'.format(name))
        self.schedule_cleanup_command('ip netns delete {0}'.format(name))
        self.schedule_cleanup_command('for pid in $(ip netns pids {0}); do kill $pid; done'.format(name))
    def register_veth(self, ns, dev1, dev2, ipmask, is_adm=False, connect_to=None, now=False):
        iface = Interface.build(dev2, ipmask, None, parent=self)
        self.ifaces[dev2] = iface
        if is_adm:
            self.adm_iface = iface
            iface.connect(self.pool.adm_host.default_iface)
        else:
            # default interface if it's the first one
            if self.default_iface is None:
                self.default_iface = iface
            # set endpoint if it exists
            endpoint = connect_to
            if endpoint is not None:
                iface.connect(endpoint)
        if now:
            self.veth(ns, dev1, dev2, ipmask, is_adm=is_adm)
        return iface
    def veth(self, ns, dev1, dev2, ipmask, is_adm=False):
        #print(ns, dev1, dev2, ipmask)
        temp_dev_name = 'veth{0}'.format(random_string(6))
        iface = self.ifaces[dev2]
        if self.args.geneve_tunnels:
            peer_dev_name = 'v{0}{1}'.format(ns, dev2)
            parent_mtu = self._getMTU(dev1)
            mtu = self.DEFAULT_MTU if parent_mtu - self.GENEVE_HEADER_LEN > self.DEFAULT_MTU else parent_mtu - self.GENEVE_HEADER_LEN
            # ip link add type veth seems to run into unexpected 'Operation not permitted' errors if there are too many concurrent operations.
            # This is usually solved by retrying, which is what we do here (with a huge delay).
            retry_until_success(lambda: self.exec_('ip link add {0} type veth peer name {1} mtu {2}'.format(peer_dev_name, temp_dev_name, mtu)), retries=3)
            #self.schedule_cleanup_command('ip link del {0}'.format(peer_dev_name))
            if self.pool is not None:
                self.pool.bridges.add_to_bridge(peer_dev_name, iface)
        else:
            self.exec_('ip link add link {0} {1} type macvlan mode bridge'.format(dev1, temp_dev_name))
        mac = self.get_mac_address(temp_dev_name)
        iface.mac = mac

        # move and rename
        self.exec_('ip link set dev {0} name {1} netns {2}'.format(temp_dev_name, dev2, ns))

        # set address, UP
        self.exec_('ip addr add {0} broadcast {1} dev {2}'.format(ipmask, iface.bcast_addr(), dev2), ns=ns)
        self.exec_('ip link set dev {0} up'.format(dev2), ns=ns)
        if not self.args.geneve_tunnels:
            if is_adm:
                # adm interface -> do not reply ARP requests from other interfaces/subnets
                self.exec_('sysctl -w net.ipv4.conf.{0}.arp_ignore=2'.format(dev2), ns=ns)
            else:
                # disable ARP on normal macvlan interfaces
                self.exec_('ip link set dev {0} arp off'.format(dev2), ns=ns)
            # flush ARP table just in case
            self.exec_('ip neigh flush dev {0}'.format(dev2), ns=ns)
        return iface
    def lookup_iface_by_addr(self, addr):
        # FIXME move to class Interface?
        o = self.exec_('ip addr show')
        if o is None:
            # return default interface
            iface = Interface(parent=self)
            return iface
        cur = None
        iface = None
        for line in o.splitlines():
            m = re.match(r'^\d+: (\w+).*$', line)
            if m is not None:
                cur = m.group(1)
                continue
            m = re.match(r'^[\t ]*inet ((\d+\.\d+\.\d+\.\d+)/(\d+)) .*$', line)
            if m is not None:
                assert(cur != None)
                if m.group(2) == addr:
                    iface = Interface(parent=self)
                    iface.name = cur
                    iface.addr = m.group(1)
                    iface.mac = self.get_mac_address(iface.name)
                    break
        return iface
    def lookup_ip_by_iface(self, iface):
        # FIXME move to class Interface?
        o = self.exec_('ip addr show {0}'.format(iface))
        if o is None:
            # return default interface
            iface = Interface(parent=self)
            return iface
        for line in o.splitlines():
            m = re.match(r'^[\t ]*inet (\d+\.\d+\.\d+\.\d+)/(\d+.*) brd (\d+\.\d+\.\d+\.\d+).*$', line)
            if m is not None:
                return m.group(1)
        return None
    def default_route(self):
        o = self.exec_('ip route')
        if o is not None:
            for line in o.splitlines():
                m = re.match(r'^default via \d+\.\d+\.\d+.\d+ dev (.*?) .*$', line)
                if m is not None:
                    return self.lookup_ip_by_iface(m.group(1))
        return '127.0.0.1'
    def lookup_route(self, addr, ns=None):
        # dummy data if dry-run
        if self.args and self.args.dry_run:
            return 'eth0', None
        o = self.exec_('ip route get {0}'.format(addr), ns=ns)
        if o is not None:
            o = o.splitlines()[0]
            m = re.search('dev (.*?) *src (.*?)$', o)
            return m.group(1), m.group(2)
        return 'eth0', None
    def arp(self, cmd, *args, **kwargs):
        dev, _ = self.lookup_route(args[0], **kwargs)
        if cmd == 'add':
            self.exec_batch('ip neigh add {1} lladdr {2} nud permanent dev {0}'.format(dev, *args), **kwargs)
        #else: TODO
        if 'ns' not in kwargs:
            self.schedule_cleanup_command('ip neigh del {0}'.format(args[0]))
    def shape_delay(self, dev, *args, **kwargs):
        try:
            self.ifaces[dev].shape_delay(*args, **kwargs)
        except IOError as e:
            raise RuntimeError('tc exited abnormally, exit code: {0}, stderr: {1}'.format(self.get_exec_exit_code(), e))
    def shape_bandwidth(self, dev, *args, **kwargs):
        try:
            self.ifaces[dev].shape_bandwidth(*args, **kwargs)
        except IOError as e:
            raise RuntimeError('tc exited abnormally, exit code: {0}, stderr: {1}'.format(self.get_exec_exit_code(), e))
    def tcraw(self, *args, **kwargs):
        cmd = 'tc {0}'.format(*args)
        self.exec_(cmd, **kwargs)
    def route(self, net, dev, batch=False, ns=None):
        fmt = 'ip route add {0} via {1}'
        exec_ = self.exec_
        if batch:
            exec_ = self.exec_batch
        exec_(fmt.format(net, self.ifaces[dev].endpoint.ip), ns=ns)
    def get_mac_address(self, dev, ns=None):
        mac = None
        o = self.exec_('ip link show {0}'.format(dev), ns=ns)
        if o is not None:
            lines = o.splitlines()
            if len(lines) > 0:
                try:
                    type, mac = re.match(r'^.*?link/(.*?) (.*?) brd.*$', lines[1]).groups()
                except AttributeError:
                    raise RuntimeError('Cannot retrieve MAC address from interface {0}'.format(dev))
                if type not in ['ether', 'infiniband']:
                    raise RuntimeError('Invalid type for interface {0}: {1}'.format(type, dev))
        return mac
    def set_link(self, dev, key, *args):
        if self.mtu is None:
            self.mtu = self._getMTU(dev)
        cmd1 = 'ip link set dev {0} {1} {2}'.format(dev, key, *args)
        cmd2 = 'ip route flush cache'
        try:
            self.exec_(cmd1)
            self.exec_(cmd2)
        except IOError as e:
            logger.warning('Ignoring: {0}'.format(e))
        if key == 'mtu':
            self._update_mtu_cache(dev, int(args[0]))
        if key == 'mtu' and not self.mtu_callback:
            # add del callback even if exec_ failed
            self.schedule_cleanup_command('ip link set dev {0} mtu {1}'.format(dev, self.mtu))
            self.mtu_callback = True
    def sysctl(self, var, value, **kwargs):
        o = None
        # if we're changing a non-netns sysctl entry, record original value so that we can restore it later
        if 'ns' not in kwargs:
            o = self.exec_('sysctl -n {0}'.format(var), **kwargs)
        self.exec_('sysctl -w {0}={1}'.format(var, value), **kwargs)
        if o is not None:
            self.schedule_cleanup_command('sysctl -w {0}={1}'.format(var, o.rstrip('\n')))
    def shell(self, **kwargs):
        dry_run = self.dry_run
        cmd = "/bin/bash"
        try:
            cmd = " su {0} -c {1}".format(kwargs['username'], cmd)
        except KeyError:
            pass
        ns = ""
        try:
            ns = ' ip netns exec {0} '.format(kwargs['ns'])
        except KeyError:
            pass
        cmd = 'ssh -tt {0}@{1}{2}{3}'.format(self.username, self.ip, ns, cmd)
        #print('DEBUG ', cmd)
        if not dry_run:
            p = pexpect.pty_spawn.spawn(cmd, env=self.pool.environ())
            pty_size = shutil.get_terminal_size()
            p.setwinsize(pty_size[1], pty_size[0])
            p.interact(chr(29))
    def setup_pipe(self):
        pipe_path = '/var/run/sherlockfog/{}'.format(self.name)
        # Netcat needs to be run on the netns (even though this is not really a requirement), so that the shutdown phase can properly kill the nc processes by enumerating all PIDs on the netns
        # This requires the containers to be created already, so the pipe cannot be configured early in the initialization process
        # FIXME: this would break non-netns executions, but maybe we want to remove that feature completely
        pipe_cmd = 'mkdir -p {pipe_dir}; ip netns exec {host_name} nc -lkNU {pipe_path}'.format(host_name=self.name, pipe_dir=os.path.dirname(pipe_path), pipe_path=pipe_path)
        logger.debug('setup_pipe: pipe_cmd={}'.format(pipe_cmd))
        cmd = self.build_cmdline(pipe_cmd)
        conn = self.real_host.get_connection()
        def setup_pipe_bound():
            self.real_host.set_connection(conn)
            logger.info('Setting up communication pipe with {} -> {}'.format(self.name, self.ip))
            i, o, e = self.real_host.run(cmd, timeout=self.connection_timeout)
            self.pipe_handler.set_pipe_channels(i, o, e)
            exit_code = 0
            try:
                for line in iter(i.readline, ''):
                    logger.info('Remote command from {}: {}'.format(self.name, line.strip()))
                    self.exec_remote(line, o.channel)
            except IOError as e:
                exit_code = o.channel.recv_exit_status()
            finally:
                log_command(self.ip, 'Pipe event loop exited with err={}'.format(exit_code))
        t = self.setup_timer(lambda: setup_pipe_bound(), at=0)
        logger.debug('Setting up pipe thread {}'.format(t))
        self.pipe_handler.set_thread(t)
        self.del_cmds.append('rm -rf {}'.format(pipe_path))
    def build_cmdline(self, cmd, username=None, cgroup=None, ns=None, docker=False, uts_ns=False, service=False):
        prefix = ''
        suffix = ''
        if docker:
            # Docker mode: run directly inside container
            opt = '-u {0} -w {1} '.format(username, os.getcwd()) if username is not None else ''
            return 'docker exec {0}{1} {2}'.format(opt, self.name, cmd)
        if service:
            prefix = 'PATH="{0}":"$PATH" '.format(self.remote_helper_dir)
            #suffix = ' &'
        if cgroup:
            prefix = '{0}cgexec -g {1}:{2} '.format(prefix, self.cgroup.types, self.cgroup.name)
        if uts_ns:
            prefix = '{0}unshare -u '.format(prefix)
        if ns is not None:
            prefix = '{0}ip netns exec {1} '.format(prefix, ns)
        if username is not None and self.username == 'root':
            cmd = "su {0} -c 'cd {1} && ({2})'".format(username, os.getcwd(), cmd)
        cmd = '{0}{1}{2}'.format(prefix, cmd, suffix)
        return cmd
    def exec_batch(self, cmd, username=None, ns=None, uts_ns=False, **kwargs):
        dry_run = self.dry_run
        cmd = self.build_cmdline(cmd,
                username=username,
                ns=ns,
                uts_ns=uts_ns,
                service=False)
        log_command(self.ip, cmd)
        if not dry_run:
            if self.current_exec_batch is None:
                self.current_exec_batch = []
            self.current_exec_batch.append(cmd)
    def exec_batch_commit(self, ignore_stderr=False, max_cmdline=4096):
        out = None
        if self.current_exec_batch is None:
            logger.warning('calling exec_batch_commit without a valid command list')
            return
        for cmd in self.current_exec_batch:
            log_command(self.ip, cmd)
        while self.current_exec_batch is not None and len(self.current_exec_batch) > 0:
            # FIXME unsafe - https://xkcd.com/327/
            cmd, self.current_exec_batch = jointake(self.current_exec_batch, max_cmdline, sep=';')
            i, o, e = self.real_host.run(cmd, timeout=self.connection_timeout)
            out = o.read().decode('utf-8').rstrip('\n') # FIXME only grabbing last output
            err = e.read().decode('utf-8')
            exit_code = o.channel.recv_exit_status()
            if not ignore_stderr and (exit_code or err):
                raise IOError('err[{0}] -> "{2}" stderr: {1}'.format(exit_code, err, cmd))
        self.current_exec_batch = None
        return out
    def exec_(self, cmd, username=None, cgroup=None, docker=False, ns=None, uts_ns=False, service=False, at=None, **kwargs):
        dry_run = self.args.dry_run
        cmd = self.build_cmdline(cmd,
                username=username,
                cgroup=cgroup,
                ns=ns,
                docker=docker,
                uts_ns=uts_ns,
                service=service)
        conn = self.real_host.get_connection()
        def exec_bound(timer=False):
            #logger.debug('exec_bound -> thread={} conn={}'.format(threading.currentThread(), conn))
            if timer:
                # If exec_ is being called from a timer, share connection to real_host with parent caller.
                # Since a timer runs on a different thread, and self.real_host.get_connection() is stored in thread-local storage, we need to copy it to the new thread.
                # If we don't do this, then self.real_host.run will trigger a reconnection, but the thread pool was already initialized, so there are no
                # free slots on the SSHConnectionManager. This would generate a deadlock.
                self.real_host.set_connection(conn)
            log_command(self.ip, cmd)
            i, o, e = self.real_host.run(cmd, timeout=self.connection_timeout)
            if not dry_run and service:
                out = o.readline().rstrip('\n')
                # service must output PID
                if re.match(r'\d+', out) is None:
                    raise IOError('service flag set but process output is not a valid PID {0} {1}'.format(out, e.readlines()))
                #self.schedule_cleanup_command('kill {0}'.format(out))
                self.service_list.append(out)
                self.pending_stdout.append(o)
            else:
                #logger.debug('Read from: {}'.format(o))
                out = o.read().decode('utf-8').rstrip('\n')
                err = e.read().decode('utf-8')
                exit_code = o.channel.recv_exit_status()
                self.set_exec_output(out, err)
                self.set_exec_exit_code(exit_code)
                if (exit_code or err) and err != 'Dump was interrupted and may be inconsistent.\n':
                    raise IOError('err[{0}] -> "{2}" stderr: {1}'.format(exit_code, err, cmd))
            return out
        if not at:
            return exec_bound()
        else:
            t = self.setup_timer(lambda: exec_bound(timer=True), at=at)
            logger.debug('Queuing thread {}'.format(t))
            self.threads.append(t)
            return t
    def setup_timer(self, fn, at):
        logger.debug("Set timer at={0}".format(float(at)))
        t = threading.Timer(float(at), fn)
        t.start()
        return t
    def exec_remote(self, cmd, chan):
        reply = {'err': 'Unhandled case'}
        try:
            d = json.loads(cmd)
        except json.decoder.JSONDecodeError as e:
            reply = {'err': 'Invalid input JSON'}
        else:
            if 'REST' in d.keys():
                if self.pool.rest_api_manager.started:
                    rest_request = requests.get('http://localhost:{}/{}'.format(self.pool.args.rest_api_port, d['REST']))
                    if rest_request.status_code == 200:
                        logger.info('REST CALL {}: {}'.format(d['REST'], rest_request.text))
                        reply = json.loads(rest_request.text)
                    else:
                        reply = {'err': 'REST API call failed', 'status_code': rest_request.status_code}
                else:
                    logger.error('Cannot execute remote command, REST API not started')
                    reply = {'err': 'REST API not started'}
            elif 'warn' in d.keys():
                logger.warning(d['warn'])
                reply = {'warn': 'accepted'}
            elif 'err' in d.keys():
                logger.error(d['err'])
                reply = {'err': 'accepted'}
            elif 'fatal' in d.keys():
                logger.fatal(d['fatal'])
                reply = {'fatal': 'accepted'}
                self.pool.close()
            elif 'cmd' in d.keys():
                try:
                    ExecutionEnvironment(self.pool.topo, self.pool, args=self.pool.args).exec_(d['cmd'].strip())
                except (KeyError, IOError) as e:
                    reply = {'cmd': 'failed', 'err': e.__class__.__name__, 'exception_doc': e.__doc__, 'exception_args': e.args}
                else:
                    reply = {'cmd': 'accepted'}
        chan.send(json.dumps(reply) + os.linesep)
    def install_script(self, script, dest):
        if self.args is not None and self.args.dry_run:
            return None
        contents = None
        if self.local_helper_dir is None:
            self.local_helper_dir = '.'
        try:
            with open(os.path.join(self.local_helper_dir, script), 'r') as f:
                contents = f.read()
        except FileNotFoundError:
            with pkg_resources.open_text('helpers', script) as f:
                contents = f.read()
        if contents is not None:
            self.copy_data(os.path.join(dest, script), contents)
            self.exec_('chmod +x {0}'.format(os.path.join(dest, script)))
            self.helpers.append(script)
    def install_helpers(self):
        self.local_helper_dir = os.path.dirname(os.path.realpath(sys.argv[0])) + self.LOCAL_HELPER_DIR
        self.remote_helper_dir = "{0}-{1}".format(self.REMOTE_HELPER_DIR, self.name)
        dest = self.remote_helper_dir
        self.exec_('mkdir -p {0}'.format(dest))
        # FIXME helpers should be installed on-demand by user script?
        self.install_script('ns-sshd', dest)
        self.schedule_cleanup_command('rm -rf {0}'.format(dest))
    def schedule_cleanup_command(self, cmd):
        self.del_cmds.appendleft(cmd)
    def _getMTU(self, dev):
        return self._cached_mtu_value(dev)
    def _update_mtu_cache(self, dev, value):
        self.mtu_cache[dev] = value
    def _cached_mtu_value(self, dev):
        if dev not in self.mtu_cache:
            value = self.exec_('cat /sys/class/net/{0}/mtu'.format(dev))
            self._update_mtu_cache(dev, int(value) if value else self.DEFAULT_MTU)
        return self.mtu_cache[dev]
    def copy_data(self, fname, contents, **kwargs):
            self.exec_('''cat > {1} <<'EOFSetupTopo'
{0}EOFSetupTopo
                '''.format(contents, fname), **kwargs)
    def ns_hosts(self, ns=None):
        if ns is None:
            ns = self.name
        if self.pool is not None:
            self.copy_data('/etc/netns/{0}/hosts'.format(ns),
                    self.pool.etchosts(),
                    ns=ns)
    def static_arp(self, ns=None):
        if ns is None:
            ns = self.name
        if self.pool is not None:
            # add ARP entries for every endpoint
            for if1 in self.ifaces.values():
                if2 = if1.endpoint
                if if2 is not None:
                    self.arp('add', if2.ip, if2.mac, ns=ns)
            self.exec_batch_commit()
    def static_routes_tree_only(self, ns=None):
        if ns is None:
            ns = self.name
        if self.pool is not None:
            localnets = set(IPUtil.join_ipmask(IPUtil.network_addr(x.ip, x.mask), x.mask) for x in self.ifaces.values())
            #print('localnets: {0}'.format(localnets))
            for if1 in self.ifaces.values():
                remotenets = self.visit_neighbors(if1)
                for r in remotenets:
                    if r not in localnets:
                        debug_route(self, r, if1)
                        self.route(r, if1.name, ns=ns)
            #self.exec_batch_commit()
    def visit_neighbors(self, if0):
        visited = set([])
        nets = set([])
        if if0.endpoint is None:
            return nets
        assert(if0.endpoint.parent is not None)
        pending = collections.deque()
        #print('start: add {0}'.format(if0.endpoint.parent.name))
        pending.append(if0.endpoint.parent)
        visited.add(if0.parent)
        # visit nodes using DFS
        while len(pending) > 0:
            n = pending.pop()
            visited.add(n)
            for i in n.ifaces.values():
                if i.endpoint != if0:
                    nets.add(IPUtil.join_ipmask(IPUtil.network_addr(i.ip, i.mask), i.mask))
                    if i.endpoint is not None and i.endpoint.parent not in visited:
                        pending.append(i.endpoint.parent)
                        #print('add {0}'.format(i.endpoint.parent.name))
        #print(nets)
        return nets
    def ifaces_non_adm(self):
        return {k: v for k, v in self.ifaces.items() if self.adm_iface is None or k != self.adm_iface.name}
    def wait(self):
        for t in self.threads:
            logger.debug('waiting on thread: {}'.format(t))
            t.join()
        self.threads = []
    def get_exec_exit_code(self):
        return self.exec_exit_code
    def set_exec_exit_code(self, code):
        self.exec_exit_code = code
    def get_exec_output(self, *args):
        if len(args) > 0:
            channel = getattr(self, 'exec_{0}'.format(args[0]))
            return channel
        return self.exec_stdout, self.exec_stderr
    def set_exec_output(self, o, e):
        self.exec_stdout, self.exec_stderr = o, e
    def close(self):
        logger.debug('del: {0}'.format(self.name))
        #print('DEBUG: ', self.del_cmds)
        # wait on pending threads
        self.wait()
        # restore network state for host
        self.cleanup()
    def emergency_close(self):
        logger.debug('Forcibly shutting down vhost: {0}'.format(self.name))
        ignore_exceptions(self.cleanup)
    def cleanup(self):
        logger.debug('Destroying virtual host: {0}'.format(self.name))
        self.pipe_handler.cleanup()
        for cmd in self.del_cmds:
            try:
                self.exec_(cmd)
                #self.exec_batch_commit()
            except IOError as e:
                logger.warning('ignoring -> {0}'.format(e))
        self.del_cmds = []

class LocalHostRunner(object):
    name = 'localhost'
    def __init__(self, args=None):
        # If adm interface is enabled, set adm_iface_addr as LocalHostRunner name in order
        # to create tunnels that connect to this local host
        self.args = args
        if args is not None and args.use_adm_ns:
            self.name = self.args.adm_iface_addr
            logger.debug('Administrative interface enabled, setting LocalHost id to {0}'.format(self.name))
    def run(self, cmd, service=False, **kwargs):
        log_command(self.name, cmd)
        process = subprocess.Popen(cmd, shell=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if not service else subprocess.DEVNULL,
            stderr=subprocess.PIPE if not service else subprocess.DEVNULL)
        process.stdout, process.stderr = process.communicate()
        return process

class LocalHost(BaseHost):
    def __init__(self, name, *args, **kwargs):
        super().__init__(name, 'localhost', *args, **kwargs)
        self.real_host = LocalHostRunner(**kwargs)
        self.username = 'root'
    def exec_(self, cmd, username=None, cgroup=None, ns=None, docker=False, uts_ns=False, service=False, at=None, **kwargs):
        dry_run = self.args.dry_run
        cmd = self.build_cmdline(cmd,
                username=username,
                cgroup=cgroup,
                ns=ns,
                docker=docker,
                uts_ns=uts_ns,
                service=service)
        #log_command('local', cmd)
        if not dry_run:
            process = self.real_host.run(cmd, service=service)
            o = process.stdout
            e = process.stderr
            exit_code = process.returncode
            if service: # We don't care about the output if running a daemon
                return ""
            out = o.decode('utf-8').rstrip('\n')
            err = e.decode('utf-8')
            if exit_code or err:
                raise IOError('err[{0}] -> "{2}" stderr: {1}'.format(exit_code, err, cmd))
            return out
        else:
            return ""
    def exec_batch_commit(self, ignore_stderr=False, max_cmdline=4096):
        out = None
        if self.current_exec_batch is None:
            logger.warning('calling exec_batch_commit without a valid command list')
            return
        for cmd in self.current_exec_batch:
            # FIXME only grabbing last output
            out = self.exec_(cmd)
        self.current_exec_batch = None
        return out

class AdminHost(LocalHost):
    def __init__(self, *args, **kwargs):
        super().__init__('adm', *args, **kwargs)

        # install ssh helpers & co
        self.install_helpers()

        # setup adm NS
        self.netns(self.name)

        # default interface
        self.real_default_iface = self.lookup_iface_by_addr(self.args.adm_iface_addr)

        # reachable nodes
        self.adm_endpoints = []

        # enable ssh
        self._service('ns-sshd {0}'.format(self.name),
                uts_ns=True,
                ns=self.name)

    def add_host(self, iface):
        #print('DEBUG adding host on {0} to adm'.format(iface))
        iface.endpoint = self.default_iface
        self.adm_endpoints.append(iface)

    def node_list(self):
        #print('DEBUG  self.adm_endpoints', [x.ip for x in self.adm_endpoints])
        return [(x.parent.name, x.ip) for x in self.adm_endpoints]

    def ns_hosts(self, ns=None):
        if ns is None:
            ns = self.name
        if self.pool is not None:
            self.copy_data('/etc/netns/{0}/hosts'.format(ns),
                    self.pool.adm_etchosts(),
                    ns=ns)

    def init_adm_gateway(self, real_ifname, pool):
        ip = next(pool)
        self.register_veth('adm', real_ifname, 'adm0', ip, is_adm=True)
        self.default_iface = self.veth('adm', real_ifname, 'adm0', ip, is_adm=True)

    def init_expose_p2p_link(self, pool):
        pool_iter = iter(pool.ips())
        ip1 = next(pool_iter)
        ip2 = next(pool_iter)
        bcast_addr = pool.bcast()
        self.exec_('ip link add gw0 type veth peer name gwadm0')
        self.exec_('ip link set dev gwadm0 netns {}'.format(self.name))
        self.exec_('ip addr add {} broadcast {} dev gw0'.format(ip1, bcast_addr))
        self.exec_('ip addr add {} broadcast {} dev gwadm0'.format(ip2, bcast_addr), ns=self.name)
        self.exec_('ip link set dev gw0 up')
        self.exec_('ip link set dev gwadm0 up', ns=self.name)


class Host(BaseHost):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._setup_real_host()
        self.install_helpers()
        self.init_container()
        self.setup_pipe()

    def init_container(self):
        # setup default NS
        self.netns(self.name)
        if not self.args.docker:
            # default cgroup
            try:
                self.init_cgroup(self.name, 'cpu,cpuset')
            except StopIteration:
                self.emergency_close()
                raise RuntimeError('Tried to allocate core for host {0} but no cores available.'.format(self.name))
            # enable IP forwarding in NS
            self.sysctl('net.ipv4.ip_forward', 1, ns=self.name)
            # enable ssh
            self._service('ns-sshd {0}'.format(self.name),
                    cgroup=self.cgroup.name,
                    uts_ns=True,
                    ns=self.name)
        else:
            # Docker mode: create container with docker but use our netns
            self.init_docker()

    def init_docker(self):
        sshd_cmd = '/usr/sbin/sshd -u0 -o UseDNS=no -o MaxSessions=1023 -o MaxStartups=1023'
        image = self.args.docker_image
        cpu_exclusive = ''
        if self.args.cpu_exclusive:
            try:
                _, unused_core = self.real_host.get_unused_core()
            except StopIteration:
                self.emergency_close()
                raise RuntimeError('Tried to allocate core for host {0} but no cores available.'.format(self.name))
            cpu_exclusive = '--cpuset-cpus {0}'.format(unused_core)
        bind_mounts = ' '.join(['--volume {0}'.format(x) for x in [
            '/etc/netns:/etc/netns',
            '/var/run/netns:/var/run/netns',
            '/var/run/sherlockfog:/var/run/sherlockfog',
            '/run/sshd:/run/sshd',
            '/root/.ssh:/root/.ssh',
        ] + self.__build_docker_storage_bind()])
        if docker_info and docker_info.get('ServerVersion') >= '25':
            docker_run_opts = '--runtime=nsmux --network=none -e NSMUX_NSPATH=/run/netns/{0} {1}'.format(self.name, image)
            sshd_cmd = '/usr/sbin/sshd -D -u0 -o UseDNS=no -o MaxSessions=1023 -o MaxStartups=1023'
            # manually mount hosts file mapped from vhost netns since commands are not executed through ip netns exec
            bind_mounts += ' --volume /etc/netns/{}/hosts:/etc/hosts:ro'.format(self.name)
        else:
            docker_run_opts = '--network=host --entrypoint "/sbin/ip" {1} netns exec {0}'.format(self.name, image)
        self.exec_('''docker run -d --hostname {0} --name {0} \
            {1} \
            --privileged \
            {2} \
            {3} /usr/local/bin/dumb-init -- {4}'''.format(
                self.name, bind_mounts, cpu_exclusive, docker_run_opts, sshd_cmd))
        self.schedule_cleanup_command('docker container rm {0}'.format(self.name))
        self.schedule_cleanup_command('docker stop {0}'.format(self.name))

    def __build_docker_storage_bind(self):
        binds = []
        # self.args.docker_storage_bind is now a list
        for bind in (self.args.docker_storage_bind or []):
            tok = bind.split(':')
            if len(tok) < 2:
                tok.append('/var/lib/sherlockfog')
            binds.append(':'.join(tok).format_map({'host': self.name}))
        return binds

    def _setup_real_host(self):
        # FIXME since RealHostPool is a singleton, *args and **kwargs are only relevant the first time this code is called
        self.real_host = RealHostPool.get_real_host(self.ip, self, args=self.args)
        # get default interface (ie. self.ip interface)
        self.real_default_iface = self.lookup_iface_by_addr(self.ip)

def _runxterm():
    os.system('/usr/bin/xterm')

def build_args(str_args):
    argv = str_args.split()
    d = {}
    for k, v in (x.split('=') for x in argv):
        d[k.strip()] = v.strip()
    return d

class char_range(object):
    def __init__(self, n0, n1, n2=None):
        self.start = ord(n0)
        self.end = ord(n1)
        self.step = n2
        if n2 is None:
            self.step = 1
        else:
            self.step = int(self.step)
    def __iter__(self):
        for c in range(self.start, self.end+1, self.step): # FIXME not really consistant, should be self.end (but then [A..Z) would spec [A..Y])
            yield(chr(c))

def build_range(str_range):
    m = re.match(r'^(\w+)\.\.(\w+)(\.\.(\d+)|)$', str_range)
    r = range
    if m is None:
        m = re.match(r'^\[(.*?)\]$', str_range)
        if m is not None:
            return eval(str_range, {}, {})
        raise SyntaxError('Invalid range: {0}'.format(str_range))
    try:
        start = int(m.group(1))
    except ValueError:
        start = m.group(1)
        r = char_range
    try:
        end = int(m.group(2))
    except ValueError:
        end = m.group(2)
        assert r is char_range
    if len(m.group(3)) == 0:
        return r(start, end)
    else:
        step = int(m.group(4))
        return r(start, end, step)

def build_link_list(*args):
    ll = []
    for a in args:
        ll.append(tuple([a.strip() for a in a.split(',')]))
    return ll

def eval_local(keyvalue_list):
    try:
        keyvalue_list[1] = InlineExpressionEvaluator.safe_eval(keyvalue_list[1])
    except NameError:
        pass
    return keyvalue_list

def parse_locals(args):
    return {k: v for k, v in [eval_local(x[0].split('=')) for x in args]} if args is not None else {}

def deprecation_warning(fn, *args, **kwargs):
    def wrapper():
        logger.warning("{0}: command is deprecated".format(fn.__name__))
        return fn(*args, **kwargs)
    return wrapper

def schedule_maybe_parallel_task(fn, *args,
        id=None,
        done_callback=None,
        register_callback=None,
        executor=None,
        **kwargs):
    if executor is None:
        res = fn(id, *args, **kwargs)
        if done_callback is not None:
            done_callback(res)
    else:
        future = executor.submit(fn, id, *args, **kwargs)
        if done_callback is not None:
            future.add_done_callback(done_callback)
        if register_callback is not None:
            register_callback(id, future)

class ExecutionEnvironment(object):
    token_regexps = {
        'id':             r'[A-Za-z_][0-9A-Za-z_-]*',
        'fname':          r'[^ ]+',
        'decimal':        r'(-|)(\d+)(.|)(\d+)',
        'positive_dec':   r'((\d+)(.\d+|))',
        'positive_int':   r'(0)|([1-9][0-9]*)',
        'keyword':        r'\w+',
        'value':          r'[0-9A-Za-z_.-]+',
        'ipv4':           r'\.'.join(['(25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9][0-9]|[0-9])']*4),
        'whitespace':     r'[ \t]*',
        'non_whitespace': r'[^ \t]*',
        'link_list':      r'\[(.*?)\]',
    }

    def __init__(self, topo, hp, locals={}, args=None, executor=None):
        # Init command map
        # - command name in the first line of __doc__
        # - _is_cmd attribute defines whether the method is a language command or not
        self._valid_cmds = {}
        for method, code in inspect.getmembers(self, predicate=inspect.ismethod):
            if hasattr(code, '_is_cmd'):
                self._valid_cmds.update({code._cmd_name: code})

        self.topo = topo
        self.hp = hp

        self.bound_queue = []
        self.bound_setup = None
        self.inside_for = False
        self.nest_level = 1

        self.locals = locals
        self.args = args

        self.parser_input = None

        self.executor = executor

    def parser_init(self, s):
        self.parser_input = s
        self.parser_current = self.parser_input

    def parser_remainder(self):
        return self.parser_current

    def parser_update_remainder(self, s):
        self.parser_current = s

    def parser_get_token_type(self):
        return self.parser_token_type

    def parser_func(fn, *args, **kwargs):
        fn._is_cmd = True
        fn._cmd_name = fn.__doc__.splitlines()[0]
        @wraps(fn)
        def _f(self, *args, **kwargs):
            self.parser_init(*args)
            try:
                ret = fn(self, *args, **kwargs)
            except SyntaxError as ex:
                raise SyntaxError("Invalid syntax while parsing {0} command: {1}".format(
                    fn._cmd_name,
                    str(ex)))
            except AssertionError:
                raise SyntaxError("Invalid argument while parsing {0} command: '{1}' found, {2} token expected.".format(
                    fn._cmd_name,
                    self.parser_remainder(),
                    self.parser_get_token_type()))
            return ret
        return _f

    def match_regexp(self, regexp, lookahead=False):
        spacing = self.token_regexps['whitespace']
        sep = r'([ \t]+?|$)'
        trail = '.*'
        match = re.match('^{0}({1}){3}({2})$'.format(
                    spacing,
                    regexp,
                    trail,
                    sep),
                self.parser_current)
        if match is None:
            return None
        if not lookahead:
            self.parser_update_remainder(match.group(len(match.groups())))
        return match.groups()

    def match_token(self, type, **kwargs):
        ret = self.match_regexp(self.token_regexps[type], **kwargs)
        self.parser_token_type = type
        assert ret is not None
        assert len(ret) >= 2
        assert ret[0] is not None
        return ret[0]

    def match_keyword(self, keyword, **kwargs):
        ret = self.match_regexp(keyword, **kwargs)
        self.parser_token_type = type
        assert ret is not None
        assert len(ret) >= 2
        assert ret[0] == keyword
        return ret[0]

    def match_option(self, option, type, **kwargs):
        ret = self.match_regexp('{0}=({1})'.format(option,
            self.token_regexps[type]), **kwargs)
        self.parser_token_type = type
        assert ret is not None
        assert len(ret) > 3
        return ret[2]

    @staticmethod
    def is_match(matchfn, *args, **kwargs):
        try:
            matchfn(*args, lookahead=True, **kwargs)
        except AssertionError:
            logger.debug("is_match returns false")
            return False
        return True

    def is_whitespace(self, s):
        return re.match('^{0}$'.format(self.token_regexps['whitespace']), s) is not None

    def match_name_args(self, cmd):
        self.parser_init(cmd)
        next_token = self.match_token('id')
        return (self._valid_cmds[next_token], self.parser_remainder())

    @parser_func
    def cmd_include(self, args_str, **kwargs):
        """include"""
        next_token = self.match_token('fname')
        with open(next_token, 'r') as f:
            for incl_line in f:
                #print(incl_line, file=sys.stderr)
                self.exec_(incl_line, **kwargs)
        return True

    @parser_func
    def cmd_def(self, args_str, **kwargs):
        """def"""
        id = self.match_token('id')
        ip = None
        if self.is_match(self.match_token, 'value'):
            ip = self.match_token('ipv4')
        else:
            ip = self.get_hp_next_host()
        schedule_maybe_parallel_task(Host, ip,
                id=id,
                done_callback=self.hp.add_host,
                register_callback=self.hp.register_host,
                executor=self.hp.get_executor(),
                args=self.args)
        return True

    @parser_func
    def cmd_let(self, args_str, **kwargs):
        """let"""
        id = self.match_token('id')
        value = self.parser_remainder()
        try:
            # Pass value literal to Python's eval to enable typed expressions
            # i.e. let n 2 => { "n": 2 } but let name test => { "name": "test" }
            # Disable all builtins to allow expressions such as let s sum => { "s": "sum" }
            self.locals[id] = InlineExpressionEvaluator.safe_eval(value, no_builtins=True)
        except (NameError, SyntaxError):
            self.locals[id] = value
        return True

    @deprecation_warning
    @parser_func
    def cmd_netns(self, args_str, **kwargs):
        """netns"""
        host = self.match_token('id')
        netns = self.match_token('id')
        self.hp.find_host(host).netns(netns)
        return True

    @parser_func
    def cmd_connect(self, args_str, **kwargs):
        """connect"""
        h1 = self.match_token('id')
        h2 = self.match_token('id')
        args = [h1, h2]
        rest = self.parser_remainder()
        if len(rest) > 0:
            args.append(rest)
        self.hp.connect(*args)
        return True

    @parser_func
    def cmd_set_delay(self, args_str, **kwargs):
        """set-delay"""
        d = {}
        if self.is_match(self.match_option, 'at', 'positive_dec'):
            d['at'] = self.match_option('at', 'positive_dec')
        if self.is_match(self.match_token, 'link_list'):
            ll = self.match_token('link_list')
            link_list = build_link_list(*ll.split())
            rest = self.parser_remainder()
            for h in link_list:
                self.hp.set_delay(h[0], h[1], *rest.split(), **d)
            return True
        if self.is_match(self.match_keyword, 'all'):
            kw = self.match_keyword('all')
            rest = self.parser_remainder()
            for h1, h2 in self.hp.link_iter():
                self.hp.set_delay(h1, h2, *rest.split(), **d)
            return True
        h1 = self.match_token('id')
        h2 = self.match_token('id')
        rest = self.parser_remainder().split()
        if len(rest) == 0:
            raise SyntaxError("Missing tc argument")
        self.hp.set_delay(h1, h2, *rest, **d)
        return True

    @parser_func
    def cmd_set_bandwidth(self, args_str, **kwargs):
        """set-bandwidth"""
        d = {}
        if self.is_match(self.match_option, 'at', 'positive_dec'):
            d['at'] = self.match_option('at', 'positive_dec')
        if self.is_match(self.match_token, 'link_list'):
            ll = self.match_token('link_list')
            link_list = build_link_list(*ll.split())
            for h in link_list:
                self.hp.set_bandwidth(h[0], h[1], *self.parser_remainder().split(), **d)
            return True
        if self.is_match(self.match_keyword, 'all'):
            kw = self.match_keyword('all')
            rest = self.parser_remainder()
            for h1, h2 in self.hp.link_iter():
                self.hp.set_bandwidth(h1, h2, *rest.split(), **d)
            return True
        h1 = self.match_token('id')
        h2 = self.match_token('id')
        rest = self.parser_remainder().split()
        if len(rest) == 0:
            raise SyntaxError("Missing tc argument")
        self.hp.set_bandwidth(h1, h2, *rest, **d)
        return True

    @parser_func
    def cmd_cgroup_set_cpu_shares(self, args_str, **kwargs):
        """cgroup-set-cpu-shares"""
        host = self.match_token('id')
        shares = self.match_token('positive_int')
        self.hp.find_host(host).cgroup_get().set_cpu_shares(int(shares))
        return True

    @parser_func
    def cmd_cgroup_set_cfs_period(self, args_str, **kwargs):
        """cgroup-set-cfs-period"""
        host = self.match_token('id')
        period = self.match_token('positive_int')
        self.hp.find_host(host).cgroup_get().set_cfs_period(int(period))
        return True

    @parser_func
    def cmd_cgroup_set_cfs_quota(self, args_str, **kwargs):
        """cgroup-set-cfs-quota"""
        host = self.match_token('id')
        quota = self.match_token('positive_int')
        self.hp.find_host(host).cgroup_get().set_cfs_quota(int(quota))
        return True

    @deprecation_warning
    @parser_func
    def cmd_tcraw(self, args_str, **kwargs):
        """tcraw"""
        host = self.match_token('id')
        self.hp.find_host(host).tcraw(self.parser_remainder())
        return True

    @deprecation_warning
    @parser_func
    def cmd_set_link(self, args_str, **kwargs):
        """set-link"""
        host = self.match_token('id')
        kw = self.match_keyword('dev')
        dev = self.match_token('id')
        key = self.match_token('id')
        self.hp.find_host(host).set_link(dev, key, self.parser_remainder())
        return True

    @parser_func
    def cmd_set_node_property(self, args_str, **kwargs):
        """set-node-property"""
        host = self.match_token('id')
        key = self.match_token('id')
        value = self.match_token('value')
        self.hp.find_host(host).set_property(key, value)
        return True

    @parser_func
    def cmd_ping(self, args_str, **kwargs):
        """ping"""
        if self.is_match(self.match_keyword, 'all'):
            self.hp.ping_all()
        else:
            h1 = self.match_token('id')
            h2 = self.match_token('id')
            self.hp.ping(h1, h2)
        return True

    @parser_func
    def cmd_xterm(self, args_str, **kwargs):
        """xterm"""
        _runxterm()
        return True

    @parser_func
    def cmd_shell(self, args_str, **kwargs):
        """shell"""
        host = self.match_token('id')
        logger.info('launching shell...')
        rest = self.parser_remainder().strip()
        if len(rest) > 0:
            self.hp.find_host(host).shell(**build_args(rest))
        else:
            self.hp.shell()
        return True

    @parser_func
    def cmd_shelladm(self, args_str, **kwargs):
        """shelladm"""
        if self.hp.args.use_adm_ns:
            logger.info('launching adm shell...')
            self.hp.adm_host.shell(ns='adm')
        else:
            logger.warning('adm disabled, skipping command: shelladm')
        return True

    @parser_func
    def cmd_run(self, args_str, **kwargs):
        """run"""
        d = {}
        docker = self.args.docker
        if docker:
            d['docker'] = True
        host = self.match_token('id')
        if self.is_match(self.match_keyword, 'netns'):
            kw = self.match_keyword('netns')
            d['ns'] = self.match_token('id')
            if docker:
                logger.warning('Ignoring netns option in run command since Docker mode is enabled')
        if self.is_match(self.match_option, 'at', 'positive_dec'):
            d['at'] = self.match_option('at', 'positive_dec')
        try:
            logger.info('Run{0}: {1}'.format(
                '[{0}]'.format(d['ns']) if 'ns' in d else '',
                self.parser_remainder()))
            self.hp.find_host(host).exec_(self.parser_remainder(), **d)
        except IOError as e:
            logger.warning('Ignoring: {0}'.format(e))
        return True

    @parser_func
    def cmd_runas(self, args_str, **kwargs):
        """runas"""
        d = {}
        docker = self.args.docker
        if docker:
            d['docker'] = True
        host = self.match_token('id')
        if self.is_match(self.match_keyword, 'netns'):
            kw = self.match_keyword('netns')
            d['ns'] = self.match_token('id')
            if docker:
                logger.warning('Ignoring netns option in runas command since Docker mode is enabled')
        if self.is_match(self.match_option, 'at', 'positive_dec'):
            d['at'] = self.match_option('at', 'positive_dec')
        d['username'] = self.match_token('id')
        try:
            logger.info('Run{0}: {1}'.format(
                '[{0}/{1}]'.format(d['username'], d['ns']) if 'ns' in d else '[{0}]'.format(d['username']),
                self.parser_remainder()))
            self.hp.find_host(host).exec_(self.parser_remainder(), **d)
        except IOError as e:
            logger.warning('Ignoring: {0}'.format(e))
        return True

    @parser_func
    def cmd_runadm(self, args_str, **kwargs):
        """runadm"""
        if self.hp.args.use_adm_ns:
            try:
                logger.info('Run[adm]: {0}'.format(self.parser_remainder()))
                self.hp.adm_host.exec_(self.parser_remainder(), ns=self.hp.adm_host.name)
            except IOError as e:
                logger.warning('Ignoring: {0}'.format(e))
        else:
            logger.warning('adm disabled, skipping command: runadm {0}'.format(args_str))
        return True

    @parser_func
    def cmd_sysctl(self, args_str, **kwargs):
        """sysctl"""
        host = self.match_token('id')
        key = self.match_token('non_whitespace')
        value = self.match_token('id')
        self.hp.find_host(host).sysctl(key, value)
        return True

    @parser_func
    def cmd_service(self, args_str, **kwargs):
        """service"""
        host = self.match_token('id')
        kw = self.match_keyword('netns')
        netns = self.match_token('id')
        self.hp.find_host(host).exec_(self.parser_remainder(), ns=netns, service=True)
        return True

    @parser_func
    def cmd_build_network(self, args_str, **kwargs):
        """build-network"""
        self.hp.build_network()
        return True

    @parser_func
    def cmd_waitall(self, args_str, **kwargs):
        """waitall"""
        self.hp.waitall()
        return True

    @parser_func
    def cmd_savegraph(self, args_str, **kwargs):
        """savegraph"""
        self.topo.save(args_str)
        return True

    def get_hp_next_host(self):
        next_host = None
        try:
            next_host = self.hp['nextRealHost']
        except IndexError:
            raise RuntimeError('Requested host from real host list but it was empty.')
        return next_host

    def exec_(self, line, vars=None):
        # ignore comments or empty lines
        if re.match('[\t ]*#.*$', line) is not None:
            return False
        if re.match('^[\t ]*$', line) is not None:
            return False

        cmd = line.rstrip(os.linesep)

        #print("debug: {0}".format(cmd))
        # sanity check
        cmd_end = re.match('[\t]*end for[\s]*$', cmd)
        assert(cmd_end is None or self.inside_for)

        # resolve for
        if self.inside_for:
            cmd_end = re.match('[\t ]*end for[\s]*$', cmd)
            if cmd_end is not None and self.nest_level == 1:
                bound_var, range_expr = self.bound_setup
                if vars is None:
                    vars = {}
                for n in build_range(range_expr):
                    vars.update({bound_var:n})
                    e = ExecutionEnvironment(self.topo, self.hp, locals=self.locals.copy(), args=self.args, executor=self.executor)
                    for bound_cmd in self.bound_queue:
                        e.exec_(bound_cmd, vars=vars)
                self.bound_queue = []
                self.bound_setup = None
                self.inside_for = False
            elif cmd_end is not None:
                self.nest_level -= 1
                self.bound_queue.append(line)
                #print("self.nest_level: {0}".format(self.nest_level))
            else:
                #print("queue: {0}".format(cmd), file=sys.stderr)
                cmd_for = re.match('^[\t ]*for (.*?) in (.*?) do$', cmd)
                if cmd_for is not None:
                    self.nest_level += 1
                    #print("self.nest_level: {0}".format(self.nest_level))
                self.bound_queue.append(line)
            return True

        # match commands without substitutions
        cmd_for = re.match('^[\t ]*for (.*?) in (.*?) do$', cmd)
        if cmd_for is not None:
            #print("multi-line for")
            bound_var = cmd_for.group(1)
            # range could depend on previously bound variables or experiment data
            range_expr = cmd_for.group(2).format_map(HostPoolSubstitutionDict(self.hp, locals=self.locals, extra=vars))
            self.bound_setup = (bound_var, range_expr)
            #print("bound_setup: {0}".format(self.bound_setup))
            self.inside_for = True
            return True
        cmd_for = re.match('^[\t ]*for (.*?) in (.*?) do (.*)$', cmd)
        if cmd_for is not None:
            #print("one-liner for")
            bound_var = cmd_for.group(1)
            # range could depend on previously bound variables or experiment data
            range_expr = cmd_for.group(2).format_map(HostPoolSubstitutionDict(self.hp, locals=self.locals, extra=vars))
            bound_cmd = cmd_for.group(3)
            for n in build_range(range_expr):
                if vars is None:
                    vars = {}
                vars.update({bound_var:n})
                self.exec_(bound_cmd, vars=vars)
            return True

        # Replace inline Python expressions, merging locals and vars if applicable
        cmd = InlineExpressionEvaluator(cmd, locals={**self.locals, **vars} if vars is not None else self.locals).get_line()

        # replace placeholders using hostpool info and scoped vars
        cmd = cmd.format_map(HostPoolSubstitutionDict(self.hp, locals=self.locals, extra=vars))

        # match command
        fn, args = self.match_name_args(cmd)
        return fn(args, vars=vars)

class InterruptHandler(object):
    def __init__(self):
        self.sig = signal.SIGINT

    def __enter__(self):
        self.orig = signal.getsignal(self.sig)
        signal.signal(self.sig, self.handler)

    def handler(self, num, frame):
        logger.error("Interrupt triggered!")
        raise StopIteration

    def __exit__(self, type, value, trace):
        signal.signal(self.sig, self.orig)

def check_ip_prefix(prefix, prefix_name='base'):
    ret = None
    try:
        ret = ipaddress.ip_interface(prefix).network
    except ValueError:
        logger.error('Invalid {0} IP prefix: {1}'.format(prefix_name, prefix))
        sys.exit(1)
    return ret

def check_docker_configuration(docker_system_info):
    try:
        docker_info = json.loads(docker_system_info)
    except json.decoder.JSONDecodeError as e:
        raise ValueError('Invalid Docker configuration: could not parse Docker system info') from e

    server_version = docker_info.get('ServerVersion')
    runtimes = docker_info.get('Runtimes')

    if server_version is None:
        raise ValueError('Invalid Docker configuration: missing ServerVersion')
    if runtimes is None:
        raise ValueError('Invalid Docker configuration: missing Runtimes')
    if not isinstance(runtimes, dict):
        raise ValueError('Invalid Docker configuration: Runtimes must be a dictionary')

    match = re.match(r'^(\d+)', str(server_version))
    if match is None:
        raise ValueError('Invalid Docker configuration: malformed ServerVersion: {}'.format(server_version))

    major_version = int(match.group(1))
    if major_version >= 25 and 'nsmux' not in runtimes:
        raise ValueError(
            'Invalid Docker configuration: Docker version 25 or above (current: {}) requires nsmux-runc'.format(
                server_version
            )
        )

    return {
        'ServerVersion': server_version,
        'Runtimes': runtimes,
    }

def get_docker_system_info():
    return subprocess.check_output(
        ['docker', 'system', 'info', '-f', 'json'],
        text=True,
    )

def load_real_host_list(pool, real_host_list):
    rhl = None
    to_close = False
    if real_host_list == '-':
        rhl = sys.stdin
    else:
        rhl = open(real_host_list, 'r')
        to_close = True
    for x in rhl:
        x = x.rstrip('\n')
        if len(x) > 0:
            pool.add_real_host(x, x)
    if to_close:
        rhl.close()

if __name__ == '__main__':
    ap = argparse.ArgumentParser(description='Setup Random Topology on Commodity Hardware (SherlockFog)')
    ap.add_argument('topology',
            metavar='TOPO',
            type=str,
            help='Topology script')
    ap.add_argument('--dry-run',
            action=argparse.BooleanOptionalAction,
            help='Dry-run (do not connect, build topology locally)')
    ap.add_argument('--real-host-list',
            type=str,
            action='store',
            nargs='?',
            help='Pool of IPs to assign nodes to (use {nextRealHost})')
    ap.add_argument('-D', '--define',
            action='append',
            nargs='+',
            help='Define key=value in execution context')
    ap.add_argument('--debug',
            action='store_true',
            help='Enable debug mode')
    ap.add_argument('--base-prefix',
            type=str,
            action='store',
            nargs='?',
            help='Base network prefix for namespace IPs (CIDR notation)')
    ap.add_argument('--base-adm-prefix',
            type=str,
            action='store',
            nargs='?',
            help='Base prefix for administrative network (CIDR notation)')
    ap.add_argument('--expose-adm-prefix',
            type=str,
            action='store',
            nargs='?',
            help='Base prefix for P2P link that exposes access to the administrative network (CIDR notation)')
    ap.add_argument('--expose-adm',
            action=argparse.BooleanOptionalAction,
            help='Expose administrative private network (requires --use-adm-ns)')
    ap.add_argument('--use-iface-prefix',
            action=argparse.BooleanOptionalAction,
            help='Use node prefix for virtual interface names (default: %(default)s)')
    ap.add_argument('--node-name-prefix',
            type=str,
            action='store',
            nargs='?',
            help='Define node name prefix (default: %(default)s{num})')
    ap.add_argument('--use-adm-ns',
            action=argparse.BooleanOptionalAction,
            help='Setup administrative private network')
    ap.add_argument('--routing-algo',
            type=str,
            choices=['shortest_path','shortest_path_compressed','tree_subnets','world_topo','world_topo_flat','none'],
            nargs='?',
            help='Set routing algorithm (default: %(default)s)')
    ap.add_argument('--adm-iface-addr',
            type=str,
            action='store',
            nargs='?',
            help="Outgoing address for administrative network (default: IP of default route's interface)")
    ap.add_argument('--cpu-exclusive',
            action=argparse.BooleanOptionalAction,
            help='Setup exclusive access to a single CPU core for each virtual host (default: %(default)s)')
    ap.add_argument('--parallel-vhost-creation',
            action=argparse.BooleanOptionalAction,
            help='Enable parallel vhost creation')
    ap.add_argument('--max-parallel-workers',
            type=int,
            action='store',
            nargs='?',
            help="Set maximum amount of parallel workers to be launched in parallel vhost creation mode")
    ap.add_argument('--geneve-tunnels',
            action=argparse.BooleanOptionalAction,
            help='Use geneve tunnels for communication between real hosts')
    ap.add_argument('--docker',
            action=argparse.BooleanOptionalAction,
            help='Use docker images to run client code')
    ap.add_argument('--docker-image',
            type=str,
            action='store',
            nargs='?',
            help="Docker image to be used in Docker mode.")
    ap.add_argument('--docker-storage-bind',
            type=str,
            action='append',
            help="Real host directory bind to be used for external storage (use {host} for vhost name) in Docker mode. Can be specified multiple times.")
    ap.add_argument('--rest-api',
            action=argparse.BooleanOptionalAction,
            help='Enable REST API adm UI (experimental)')
    ap.add_argument('--rest-api-port',
            type=int,
            action='store',
            default=8888,
            help='REST API adm UI port (default: %(default)d) (experimental)')
    ap.set_defaults(node_name_prefix='n',
            base_prefix='10.67.0.0/16',
            base_adm_prefix='10.68.0.0/16',
            expose_adm_prefix='10.69.0.0/30',
            expose_adm=False,
            use_adm_ns=False,
            use_iface_prefix=False,
            routing_algo='shortest_path_compressed',
            cpu_exclusive=False,
            docker=False,
            docker_image=None,
            docker_storage_bind=['/var/lib/sherlockfog/{host}:/var/lib/sherlockfog'],
            debug=False,
            parallel_vhost_creation=True,
            geneve_tunnels=True,
            max_parallel_workers=5,
            adm_iface_addr=None,
            rest_api=True,
            rest_api_port=8888)
    args = ap.parse_args()
    init_logging(args)

    # Force-limit concurrent connections if parallel mode is not enabled
    if not args.parallel_vhost_creation:
        args.max_parallel_workers = 1

    # Sanity checks
    docker_info = None
    iface_base_network = check_ip_prefix(args.base_prefix, prefix_name='base')
    if args.use_adm_ns:
        iface_base_adm_network = check_ip_prefix(args.base_adm_prefix, prefix_name='administrative')
        if iface_base_network.overlaps(iface_base_adm_network):
            logger.error('Administrative private network enabled but base IP prefixes for vhosts and administrative interfaces overlap')
            sys.exit(1)
        if args.expose_adm:
            expose_adm_network = check_ip_prefix(args.expose_adm_prefix, prefix_name='expose')
            if expose_adm_network.overlaps(iface_base_adm_network):
                logger.error('Expose administrative private network enabled but prefix overlaps with P2P Link to expose it')
                sys.exit(1)
    elif args.expose_adm:
        logger.warning('Expose administrative private network enabled but administrative network is not, ignoring')

    if args.docker and args.docker_image is None:
        logger.error('Docker mode enabled but no image set')
        sys.exit(2)
    if args.docker:
        try:
            docker_system_info = get_docker_system_info()
            docker_info = check_docker_configuration(docker_system_info)
        except (OSError, subprocess.SubprocessError, ValueError) as e:
            logger.error(str(e))
            sys.exit(2)

    # Discover default interface if not given in case we need to create an adm vhost
    if args.adm_iface_addr is None:
        logger.info('Creating virtual host: throwaway')
        h = LocalHost('throwaway', args=args)
        args.adm_iface_addr = h.default_route()
        h.close()
        logger.info("Setting address for adm interface to {0}".format(args.adm_iface_addr))

    locals = parse_locals(args.define)
    topo0 = Topo()
    lan0 = HostPool('lan0',
            base=args.base_prefix,
            use_adm=args.use_adm_ns,
            args=args,
            topo=topo0)

    # Exec commands in topology script
    #
    # We use InterruptHandler to trap SIGINT and TTY's Ctrl+C in order to allow the virtual hosts to
    # properly shutdown if there is a failure
    with InterruptHandler():
        try:
            if args.rest_api:
                lan0.rest_api()

            if args.real_host_list:
                load_real_host_list(lan0, args.real_host_list)

            executor = None
            if args.parallel_vhost_creation:
                executor = concurrent.futures.ThreadPoolExecutor(max_workers=args.max_parallel_workers)
                lan0.set_executor(executor)
            e = ExecutionEnvironment(topo0, lan0, locals=locals, args=args)

            with open(args.topology, 'r') as f:
                for line in f:
                    e.exec_(line)
        except IOError as exc:
            logger.error('err -> {0}'.format(exc))
        finally:
            lan0.close()
