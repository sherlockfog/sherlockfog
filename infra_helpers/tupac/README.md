Scripts para la utilización de un entorno de SherlockFog en TUPAC
=================================================================

* `install.sh`: el script que instala un nodo, toma como parámetro la IP y el nombre de la imagen (tiene un comentario adentro con usage info).
* `node_lvm_cfg`: archivo de configuración de LVM para la imagen.
* `part_table`: dump de la tabla de particiones.
* `remote.sh`: script que se ejecuta remoto que instala el nodo.
* `imagen_debian9.fsa`: imagen de `fsarchiver` con un Debian9 pelado (más deps de Python para correr SherlockFog).
* `imagen_debian_bitcoind.fsa`: imagen con todas las dependencias instaladas para correr `bitcoind` sobre SherlockFog.

Instrucciones para correr desde SystemRescueCD
==============================================

1. Forwardear el puerto local 5120 al 5120 del BMC (ej. para `gnode02`, la interfaz está en `10.1.1.162`, así que hay que hacer `ssh h2 -L5120:10.1.1.162:5120`). Esa es la redirección para el virtual CD.
2. Desde el KVM se puede poner un ISO local y que bootee eso. Bootear SystemRescueCD (o una ISO que venga con fsarchiver). Poner preferentemente que cargue todo el sistema en RAM.
3. Cambiar la pass de root (en SystemRescueCD viene deshabilitada) para poder loguearse por ssh. Acá no me acuerdo si además no hay que permitir logins como root en el sshd.
4. Correr `install.sh` desde el headnode.
