"""No network for recipe compute: a seccomp-bpf filter the compute child installs
on itself before any recipe code runs (refresh.py `_network_guard`).

Recipe `compute.py` never needs the network (its inputs arrive as files the host
fetched), but it runs in the builder container, which can reach the GCP metadata
server and so the builder service account's token. This filter makes every
non-AF_UNIX socket fail with EPERM, whatever the recipe's code does:

- `prctl(PR_SET_NO_NEW_PRIVS)` then `seccomp(SECCOMP_SET_MODE_FILTER, TSYNC)`.
  Neither can be undone by the process, and both are inherited across fork,
  clone and execve, so a subprocess (`os.system`, `subprocess`, a shell) is
  bound too.
- pure stdlib (`ctypes`), x86_64 only: syscall numbers are per architecture,
  so `install()` raises on any other machine instead of loading a wrong table.

Syscall table (numbers from /usr/include/asm/unistd_64.h, x86_64):

    socket             41   allowed only for domain AF_UNIX (1), else EPERM
    socketpair         53   allowed (the kernel supports it for AF_UNIX only)
    ptrace            101   EPERM
    process_vm_readv  310   EPERM
    process_vm_writev 311   EPERM
    io_uring_setup    425   EPERM (io_uring can open sockets without socket(2))
    io_uring_enter    426   EPERM
    io_uring_register 427   EPERM
    nr >= 0x40000000        EPERM (the x32 ABI: same audit arch, other numbers)
    any other arch          KILL_PROCESS (i386 int 0x80 has its own numbering)
    everything else         ALLOW

The refresh inlines this file's source into the compute child's `python -c`
prologue (`child_prologue()`): the child runs with a scrubbed env in a private
workdir and imports nothing from /app. Keep this module stdlib-only, with no
`from __future__` import and no side effect at import time.
"""
import ctypes
import os
import platform
import struct

# Printed (stderr) and used as the exit code by the prologue when install()
# fails, so the host records a platform failure (`sandbox_failed`), not a
# recipe failure.
INSTALL_FAILED_MARKER = "netguard: seccomp filter install failed"
INSTALL_FAILED_EXIT = 86

# <linux/prctl.h>, <linux/seccomp.h>, <linux/audit.h>, <linux/filter.h>
_PR_SET_NO_NEW_PRIVS = 38
_NR_SECCOMP_X86_64 = 317
_SECCOMP_SET_MODE_FILTER = 1
_SECCOMP_FILTER_FLAG_TSYNC = 1
_AUDIT_ARCH_X86_64 = 0xC000003E
_SECCOMP_RET_KILL_PROCESS = 0x80000000
_SECCOMP_RET_ERRNO = 0x00050000
_SECCOMP_RET_ALLOW = 0x7FFF0000
_EPERM = 1
_AF_UNIX = 1
_X32_SYSCALL_BIT = 0x40000000

_BPF_LD_W_ABS = 0x20   # BPF_LD | BPF_W | BPF_ABS
_BPF_JEQ_K = 0x15      # BPF_JMP | BPF_JEQ | BPF_K
_BPF_JGE_K = 0x35      # BPF_JMP | BPF_JGE | BPF_K
_BPF_RET_K = 0x06      # BPF_RET | BPF_K

# struct seccomp_data { int nr; __u32 arch; __u64 instruction_pointer; __u64 args[6]; }
_OFF_NR = 0
_OFF_ARCH = 4
_OFF_ARG0_LO = 16      # little-endian low half of args[0]; socket()'s domain is an int

# x86_64 syscall numbers, /usr/include/asm/unistd_64.h
NR_SOCKET = 41
NR_SOCKETPAIR = 53
NR_PTRACE = 101
NR_PROCESS_VM_READV = 310
NR_PROCESS_VM_WRITEV = 311
NR_IO_URING_SETUP = 425
NR_IO_URING_ENTER = 426
NR_IO_URING_REGISTER = 427
DENIED_SYSCALLS = (
    NR_PTRACE, NR_PROCESS_VM_READV, NR_PROCESS_VM_WRITEV,
    NR_IO_URING_SETUP, NR_IO_URING_ENTER, NR_IO_URING_REGISTER,
)


def _ins(code, k, jt=0, jf=0):
    return struct.pack("=HBBI", code, jt, jf, k)


