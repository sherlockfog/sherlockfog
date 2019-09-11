def test_installed_in_usr_local(host):
    f = host.file('/usr/local/bin/sherlockfog')
    assert f.exists


def test_runs_without_arguments(host):
    # return code 2 == missing arguments
    host.run_expect([2], 'sherlockfog')
