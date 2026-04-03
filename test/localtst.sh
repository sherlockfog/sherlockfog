#!/bin/bash

if [ -z $1 ]; then
	IP=192.168.1.100
else
	IP=$1
	shift
fi
if [ "$1" = "--debug" ]; then
	# DEBUG
	EXTRA_FLAGS="-x --pdb"
fi
pwd=$(pwd) sudo su -c "cd $(pwd) && IP=$IP PYTHONPATH=.. pytest-3 $EXTRA_FLAGS"
