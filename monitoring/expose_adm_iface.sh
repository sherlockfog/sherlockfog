#!/bin/bash

set -e

IP="$1"
if [ -z "$IP" ]; then
	IP=192.168.0.1
fi

GW_IP=$(ipcalc $IP/30 | grep HostMin | cut -d' ' -f4)
if [ "$GW_IP" != "$IP" ]; then
	echo "Invalid gateway IP; must correspond to first host in containing /30 prefix"
	exit 1
fi
TUN_IP=$(ipcalc $IP/30 | grep HostMax | cut -d' ' -f4)
BCAST_IP=$(ipcalc $IP/30 | grep Broadcast | cut -d' ' -f2)

ip 				link add gw0 type veth peer name gwadm0
ip 				link set dev gwadm0 netns adm
ip 				addr add $GW_IP/30 broadcast $BCAST_IP dev gw0
ip -netns adm 	addr add $TUN_IP/30 broadcast $BCAST_IP dev gwadm0
ip 				link set dev gw0 up
ip -netns adm	link set dev gwadm0 up
