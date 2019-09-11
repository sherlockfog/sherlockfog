#!/bin/bash

#debug=0

source /usr/share/modules/init/bash

TODO() {
	echo "Error: TODO" && exit 1
}

numeric_sorted_hosts() {
	cat /etc/hosts | awk -F'\t' '{print $2}' | python -c "import re, sys; print ''.join(sorted(sys.stdin.readlines(), key=lambda x: int(re.search('(\d+)', x).group(1))))"
}

hostfile_openmpi() {
	fn="$1"
	rank=0
	echo -n "" > $fn  # truncate
	for h in $(numeric_sorted_hosts); do
		echo "rank $rank=$h slot=$rank" >> $fn
		rank=$(($rank + 1))
	done
}

hostfile_mpich2() {
	fn="$1"
	rank=0
	echo -n "" > $fn  # truncate
	for h in $(numeric_sorted_hosts); do
		echo "$h:1" >> $fn
		rank=$(($rank + 1))
	done
}

hostfile_mvapich() {
	hostfile_mpich2 "$@" # same format
}

##### params
#exp=exp
#cwd=$(basename $(readlink -f $0))
#if [ "$cwd" =~ "\d+" ]; then
#	exp=$cwd
#fi
date="$(date +%Y%m%d%H%M%S)"
#log="$exp-$date.txt"
log="$date.txt"
prefix="$(dirname $0)"

prog="$1"
shift
if [ "$prog" = "--openmpi" ]; then
	#debug_flags="-mca mca_base_verbose 30 -mca btl_base_verbose 30 -mca topo_verbose 1 -mca coll_base_verbose 1 -display-map"
	#flags="-display-map --report-bindings --bind-to core --rankfile $rankfile --mca btl tcp,self -mca btl_tcp_if_include eth0 -mca oob_tcp_if_include eth0 -mca coll_tuned_use_dynamic_rules 1"
	#flags="-display-map --report-bindings --bind-to core --rankfile $rankfile --mca btl tcp,self -mca coll_tuned_use_dynamic_rules 1"
	#if [ $debug -eq 1 ]; then
	#	all_flags="$flags $debug_flags"
	#else
	#	all_flags="$flags"
	#fi

	f="-rf h.txt -mca btl tcp,self -mca coll_tuned_used_dynamic_rules 1"
	module load openmpi
	hostfile_openmpi h.txt
	prog="$1"; shift
elif [ "$prog" = "--mvapich" ]; then
	f="-f h.txt"
	module load mvapich
	hostfile_mvapich h.txt
	prog="$1"; shift
elif [ "$prog" = "--intel" ]; then
	TODO
elif [ "$prog" = "--ibm" ]; then
	TODO
else
	f="-f h.txt"
	module load mpich2
	hostfile_mpich2 h.txt
fi
if [ "$prog" = "--mpich2" ]; then
	prog="$1"; shift
fi
##### end params

cmd="$prefix/$prog $@"

pushd "$prefix" >/dev/null
mpirun $f $cmd 2>&1 | tee -a "$log" 2>/dev/null # | grep MPI_Finalize | tr -d ' ' | cut -d: -f2
popd >/dev/null
