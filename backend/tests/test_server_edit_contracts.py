from __future__ import annotations

import socket
from types import SimpleNamespace

import paramiko
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app import ssh_transport
from backend.app.api import servers
from backend.app.api.server_test import test_stored_server as run_stored_test
from backend.app.database import Base
from backend.app.models import Server, User
from backend.app.schemas import ConnectionTestRequest, ServerCreate, ServerUpdate
from backend.app.security import decrypt_text, encrypt_text


@pytest.fixture
def server_db():
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(username='server-test-admin', password_hash='unused', role='admin')
        server = Server(name='stored-server', host='192.0.2.10', username='gpumon', auth_type='key',
                        private_key=encrypt_text('stored-key'), passphrase=encrypt_text('stored-passphrase'))
        db.add_all([admin, server])
        db.commit()
        yield db, admin, server
    engine.dispose()


def test_key_to_password_clears_old_key_and_passphrase(server_db):
    db, admin, server = server_db
    result = servers.update_server(server.id, ServerUpdate(auth_type='password', password='new-password'), db, admin)
    assert result.auth_type == 'password'
    assert decrypt_text(server.password) == 'new-password'
    assert server.private_key == server.passphrase == ''


def test_switching_authentication_requires_new_active_credential(server_db):
    db, admin, server = server_db
    with pytest.raises(HTTPException) as exc:
        servers.update_server(server.id, ServerUpdate(auth_type='password'), db, admin)
    assert exc.value.status_code == 400
    assert server.auth_type == 'key'


def test_same_auth_blank_edit_preserves_credentials(server_db):
    db, admin, server = server_db
    servers.update_server(server.id, ServerUpdate(auth_type='key', private_key='', passphrase=None), db, admin)
    assert decrypt_text(server.private_key) == 'stored-key'
    assert decrypt_text(server.passphrase) == 'stored-passphrase'


def test_replacement_key_does_not_inherit_old_passphrase(server_db):
    db, admin, server = server_db
    servers.update_server(server.id, ServerUpdate(private_key='replacement-key'), db, admin)
    assert decrypt_text(server.private_key) == 'replacement-key'
    assert server.passphrase == ''


def test_metadata_updates_do_not_decrypt_unavailable_credentials(server_db):
    db, admin, server = server_db
    server.private_key = 'corrupted-ciphertext'
    server.passphrase = 'corrupted-passphrase'
    db.commit()
    servers.update_server(server.id, ServerUpdate(enabled=False, note='Stopped until credentials repaired', tags=['repair']), db, admin)
    assert not server.enabled
    assert server.note == 'Stopped until credentials repaired'
    assert server.tags == ['repair']
    assert server.private_key == 'corrupted-ciphertext'
    assert server.passphrase == 'corrupted-passphrase'


@pytest.mark.parametrize('auth_type', ['password', 'key'])
def test_full_frontend_metadata_payload_preserves_unavailable_active_ciphertext(server_db, monkeypatch, auth_type):
    db, admin, server = server_db
    server.auth_type = auth_type
    server.password = 'corrupted-password'
    server.private_key = 'corrupted-key'
    server.passphrase = 'corrupted-passphrase'
    db.commit()
    # Mirror buildServerPayload(form, true): auth_type is always present;
    # blank active fields are omitted, while inactive fields explicitly clear.
    payload = dict(name='metadata-renamed', host=server.host, port=server.port,
                   auth_type=auth_type, enabled=False, server_type='gpu',
                   tags=['repair'], note='Credentials will be repaired separately',
                   bmc_host='', bmc_user='')
    if auth_type == 'password':
        payload.update(private_key='', passphrase='')
    else:
        payload.update(password='')
    monkeypatch.setattr(servers, 'decrypt_text', lambda _: pytest.fail('metadata edit must not decrypt saved credentials'))
    servers.update_server(server.id, ServerUpdate(**payload), db, admin)
    assert server.name == 'metadata-renamed'
    assert not server.enabled
    assert server.tags == ['repair']
    if auth_type == 'password':
        assert server.password == 'corrupted-password'
        assert server.private_key == server.passphrase == ''
    else:
        assert server.private_key == 'corrupted-key'
        assert server.passphrase == 'corrupted-passphrase'
        assert server.password == ''


def test_same_auth_blank_active_fields_preserve_exact_ciphertext(server_db, monkeypatch):
    db, admin, server = server_db
    original = (server.private_key, server.passphrase)
    monkeypatch.setattr(servers, 'decrypt_text', lambda _: pytest.fail('unchanged credentials must not be decrypted or reencrypted'))
    servers.update_server(server.id, ServerUpdate(auth_type='key', private_key='', password=''), db, admin)
    assert (server.private_key, server.passphrase) == original


