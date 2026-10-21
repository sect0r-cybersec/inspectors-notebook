"""Message-mode named pipes between the relay and the companion (NFR-5).

Handles are overlapped so one thread can block reading while another writes;
synchronous pipe handles serialise the two and deadlock.

The pipe's security descriptor names the current user as owner and grants access
to that user only, and remote clients are rejected. Clients check the owner before
sending anything, so a pipe pre-created by another account is refused.
"""

import ctypes
import json
import time
from ctypes import wintypes

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
PIPE_ACCESS_DUPLEX = 0x00000003
FILE_FLAG_FIRST_PIPE_INSTANCE = 0x00080000
FILE_FLAG_OVERLAPPED = 0x40000000
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
PIPE_REJECT_REMOTE_CLIENTS = 0x00000008
PIPE_UNLIMITED_INSTANCES = 255
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
ERROR_ACCESS_DENIED = 5
ERROR_FILE_NOT_FOUND = 2
ERROR_BROKEN_PIPE = 109
ERROR_MORE_DATA = 234
ERROR_PIPE_BUSY = 231
ERROR_PIPE_CONNECTED = 535
ERROR_IO_PENDING = 997
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0
TOKEN_QUERY = 0x0008
TOKEN_USER_CLASS = 1
SE_KERNEL_OBJECT = 6
OWNER_SECURITY_INFORMATION = 0x00000001
SDDL_REVISION_1 = 1

BUFFER_SIZE = 64 * 1024


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("Internal", ctypes.c_size_t),
        ("InternalHigh", ctypes.c_size_t),
        ("Offset", wintypes.DWORD),
        ("OffsetHigh", wintypes.DWORD),
        ("hEvent", wintypes.HANDLE),
    ]


def _sig(fn, restype, *argtypes):
    fn.restype = restype
    fn.argtypes = argtypes
    return fn


CreateNamedPipeW = _sig(
    kernel32.CreateNamedPipeW, wintypes.HANDLE,
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, ctypes.POINTER(SECURITY_ATTRIBUTES),
)  # fmt: skip
ConnectNamedPipe = _sig(kernel32.ConnectNamedPipe, wintypes.BOOL, wintypes.HANDLE, ctypes.POINTER(OVERLAPPED))
DisconnectNamedPipe = _sig(kernel32.DisconnectNamedPipe, wintypes.BOOL, wintypes.HANDLE)
CreateFileW = _sig(
    kernel32.CreateFileW, wintypes.HANDLE,
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
)  # fmt: skip
SetNamedPipeHandleState = _sig(
    kernel32.SetNamedPipeHandleState, wintypes.BOOL,
    wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID, wintypes.LPVOID,
)  # fmt: skip
ReadFile = _sig(
    kernel32.ReadFile, wintypes.BOOL,
    wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
)  # fmt: skip
WriteFile = _sig(
    kernel32.WriteFile, wintypes.BOOL,
    wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID,
)  # fmt: skip
CreateEventW = _sig(
    kernel32.CreateEventW, wintypes.HANDLE, wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR
)
GetOverlappedResult = _sig(
    kernel32.GetOverlappedResult, wintypes.BOOL,
    wintypes.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wintypes.DWORD), wintypes.BOOL,
)  # fmt: skip
WaitForMultipleObjects = _sig(
    kernel32.WaitForMultipleObjects, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE), wintypes.BOOL, wintypes.DWORD
)
SetEvent = _sig(kernel32.SetEvent, wintypes.BOOL, wintypes.HANDLE)
CloseHandle = _sig(kernel32.CloseHandle, wintypes.BOOL, wintypes.HANDLE)
CancelIoEx = _sig(kernel32.CancelIoEx, wintypes.BOOL, wintypes.HANDLE, wintypes.LPVOID)
GetCurrentProcess = _sig(kernel32.GetCurrentProcess, wintypes.HANDLE)
LocalFree = _sig(kernel32.LocalFree, wintypes.HLOCAL, wintypes.HLOCAL)
OpenProcessToken = _sig(
    advapi32.OpenProcessToken, wintypes.BOOL, wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
)
GetTokenInformation = _sig(
    advapi32.GetTokenInformation, wintypes.BOOL,
    wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
)  # fmt: skip
ConvertSidToStringSidW = _sig(
    advapi32.ConvertSidToStringSidW, wintypes.BOOL, wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR)
)
ConvertStringSecurityDescriptorToSecurityDescriptorW = _sig(
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW, wintypes.BOOL,
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.ULONG),
)  # fmt: skip
GetSecurityInfo = _sig(
    advapi32.GetSecurityInfo, wintypes.DWORD,
    wintypes.HANDLE, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID),
    ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID), ctypes.POINTER(wintypes.LPVOID),
)  # fmt: skip
EqualSid = _sig(advapi32.EqualSid, wintypes.BOOL, wintypes.LPVOID, wintypes.LPVOID)


