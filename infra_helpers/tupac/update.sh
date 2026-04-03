#!/bin/bash

run_in_node()
{
	ssh "root@$1" ${@:2}
}

echo "[Retrieve partition table]"
run_in_node $node sfdisk -d /dev/sda > part_table

# TODO