def test_same_auth_credential_replacement_repairs_corrupt_saved_key(server_db, monkeypatch):
    db, admin, server = server_db
    server.private_key = 'corrupted-key'
    server.passphrase = 'corrupted-passphrase'
    db.commit()
    monkeypatch.setattr(servers, 'decrypt_text', lambda _: pytest.fail('replacement must not depend on old credentials'))
    servers.update_server(server.id, ServerUpdate(auth_type='key', private_key='replacement-key'), db, admin)
    assert decrypt_text(server.private_key) == 'replacement-key'
    assert server.passphrase == ''


def test_same_auth_full_edit_still_rejects_new_root_username(server_db, monkeypatch):
    db, admin, server = server_db
    monkeypatch.setattr(ssh_transport.settings, 'ALLOW_ROOT_SSH', 'no')
    with pytest.raises(HTTPException) as exc:
        servers.update_server(server.id, ServerUpdate(auth_type='key', username='root', password=''), db, admin)
    assert exc.value.status_code == 400
    assert server.username == 'gpumon'


def test_create_discards_inactive_credentials(server_db):
    db, admin, _ = server_db
    result = servers.create_server(ServerCreate(name='password-only', host='192.0.2.11',
        password='active-password', private_key='unused-key', passphrase='unused-passphrase'), db, admin)
    server = db.get(Server, result.id)
    assert server.private_key == server.passphrase == ''
    assert decrypt_text(server.password) == 'active-password'


def test_edit_connection_test_merges_stored_credentials_without_saving(server_db, monkeypatch):
    db, admin, server = server_db
    observed = []
    monkeypatch.setattr(servers, 'test_connection', lambda **kwargs: (observed.append(kwargs) or True, 'ok'))
    response = run_stored_test(server.id, db, admin, ServerUpdate(name='unsaved-name', note='unsaved-note'))
    assert response.ok
    assert observed[0]['username'] == 'gpumon'
    assert observed[0]['private_key'] == 'stored-key'
    assert observed[0]['passphrase'] == 'stored-passphrase'
    assert observed[0]['server_key'] == f'server_{server.id}'
    assert server.name == 'stored-server'
    assert server.note == ''


def test_edit_connection_test_uses_changed_credentials_and_address_without_saving(server_db, monkeypatch):
    db, admin, server = server_db
    observed = []
    monkeypatch.setattr(servers, 'test_connection', lambda **kwargs: (observed.append(kwargs) or True, 'ok'))
    result = run_stored_test(server.id, db, admin, ServerUpdate(host='192.0.2.12', auth_type='password', password='draft-password'))
    assert result.ok
    assert observed[0]['password'] == 'draft-password'
    assert observed[0]['private_key'] == ''
    assert observed[0]['host'] == observed[0]['connect_address'] == '192.0.2.12'
    assert observed[0]['server_key'] == 'target_192.0.2.12_22'
    assert server.host == '192.0.2.10'
    assert server.auth_type == 'key'


@pytest.mark.parametrize('host', ['127.0.0.1', '169.254.169.254', '::1', '224.0.0.1', '0.0.0.0', '::ffff:127.0.0.1', '::ffff:169.254.169.254'])
def test_connection_test_rejects_unsafe_targets(host, monkeypatch):
    monkeypatch.setattr(servers, 'test_connection', lambda **_: pytest.fail('unsafe SSH target reached'))
    result = servers._run_connection_test(ConnectionTestRequest(host=host, username='gpumon'), server_key='test')
    assert not result.ok


def test_connection_test_pins_dns_answer_but_preserves_host_identity(monkeypatch):
    observed = []
    lookups = []
    def resolve(host, port, **kwargs):
        lookups.append(host)
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, '', ('192.0.2.13', port))]
    monkeypatch.setattr(socket, 'getaddrinfo', resolve)
    monkeypatch.setattr(servers, 'test_connection', lambda **kwargs: (observed.append(kwargs) or True, 'ok'))
    result = servers._run_connection_test(ConnectionTestRequest(host='gpu.example', username='gpumon', password='pass'), server_key='server_1')
    assert result.ok
    assert lookups == ['gpu.example']
    assert observed[0]['host'] == 'gpu.example'
    assert observed[0]['connect_address'] == '192.0.2.13'
    assert observed[0]['server_key'] == 'server_1'


def test_connection_test_rejects_root_before_any_network_call(monkeypatch):
    monkeypatch.setattr(ssh_transport.settings, 'ALLOW_ROOT_SSH', 'no')
    monkeypatch.setattr(servers, 'test_connection', lambda **_: pytest.fail('root SSH reached'))
    with pytest.raises(HTTPException) as exc:
        servers._run_connection_test(ConnectionTestRequest(host='192.0.2.10', username='root'), server_key='test')
    assert exc.value.status_code == 400


