#!/bin/bash

if [ -z $1 ]; then
	IP=192.168.2.180
else
	IP=$1
fi
pwd=$(pwd) sudo su -c "cd $(pwd) && IP=$IP PYTHONPATH=.. pytest-3"