class PipeError(OSError):
    pass


class AlreadyRunning(PipeError):
    """Another process already serves this pipe name."""


class NotOwnedByUser(PipeError):
    """The pipe exists but another account created it."""


def _error(code: int | None = None) -> PipeError:
    code = ctypes.get_last_error() if code is None else code
    return PipeError(code, ctypes.FormatError(code))


def _user_sid() -> ctypes.Array:
    """The current user's SID as a raw buffer."""
    token = wintypes.HANDLE()
    if not OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)):
        raise _error()
    try:
        size = wintypes.DWORD()
        GetTokenInformation(token, TOKEN_USER_CLASS, None, 0, ctypes.byref(size))
        buf = ctypes.create_string_buffer(size.value)
        if not GetTokenInformation(token, TOKEN_USER_CLASS, buf, size, ctypes.byref(size)):
            raise _error()
    finally:
        CloseHandle(token)
    return buf  # TOKEN_USER: the first field is a pointer to the SID inside this buffer


def _sid_pointer(token_user: ctypes.Array) -> int:
    return ctypes.cast(token_user, ctypes.POINTER(ctypes.c_void_p))[0]


def user_sid_string() -> str:
    token_user = _user_sid()
    out = wintypes.LPWSTR()
    if not ConvertSidToStringSidW(_sid_pointer(token_user), ctypes.byref(out)):
        raise _error()
    try:
        return out.value
    finally:
        LocalFree(ctypes.cast(out, wintypes.HLOCAL))


def default_pipe_name() -> str:
    return rf"\\.\pipe\InspectorsNotebook.{user_sid_string()}"


def security_sddl(sid: str) -> str:
    """Owner and sole grantee is the user; P blocks inherited entries."""
    return f"O:{sid}D:P(A;;GA;;;{sid})"


def _wait_io(handle: int, op, buf, size: int) -> tuple[int, int]:
    """Run an overlapped ReadFile or WriteFile to completion. Returns (error code, bytes)."""
    ov = OVERLAPPED(hEvent=CreateEventW(None, True, False, None))
    if not ov.hEvent:
        raise _error()
    try:
        done = wintypes.DWORD()
        # The count the call itself reports is unreliable for overlapped handles; always
        # take it from GetOverlappedResult, including for a partial message (MORE_DATA).
        code = 0 if op(handle, buf, size, None, ctypes.byref(ov)) else ctypes.get_last_error()
        if code not in (0, ERROR_IO_PENDING, ERROR_MORE_DATA):
            return code, 0
        if GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(done), True):
            return 0, done.value
        return ctypes.get_last_error(), done.value
    finally:
        CloseHandle(ov.hEvent)


class Connection:
    """One end of a connected pipe. Each send is one whole message."""

    def __init__(self, handle: int):
        self._handle = handle

    def send(self, message: dict) -> None:
        data = json.dumps(message, separators=(",", ":")).encode("utf-8")
        code, _ = _wait_io(self._handle, WriteFile, data, len(data))
        if code:
            raise _error(code)

    def receive(self) -> dict:
        """Block for the next message. Raises PipeError when the other end goes away."""
        chunks = []
        buf = ctypes.create_string_buffer(BUFFER_SIZE)
        while True:
            code, read = _wait_io(self._handle, ReadFile, buf, BUFFER_SIZE)
            chunks.append(buf.raw[:read])
            if not code:
                return json.loads(b"".join(chunks).decode("utf-8"))
            if code != ERROR_MORE_DATA:
                raise _error(code)

    def close(self) -> None:
        if self._handle:
            CancelIoEx(self._handle, None)  # unblock a receive() on another thread
            CloseHandle(self._handle)
            self._handle = 0


