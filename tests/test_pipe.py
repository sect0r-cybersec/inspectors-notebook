import ctypes
import sys
import threading
import uuid

import pytest

if sys.platform != "win32":
    pytest.skip("Windows only", allow_module_level=True)

from inspectors_notebook import pipe


@pytest.fixture
def name():
    return rf"\\.\pipe\InspectorsNotebook.test.{uuid.uuid4()}"


@pytest.fixture
def server(name):
    s = pipe.Server(name)
    s.listen()
    yield s
    s.close()


def accept_in_background(server):
    result = {}
    t = threading.Thread(target=lambda: result.setdefault("conn", server.accept()), daemon=True)
    t.start()
    return t, result


def test_round_trip_both_ways(server, name):
    t, result = accept_in_background(server)
    client = pipe.connect(name, timeout_ms=2000)
    t.join(2)
    conn = result["conn"]
    client.send({"type": "hello", "browser": "edge"})
    assert conn.receive() == {"type": "hello", "browser": "edge"}
    conn.send({"type": "status", "recording": False})
    assert client.receive() == {"type": "status", "recording": False}
    client.close()
    conn.close()


def test_a_client_that_left_before_the_server_accepted_does_not_stop_it(server, name):
    # A second launch while the app is still starting connects, finds nobody answering, and leaves.
    pipe.connect(name, timeout_ms=2000).close()
    t, result = accept_in_background(server)
    client = pipe.connect(name, timeout_ms=2000)
    t.join(2)
    client.send({"type": "show"})
    assert result["conn"].receive() == {"type": "show"}
    client.close()
    result["conn"].close()


def test_message_larger_than_buffer_arrives_whole(server, name):
    t, result = accept_in_background(server)
    client = pipe.connect(name, timeout_ms=2000)
    t.join(2)
    big = {"type": "event", "text": "x" * (3 * pipe.BUFFER_SIZE + 17)}
    sender = threading.Thread(target=client.send, args=(big,))
    sender.start()
    assert result["conn"].receive() == big
    sender.join(2)


def test_several_clients_at_once(server, name):
    conns = []
    def serve():
        for _ in range(3):
            conns.append(server.accept())
    t = threading.Thread(target=serve, daemon=True)
    t.start()
    clients = [pipe.connect(name, timeout_ms=2000) for _ in range(3)]
    t.join(2)
    for i, c in enumerate(clients):
        c.send({"n": i})
    assert sorted(c.receive()["n"] for c in conns) == [0, 1, 2]


def test_second_server_on_same_name_is_refused(server, name):
    with pytest.raises(pipe.AlreadyRunning):
        pipe.Server(name).listen()


def test_connect_without_server_fails_fast(name):
    with pytest.raises(pipe.PipeError):
        pipe.connect(name)


def test_receive_raises_when_other_end_closes(server, name):
    t, result = accept_in_background(server)
    client = pipe.connect(name, timeout_ms=2000)
    t.join(2)
    client.close()
    with pytest.raises(pipe.PipeError):
        result["conn"].receive()


def test_close_wakes_blocked_accept(name):
    s = pipe.Server(name)
    s.listen()
    t, result = accept_in_background(s)
    s.close()
    t.join(2)
    assert not t.is_alive()
    assert result["conn"] is None


def test_security_descriptor_grants_only_the_user():
    sid = pipe.user_sid_string()
    assert sid.startswith("S-1-5-")
    assert pipe.security_sddl(sid) == f"O:{sid}D:P(A;;GA;;;{sid})"
    assert pipe.default_pipe_name().endswith(sid)


def open_as_anonymous(name):
    """Open the pipe read-only while impersonating Anonymous. Returns the Win32 error, 0 on success."""
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.GetCurrentThread.restype = ctypes.c_void_p
    advapi32.ImpersonateAnonymousToken.argtypes = [ctypes.c_void_p]
    result = []

    def run():
        assert advapi32.ImpersonateAnonymousToken(kernel32.GetCurrentThread())
        try:
            h = pipe.CreateFileW(name, pipe.GENERIC_READ, 0, None, pipe.OPEN_EXISTING, 0, None)
            if h == pipe.INVALID_HANDLE_VALUE:
                result.append(ctypes.get_last_error())
            else:
                pipe.CloseHandle(h)
                result.append(0)
        finally:
            advapi32.RevertToSelf()

    t = threading.Thread(target=run)
    t.start()
    t.join(2)
    return result[0]


def test_other_accounts_are_rejected(server, name):
    """Anonymous stands in for another account; even read-only access is refused.

    A check with a second real Windows account is in tests/manual/S2-relay-checklist.md.
    """
    assert open_as_anonymous(name) == pipe.ERROR_ACCESS_DENIED


def test_control_default_pipe_security_lets_anonymous_read(name):
    """Shows the test above can fail: Windows' default pipe DACL grants Anonymous read."""
    h = pipe.CreateNamedPipeW(
        name, pipe.PIPE_ACCESS_DUPLEX, pipe.PIPE_TYPE_MESSAGE | pipe.PIPE_READMODE_MESSAGE,
        1, 4096, 4096, 0, None,
    )
    assert h != pipe.INVALID_HANDLE_VALUE
    try:
        assert open_as_anonymous(name) == 0
    finally:
        pipe.CloseHandle(h)
