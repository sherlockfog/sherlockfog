Overview
========

SherlockFog is a tool that takes care of automating the deployment of an emulated network topology and running experiments on top of it.
In a nutshell, it *transforms* a script written in a custom language that defines a topology and the description of an experiment into hundreds or thousands of shell commands that achieve this goal.
These commands are executed sequentially over one or several hosts.
Its main focus is the execution and evaluation of MPI applications in non-standard configurations, with an emphasis on Fog/Edge Computing network scenarios, although other types of distributed systems can be emulated as well.

It makes extensive use of the `ip` tool, found on most GNU/Linux installations, to set up virtual Ethernet interfaces inside Linux Network Namespaces.
The virtual interfaces are created by the `veth` subcommand of `ip`, using the [macvlan feature](https://hicu.be/bridge-vs-macvlan) in bridge mode.
Macvlan allows a single real network interface to have different MAC addresses, each connected to a different ``subinterface'' which is managed independently.
The kernel takes care of routing incoming traffic to the correct interface by looking up the destination MAC address of each fragment.
A pair in the virtual network is connected by simply assigning IP addresses in the same P2P network (/30 network prefix) to both endpoints.
All traffic flows through the carrier of the host network interface, which is thus the main bottleneck of the emulated network.
Each interface has not just a different MAC address but also a standalone configuration (e.g. its own name resolution dictionary, firewall, ARP and routing tables).

Containers are reached via SSH servers which are brought up automatically upon creation.
Each server runs on a different [UTS namespace](http://windsock.io/uts-namespace/), whose hostname matches that of the virtual host.
This feature is used to isolate the applications inside the emulated network, as some MPI implementations check the hostname to define whether shared memory or a network transport should be used for communication.
To the best of our knowledge, no other network experimentation tool takes this into account.

Virtual nodes are further isolated by using Linux cgroups, a feature that is used on other similar platforms, such as Mininet-HiFi, to improve emulation fidelity.
It is possible to use this feature to assign CPU cores for exclusive access so that the client code that is executed in a virtual node is not migrated by the kernel at runtime.

Name resolution is handled by generating appropriate `/etc/hosts` files for each namespace automatically.
These files are bound by the `ip netns exec` command.
This feature allows host files to be generated automatically using consistent names, the choice of real hosts notwithstanding.

Finally, using the NetEm traffic control extension via the `tc` tool, link parameters such as latency and bandwidth can be modified on the outbound port of any virtual network interface.
This allows the emulation of distant networks using local connectivity.

Software Requirements
=====================

SherlockFog is implemented in Python version 3 and has dependencies on some additional Python modules and shell commands.
The following Python modules are required:

* `networkx`: graph handling.
* `matplotlib`: graph visualization and plotting.
* `paramiko`: SSH connection handling from Python.

The following shell commands are used by SherlockFog explicitly:

* `ip`: handles virtual network interface creation, address discovery, routing tables, ARP tables, network namespaces.
* `tc`: traffic shaping handling.
* `cgcreate`: handles cgroup creation.
* `cgset`: handles CPU sets and other cgroup parameters.
* `cgdelete`: removes cgroup.
* `cgexec`: command execution inside a *cgroup*.
* `ssh`: used to execute commands on an interactive shell inside a virtual node.
* `sshd`: OpenSSH is instantiated on every virtual node to accept connections.
* `lscpu`: CPU topology discovery.
* `unshare`: UTS namespace creation.

On Ubuntu 18.04, the following command installs all required dependencies:

```
# apt install python3-networkx python3-matplotlib python3-paramiko iproute2 cgroup-tools util-linux openssh-server
```

Installation
============

SherlockFog has been designed to be easy to install and deploy.
Since it is executed only on a single node, the Python dependencies don't have to be installed elsewhere.
The command line tools that have been mentioned in the previous section, however, must be available in worker nodes as well.

Additionally, the coordinator must be allowed to connect to worker nodes via password-less SSH with appropriate privileges (i.e. root access).
It is highly recommended to disable Strict Host Key Checking on the SSH client configuration of worker nodes by adding the following line to each `$ROOT_HOME/.ssh/config` file:

```
StrictHostKeyChecking no
```

Worker nodes don't require being in the same physical network as long as all IP traffic between nodes is forwarded in an unrestricted way.

Command Line Arguments
======================

Calling SherlockFog with the `-h` or `--help` flag produces the following output:

```
usage: sherlockfog [-h] [--dry-run [DRY_RUN]]
                   [--real-host-list [REAL_HOST_LIST]]
                   [-D DEFINE [DEFINE ...]] [--base-prefix [BASE_PREFIX]]
                   [--base-adm-prefix [BASE_ADM_PREFIX]]
                   [--use-iface-prefix [USE_IFACE_PREFIX]]
                   [--node-name-prefix [NODE_NAME_PREFIX]]
                   [--use-adm-ns [USE_ADM_NS]]
                   [--routing-algo [{shortest_path,tree_subnets,world_topo}]]
                   [--adm-iface-addr [ADM_IFACE_ADDR]]
                   [--cpu-exclusive [CPU_EXCLUSIVE]]
                   TOPO

Setup Random Topology on Commodity Hardware (SherlockFog)

positional arguments:
  TOPO                  Topology script

optional arguments:
  -h, --help            show this help message and exit
  --dry-run [DRY_RUN]   Dry-run (do not connect, build topology locally)
  --real-host-list [REAL_HOST_LIST]
                        Pool of IPs to assign nodes to (use {nextRealHost})
  -D DEFINE [DEFINE ...], --define DEFINE [DEFINE ...]
                        Define key=value in execution context
  --base-prefix [BASE_PREFIX]
                        Base network prefix for namespace IPs (CIDR notation)
  --base-adm-prefix [BASE_ADM_PREFIX]
                        Base prefix for administrative network (CIDR notation)
  --use-iface-prefix [USE_IFACE_PREFIX]
                        Use node prefix for virtual interface names (default:
                        False)
  --node-name-prefix [NODE_NAME_PREFIX]
                        Define node name prefix (default: n{num})
  --use-adm-ns [USE_ADM_NS]
                        Setup administrative private network
  --routing-algo [{shortest_path,tree_subnets,world_topo}]
                        Set routing algorithm (default: shortest_path)
  --adm-iface-addr [ADM_IFACE_ADDR]
                        Outgoing address for administrative network (default:
                        IP of default route's interface)
  --cpu-exclusive [CPU_EXCLUSIVE]
                        Setup exclusive access to a single CPU core for each
                        virtual host (default: True)
```

Considerations, caveats and bugs:

* `--real-host-list`: this argument is optional in combination with either `--dry-run` or a topology script that doesn't create virtual nodes.
		The magic variable `{nextRealHost}` is defined in the main execution context as the next host in that list.
		It also accepts `-`, which denotes *standard input*.
		Defining less hosts than the number of requested virtual nodes will result in an error as `{nextRealHost}` will return an empty string.
* `--cpu-exclusive`: SherlockFog reads the topology of the host using the `lscpu` command.
		It processes NUMA nodes and cores, and selects the core to be assigned to a particular virtual host by iterating the cores of each NUMA node in a round-robin fashion.
		If more virtual nodes are instantiated in a given host than the number of cores, setting the assigned core for exclusive access for the second time will result in an error.
* `--routing-algo`: the `world_topo` option relies on the names of the virtual nodes to properly define routing tables.
		Names **must** be defined following this template, where `{n}` is the node number and `{ccTLD}` is the top-level domain for a given country (in uppercase letters):
    * `h{n}`: end nodes. Must be connected to a single virtual node (node degree equals 1), which must be an intermediate switch. The prefix letter `h` may be changed using the `--node-name-prefix` argument.
    * `s{n}`: intermediate switches. Must only be connected to a world backbone switch and an end node (node degree equals 2).
    * `s{n}-{ccTLD}`: world backbone switch for country `{ccTLD}`. Must be connected to every other world backbone switch (node degree equals to the number of countries plus the number of intermediate switches for that country).
Additionally, virtual nodes **must** define a `country` property to be able to properly identify them.
This is achieved by using the `set-node-property` instruction in code before executing `build-network`.

* Using `--routing-algo tree_subnets` on a graph with loops may result in SherlockFog hanging.
* Using `--adm-iface-addr` with an address that corresponds to a different network interface than the default route that is used to connect to the hosts will result in the administrative network not being able to connect to any virtual node.
* Macvlan doesn't work over non-Ethernet interfaces (e.g. InfiniBand or the loopback interface), as it requires a MAC address.
* SherlockFog **does not** support IPv6 (yet).

The Scripting Language
======================

The *fog* scripting language allows the user to define, configure and initialize a virtual topology by executing repeatable experiment scripts.
It also allows client code to be executed on top of the virtual infrastructure.
The only control structure is the `for` command, which can be nested.
The execution environment (class `ExecutionEnvironment`) keeps track of the state variables of the current scope and the topology graph.
There is no conditional execution, which has to be handled using external scripts.

A syntactically correct *fog* program conforms to the following EBNF grammar:

```
	Program       = { line | for | comment | eol };

	line          = spaces, command, eol
	command       = for_cmd | def_cmd | let_cmd | connect_cmd | set_delay_cmd |
	                set_bw_cmd | set_nprop_cmd | shell_cmd | shelladm_cmd |
	                buildnet_cmd | savegraph_cmd | include_cmd |
	                run_cmd, runas_cmd, runadm_cmd;
	comment       = spaces, "#", text, eol;
	for_decl      = "for", space, id, space, "in", range, space, "do";
	for_cmd       = for_decl, space, command;
	for           = for_decl, eol, Program, "end for";
	range         = number, "..", number, [ "..", number ];

	def_cmd       = "def", space, id, [ space, ip_addr ];
	let_cmd       = "let", space, id, space, expr;
	connect_cmd   = "connect", space, id, space, id, [ space, expr ],
	                { space, kwarg };
	set_delay_cmd = "set-delay", space, [ at ], ( link | all ), rate;
	set_bw_cmd    = "set-bandwidth", space, [ at ], ( link | all ), rate;
	set_nprop_cmd = "set-node-property", space, id, space, id, space, value;
	savegraph_cmd = "save-graph", space, value;
	include_cmd   = "include", space, value;
	shell_cmd     = "shell", [ space, id ];
	shelladm_cmd  = "shelladm";
	buildnet_cmd  = "build-network";
	run_cmd       = "run", space, id, space, value;
	runas_cmd     = "runas", space, id, space, id, space, value;
	runadm_cmd    = "runadm", space, value;

	link          = id, space, id;
	ip_addr       = { digit }, ".", { digit }, ".", { digit }, ".", { digit };
	at            = "at=", number, space;
	number        = digit_nonzero, { "0" | digit_nonzero };
	digit_nonzero = "[1-9]";
	kwarg         = id, "=", expr;
	value         = ? all visible characters ? - " ";
	id            = "[A-Za-z_]", { "[0-9A-Za-z_-]" };
	expr          = "[0-9A-Za-z_]", { "[0-9A-Za-z_-]" };
	all           = "all";
	spaces        = "[ \t]+";
	space         = " ";
	eol           = "\n";
```

## Overview

The language has nested block scopes, but each command is only matched within a single line.
The following commands are defined:

* `def vnode`: defines a new virtual node called `vnode`.
This instruction comprises the creation of a container with the same name in one of the hosts of the real host pool and adding it to the topology.
The container includes:
    * A network namespace with a loopback interface.
	* A cgroup (assigning a CPU core for exclusive access if that option is enabled).
	* An UTS namespace.
An SSH server will also be started automatically on the newly created container.

* `let var value`: defines a syntactic replacement for all bounded occurrences of the `{var}` expression to `value` in the current execution context (block). 

* `for var in start..end..step do cmd`: executes `cmd` in a loop, binding `var` to each value specified by the range definition `start..end..step`.
    * Explicit Python-like lists of literals may be used instead of the range definition, e.g. `[3, 6, 7, 'A']`.
	* `cmd` may be replaced by a multi-line command list, which will be bound to its own execution context (inheriting previously defined variables).
In this case, the command list must terminate with an `end for` stanza.
	
* `include file`: reads and executes every line in `file` in the current execution context.
Paths are relative to the current working directory.
	
* `runas vnode user cmd`: executes `cmd` as user `user` in node `vnode`.
The `cmd` argument is piped through bash, thus allowing output redirections and variable substitutions.
	
* `run vnode cmd`: executes `cmd` as user `root` in node `vnode`.

* `set-delay vnode1 vnode2 delay`: sets link delay between nodes `vnode1` and `vnode2` to `delay`.
This commands accept delay definitions using the same notation as `tc` (e.g. `10ms`).

* `set-bandwidth vnode1 vnode2 bandwidth`: sets link bandwidth between nodes `vnode1` and `vnode2` to `bandwidth`.
This commands accept bandwidth definitions using the same notation as `tc` (e.g. `100mbps`).

* `connect vnode1 vnode2 delay`: connects node `vnode1` to node `vnode2`, optionally setting the new link's delay to the `delay` specifier.
This instruction defines new virtual interfaces in `vnode1` and `vnode2`, assigning IP addresses from a newly unassigned P2P subnet to both endpoints.
IP assignment is performed deterministically by taking a P2P subnet from the address pool in sequential order.
Then, the first address of that subnet will be assigned to `vnode1` and the second to `vnode2`.
	
* `build-network`: defines the routing and `ARP` tables in every previously defined virtual node and topology.
The algorithm that is used to generate these rules depends on the value of the `--routing-algo` option.
Failing to execute this command results in the virtual network not being able to route traffic unless a set of rules is defined manually.
It also defines the containers' `/etc/hosts` file to be able to resolve the names of every node in the network.
Note that every container should have the same version of this file, but it must be replicated to be bound to each network namespace.
This operation is performed automatically by this command.
	
* `save-graph filename`: saves the current topology to `filename`.
This command makes use of NetworkX and supports every format that is supported by this module.
Please refer to its [documentation](https://networkx.github.io/documentation/stable/) for more details.
	
* `set-node-property vnode prop value`: defines in `vnode` a node property with name `prop` and value `value`.
These properties might be used by static routing algorithms to implement a non-standard model (e.g. `world_topo`).
	
* `shell vnode`: starts a shell in virtual node `vnode`, or in the coordinator if unspecified.

* `shelladm`: starts a shell in the administrative virtual node.
This command has no effect if the administrative interface has not been initialized.

* `runadm cmd`: executes `cmd` as the `root` user in the administrative virtual node.
This command has no effect if the administrative interface has not been initialized.

## Macro System

Additionally, a macro system is used to query context information, which includes topology objects, scoped variables or "magic" arguments.
Language expressions that enclose identifiers between brackets are replaced by their corresponding value before evaluation.
These identifiers can appear anywhere except as part of the definition of a `for` command.
A few examples follow:

* `run n0 ./cmd {n}` &#8594; replaces `{n}` with scoped variable `n`.
* `run n{i} ./cmd {n0.default_iface.ip}` &#8594; this command requires two substitutions. It is executed on virtual host `n{i}`, which is resolved by replacing `{i}` with its scoped value, then appending it to the string `n`.
		For example, if the value of `i` were `adm`, the resulting name would be `nadm`.
		Finally, the string `{n0.default_iface.ip}` is resolved by taking `n0` as a node object and navigating its attributes (it is evaluated within the Python interpreter).
		In this case, it will output the IP address of the default (firstly created) virtual interface of `n0`.
* "Magic" arguments:
    * `def n0 {nextRealHost}` &#8594; `{nextRealHost}` resolves to the next IP address in the real host list.
	This address is removed from the list after use.
	It is also the default value of the optional IP argument.
    * `run n0 ./cmd {hostList}` &#8594; the `{hostList}` string resolves to a sorted, space-separated list of virtual node names, including every node in the topology (even unreachable nodes).
    * `run n0 {pwd}/myscript.py` &#8594; `{pwd}` resolves to the current working directory of the coordinator (equivalent to running the `pwd` command locally).
			This is useful to find scripts in a directory tree which is shared by all physical nodes.

## Topology Navigation

As mentioned in the previous section, it is possible to navigate topology objects in command substitutions.
This allows, for example, to determine the IP address of an interface or which node (or nodes) and connected directly.
Valid node attributes include:

* `{node.veth0.ip}`: resolves to the IP address of the `veth0` virtual interface of virtual node `node`.