def build_filter():
    """The BPF program as a list of packed `struct sock_filter` (8 bytes each)."""
    errno_eperm = _SECCOMP_RET_ERRNO | _EPERM
    prog = [
        _ins(_BPF_LD_W_ABS, _OFF_ARCH),
        _ins(_BPF_JEQ_K, _AUDIT_ARCH_X86_64, jt=1),
        _ins(_BPF_RET_K, _SECCOMP_RET_KILL_PROCESS),
        _ins(_BPF_LD_W_ABS, _OFF_NR),
        _ins(_BPF_JGE_K, _X32_SYSCALL_BIT, jf=1),
        _ins(_BPF_RET_K, errno_eperm),
    ]
    # Each denied number: on a match jump past the rest of the list, the
    # socket test and the ALLOW, to the EPERM return.
    n = len(DENIED_SYSCALLS)
    for i, nr in enumerate(DENIED_SYSCALLS):
        prog.append(_ins(_BPF_JEQ_K, nr, jt=(n - 1 - i) + 2))
    # socket(): not a match → ALLOW; a match → skip ALLOW + EPERM to the domain test.
    prog.append(_ins(_BPF_JEQ_K, NR_SOCKET, jt=2))
    prog.append(_ins(_BPF_RET_K, _SECCOMP_RET_ALLOW))
    prog.append(_ins(_BPF_RET_K, errno_eperm))      # the denied-list target
    prog.append(_ins(_BPF_LD_W_ABS, _OFF_ARG0_LO))   # socket(domain, ...)
    prog.append(_ins(_BPF_JEQ_K, _AF_UNIX, jf=1))
    prog.append(_ins(_BPF_RET_K, _SECCOMP_RET_ALLOW))
    prog.append(_ins(_BPF_RET_K, errno_eperm))
    return prog


class _SockFprog(ctypes.Structure):
    _fields_ = [("len", ctypes.c_ushort), ("filter", ctypes.c_void_p)]


def _status_field(name):
    with open("/proc/self/status", encoding="ascii", errors="replace") as f:
        for line in f:
            if line.startswith(name + ":"):
                return line.split(":", 1)[1].strip()
    return None


def install():
    """Deny this process (and everything it spawns) any non-AF_UNIX socket.

    Raises OSError / RuntimeError when the filter can't be installed or a
    self-test after installing finds the network still open. Irreversible:
    never call it in a process that needs the network afterwards.
    """
    machine = platform.machine()
    if os.uname().sysname != "Linux" or machine not in ("x86_64", "AMD64"):
        raise RuntimeError(f"netguard supports Linux x86_64 only, not {os.uname().sysname} {machine}")
    if struct.calcsize("P") != 8:
        raise RuntimeError("netguard needs a 64-bit interpreter")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, ctypes.c_ulong(1), ctypes.c_ulong(0),
                  ctypes.c_ulong(0), ctypes.c_ulong(0)) != 0:
        e = ctypes.get_errno()
        raise OSError(e, f"prctl(PR_SET_NO_NEW_PRIVS): {os.strerror(e)}")
    code = b"".join(build_filter())
    buf = ctypes.create_string_buffer(code, len(code))
    fprog = _SockFprog(len(code) // 8, ctypes.cast(buf, ctypes.c_void_p))
    rc = libc.syscall(ctypes.c_long(_NR_SECCOMP_X86_64), ctypes.c_ulong(_SECCOMP_SET_MODE_FILTER),
                      ctypes.c_ulong(_SECCOMP_FILTER_FLAG_TSYNC), ctypes.byref(fprog))
    if rc != 0:
        e = ctypes.get_errno()
        detail = os.strerror(e) if rc < 0 else f"thread {rc} could not be synchronized"
        raise OSError(e, f"seccomp(SECCOMP_SET_MODE_FILTER): {detail}")
    # Self-test: the kernel says a filter is on, and an AF_INET socket is refused.
    if _status_field("NoNewPrivs") != "1" or _status_field("Seccomp") != "2":
        raise RuntimeError("netguard: /proc/self/status shows no seccomp filter after install")
    import socket
    try:
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).close()
    except PermissionError:
        return
    raise RuntimeError("netguard: an AF_INET socket opened after install")


def child_prologue():
    """Python source for the compute child: this module, then `install()`.

    On failure the child prints INSTALL_FAILED_MARKER to stderr and exits
    INSTALL_FAILED_EXIT before any recipe code is loaded.
    """
    with open(__file__, encoding="utf-8") as f:
        src = f.read()
    return (
        src
        + "\ntry:\n"
        "    install()\n"
        "except BaseException as _netguard_err:\n"
        "    import sys as _netguard_sys\n"
        f"    _netguard_sys.stderr.write({INSTALL_FAILED_MARKER!r} + ': '"
        " + type(_netguard_err).__name__ + ': ' + str(_netguard_err) + '\\n')\n"
        "    _netguard_sys.stderr.flush()\n"
        f"    os._exit({INSTALL_FAILED_EXIT})\n"
    )


def install_failed(error_value, stderr):
    """True when a compute run's error is the prologue's install failure
    (`error_value` is LocalSandbox's `exit code N`)."""
    return error_value == f"exit code {INSTALL_FAILED_EXIT}" and INSTALL_FAILED_MARKER in stderr