class Server:
    """Accepts clients on a pipe only the current user can open."""

    def __init__(self, name: str):
        self.name = name
        self._sid = user_sid_string()
        self._first = True
        self._closed = False
        self._listening = 0
        self._stop = CreateEventW(None, True, False, None)  # manual reset: stays set once closed

    def _create_instance(self) -> int:
        sd = wintypes.LPVOID()
        if not ConvertStringSecurityDescriptorToSecurityDescriptorW(
            security_sddl(self._sid), SDDL_REVISION_1, ctypes.byref(sd), None
        ):
            raise _error()
        try:
            sa = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), sd, False)
            mode = PIPE_ACCESS_DUPLEX | FILE_FLAG_OVERLAPPED
            if self._first:
                mode |= FILE_FLAG_FIRST_PIPE_INSTANCE
            handle = CreateNamedPipeW(
                self.name, mode,
                PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
                PIPE_UNLIMITED_INSTANCES, BUFFER_SIZE, BUFFER_SIZE, 0, ctypes.byref(sa),
            )  # fmt: skip
        finally:
            LocalFree(sd)
        if handle == INVALID_HANDLE_VALUE:
            code = ctypes.get_last_error()
            if self._first and code == ERROR_ACCESS_DENIED:
                raise AlreadyRunning(code, f"{self.name} is already in use")
            raise _error(code)
        self._first = False
        return handle

    def listen(self) -> None:
        """Create the first instance now, so a second companion finds out straight away."""
        self._listening = self._create_instance()

    def accept(self) -> Connection | None:
        """Block until a client connects. Returns None once the server is closed."""
        if self._closed:
            return None
        handle = self._listening or self._create_instance()
        self._listening = 0
        code = _wait_connect(handle, self._stop)
        if code or self._closed:
            CloseHandle(handle)
            if self._closed:
                return None
            raise _error(code)
        return Connection(handle)

    def close(self) -> None:
        """Stop accepting and wake a blocked accept()."""
        self._closed = True
        SetEvent(self._stop)
        if self._listening:
            CloseHandle(self._listening)
            self._listening = 0


def _wait_connect(handle: int, stop_event: int) -> int:
    """Wait for a client, or for stop_event. Returns 0 when a client connected."""
    ov = OVERLAPPED(hEvent=CreateEventW(None, True, False, None))
    try:
        if ConnectNamedPipe(handle, ctypes.byref(ov)):
            return 0
        code = ctypes.get_last_error()
        if code == ERROR_PIPE_CONNECTED:
            return 0
        if code != ERROR_IO_PENDING:
            return code
        events = (wintypes.HANDLE * 2)(ov.hEvent, stop_event)
        if WaitForMultipleObjects(2, events, False, INFINITE) != WAIT_OBJECT_0:
            CancelIoEx(handle, ctypes.byref(ov))
        done = wintypes.DWORD()
        return 0 if GetOverlappedResult(handle, ctypes.byref(ov), ctypes.byref(done), True) else ctypes.get_last_error()
    finally:
        CloseHandle(ov.hEvent)


def _check_owner(handle: int) -> None:
    owner = wintypes.LPVOID()
    sd = wintypes.LPVOID()
    rc = GetSecurityInfo(
        handle, SE_KERNEL_OBJECT, OWNER_SECURITY_INFORMATION,
        ctypes.byref(owner), None, None, None, ctypes.byref(sd),
    )  # fmt: skip
    if rc:
        raise _error(rc)
    try:
        if not EqualSid(owner, _sid_pointer(_user_sid())):
            raise NotOwnedByUser(ERROR_ACCESS_DENIED, "The pipe belongs to another account")
    finally:
        LocalFree(sd)


def connect(name: str, timeout_ms: int = 0) -> Connection:
    """Open a client connection. Raises PipeError if no server is listening."""
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        handle = CreateFileW(
            name, GENERIC_READ | GENERIC_WRITE, 0, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None
        )
        if handle != INVALID_HANDLE_VALUE:
            break
        code = ctypes.get_last_error()
        if code not in (ERROR_PIPE_BUSY, ERROR_FILE_NOT_FOUND) or time.monotonic() >= deadline:
            raise _error(code)
        time.sleep(0.05)

    try:
        _check_owner(handle)
        mode = wintypes.DWORD(PIPE_READMODE_MESSAGE)
        if not SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
            raise _error()
    except BaseException:
        CloseHandle(handle)
        raise
    return Connection(handle)
