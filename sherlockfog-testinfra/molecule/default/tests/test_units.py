def test_units(host):
    ip = host.interface('enp0s3').addresses[0]
    host.run_expect([0], "sudo su -c 'cd /home/vagrant/sherlockfog/test \
            && IP={0} PYTHONPATH=/home/vagrant/sherlockfog/ pytest-3'"
                    .format(ip))
