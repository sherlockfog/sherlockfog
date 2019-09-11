#!/bin/bash

# change UUID when image is updated
UUID="XDTGQx-yjqX-EET8-HUn2-dz2R-iK00-QdbL0X"
imagen="$1"

echo "[Restore partition table]"
sfdisk /dev/sda < part_table

echo "[Create PV]"
mkdir -p /etc/lvm/backup
cp node_lvm_cfg /etc/lvm/backup/srtch-vg
pvcreate -ff --uuid "$UUID" --restorefile /etc/lvm/backup/srtch-vg /dev/sda5
vgcfgrestore srtch-vg
vgchange -ay

echo "[Format swap]"
mkswap /dev/mapper/srtch--vg-swap

echo "[Restore FS]"
fsarchiver restfs $imagen id=0,dest=/dev/mapper/srtch--vg-root

echo "[Install grub]"
mount /dev/mapper/srtch--vg-root /mnt
mount -o bind /dev /mnt/dev
mount -o bind /sys /mnt/sys
mount -o bind /proc /mnt/proc
chroot /mnt grub-install /dev/sda

name="c"
nodenum=$(ip a | grep inet | grep '10\.1\.10' | awk '{print $2}' | awk -F/ '{print $1}' | awk -F. '{print $4}')
if [ $nodenum -gt 160 ]; then
	name="g$(($nodenum - 160))"
else
	name="c$(($nodenum - 100))"
fi
echo "[Set hostname: $name]"
echo "$name" > /mnt/etc/hostname

umount /mnt/dev
umount /mnt/sys
umount /mnt/proc
