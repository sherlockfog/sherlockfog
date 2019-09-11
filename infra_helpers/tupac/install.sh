#!/bin/bash

# pasos:
# 1. bootear nodo con SystemRescueCD
# 2. cambiar pass de ssh de root
# 3. correr script

dest="$1"
shift

imagen="imagen_debian9.fsa"
if [ -f "$1" ]; then
	imagen="$1"
fi

scp -o StrictHostKeyChecking=no part_table $imagen node_lvm_cfg remote.sh root@$dest:/tmp
ssh -o StrictHostKeyChecking=no root@$dest "cd /tmp && ./remote.sh $imagen" 
