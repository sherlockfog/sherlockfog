import pytest

from sherlockfog import IPUtil

def test_bcast():
    assert IPUtil.bcast_addr('8.8.8.0', 21) == '8.8.15.255'
    assert IPUtil.bcast_addr('10.67.0.2', 24) == '10.67.0.255'
    assert IPUtil.bcast_addr('10.67.0.2', 31) == '10.67.0.3'
    assert IPUtil.bcast_addr('0.0.0.0', 0) == '255.255.255.255'

def test_network_addr():
    assert IPUtil.network_addr('1.1.1.1', 24) == '1.1.1.0'
    assert IPUtil.network_addr('254.0.1.2', 7) == '254.0.0.0'
    assert IPUtil.network_addr('5.129.1.5', 9) == '5.128.0.0'
    assert IPUtil.network_addr('5.129.1.5', 0) == '0.0.0.0'
    assert IPUtil.network_addr('5.129.1.5', 32) == '5.129.1.5'

def test_aton():
    assert IPUtil.inet_aton('1.1.1.1') == 16843009
    assert IPUtil.inet_aton('0.0.0.0') == 0
    assert IPUtil.inet_aton('255.255.255.255') == 4294967295
    assert IPUtil.inet_aton('1.0.0.1') == 16777217

def test_ntoa():
    assert IPUtil.inet_ntoa(16843009) == '1.1.1.1'
    assert IPUtil.inet_ntoa(0) == '0.0.0.0'
    assert IPUtil.inet_ntoa(4294967295) == '255.255.255.255'
    assert IPUtil.inet_ntoa(16777217) == '1.0.0.1'