def test_transport_uses_validated_socket_and_existing_hostkey_pin(tmp_path, monkeypatch):
    observed = {}
    fake_socket = SimpleNamespace(close=lambda: observed.update(socket_closed=True))
    class Client:
        def get_host_keys(self): return paramiko.HostKeys()
        def load_host_keys(self, path): observed['key_path'] = path
        def set_missing_host_key_policy(self, policy): observed['policy'] = policy
        def connect(self, **kwargs): observed['connection'] = kwargs
        def close(self): observed['closed'] = True
    monkeypatch.setattr(ssh_transport.settings, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ssh_transport.paramiko, 'SSHClient', Client)
    monkeypatch.setattr(ssh_transport, '_has_recorded_key', lambda _: True)
    monkeypatch.setattr(ssh_transport.socket, 'create_connection', lambda address, **_: (observed.update(address=address) or fake_socket))
    client = ssh_transport.connect_host('gpu.example', 22, 'gpumon', password='pass', server_key='server_9', connect_address='192.0.2.13')
    assert isinstance(client, Client)
    assert observed['address'] == ('192.0.2.13', 22)
    assert observed['connection']['hostname'] == 'gpu.example'
    assert observed['connection']['sock'] is fake_socket
    assert isinstance(observed['policy'], paramiko.RejectPolicy)
    assert observed['key_path'] == ssh_transport.hostkey_path('server_9')


def test_transport_default_path_keeps_direct_connection(tmp_path, monkeypatch):
    observed = {}
    class Client:
        def set_missing_host_key_policy(self, policy): pass
        def connect(self, **kwargs): observed.update(kwargs)
        def close(self): pass
    monkeypatch.setattr(ssh_transport.settings, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ssh_transport.paramiko, 'SSHClient', Client)
    monkeypatch.setattr(ssh_transport, '_has_recorded_key', lambda _: False)
    monkeypatch.setattr(ssh_transport.socket, 'create_connection', lambda *_args, **_kwargs: pytest.fail('default SSH transport changed'))
    ssh_transport.connect_host('gpu.example', 22, 'gpumon', password='pass')
    assert observed['hostname'] == 'gpu.example'
    assert 'sock' not in observed


def test_transport_pin_failure_closes_socket_and_does_not_downgrade(tmp_path, monkeypatch):
    observed = {}
    fake_socket = SimpleNamespace(close=lambda: observed.update(socket_closed=True))
    trusted = paramiko.RSAKey.generate(1024)
    class Client:
        def get_host_keys(self): return paramiko.HostKeys()
        def load_host_keys(self, path): pass
        def set_missing_host_key_policy(self, policy): observed['policy'] = policy
        def connect(self, **kwargs): raise paramiko.BadHostKeyException('gpu.example', trusted, trusted)
        def close(self): observed['closed'] = True
    monkeypatch.setattr(ssh_transport.settings, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ssh_transport.paramiko, 'SSHClient', Client)
    monkeypatch.setattr(ssh_transport, '_has_recorded_key', lambda _: True)
    monkeypatch.setattr(ssh_transport.socket, 'create_connection', lambda *_args, **_kwargs: fake_socket)
    with pytest.raises(paramiko.BadHostKeyException):
        ssh_transport.connect_host('gpu.example', 22, 'gpumon', password='pass', connect_address='192.0.2.13')
    assert observed['closed'] and observed['socket_closed']
    assert isinstance(observed['policy'], paramiko.RejectPolicy)


@pytest.mark.parametrize('existing_hostname_pin', [False, True])
def test_transport_reuses_exact_legacy_ip_pin_without_overwriting_hostname_pin(tmp_path, monkeypatch, existing_hostname_pin):
    trusted = paramiko.RSAKey.generate(1024)
    hostname_key = paramiko.RSAKey.generate(1024)
    keys = paramiko.HostKeys()
    keys.add('192.0.2.13', 'ssh-rsa', trusted)
    if existing_hostname_pin:
        keys.add('gpu.example', 'ssh-rsa', hostname_key)
    class Client:
        def get_host_keys(self): return keys
        def load_host_keys(self, path): pass
        def set_missing_host_key_policy(self, policy): assert isinstance(policy, paramiko.RejectPolicy)
        def connect(self, **kwargs):
            expected = hostname_key if existing_hostname_pin else trusted
            assert keys.lookup(kwargs['hostname'])['ssh-rsa'] == expected
        def close(self): pass
    monkeypatch.setattr(ssh_transport.settings, 'DATA_DIR', str(tmp_path))
    monkeypatch.setattr(ssh_transport.paramiko, 'SSHClient', Client)
    monkeypatch.setattr(ssh_transport, '_has_recorded_key', lambda _: True)
    monkeypatch.setattr(ssh_transport.socket, 'create_connection', lambda *_args, **_kwargs: SimpleNamespace(close=lambda: None))
    ssh_transport.connect_host('gpu.example', 22, 'gpumon', password='pass', connect_address='192.0.2.13')
