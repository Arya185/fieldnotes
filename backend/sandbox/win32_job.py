"""Windows Job Object containment for sandbox subprocesses."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

from backend.sandbox.containment import SandboxPolicy


if ctypes.sizeof(ctypes.c_void_p) == 8:
    ULONG_PTR = ctypes.c_uint64
else:
    ULONG_PTR = ctypes.c_uint32


JOB_OBJECT_LIMIT_WORKINGSET = 0x00000001
JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
JobObjectExtendedLimitInformation = 9
INFINITE = 0xFFFFFFFF
WAIT_OBJECT_0 = 0x00000000
ERROR_INVALID_PARAMETER = 87


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ULONG_PTR),
        ("MaximumWorkingSetSize", ULONG_PTR),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ULONG_PTR),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ULONG_PTR),
        ("JobMemoryLimit", ULONG_PTR),
        ("PeakProcessMemoryUsed", ULONG_PTR),
        ("PeakJobMemoryUsed", ULONG_PTR),
    ]


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
kernel32.CreateJobObjectW.restype = wintypes.HANDLE
kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, wintypes.INT, ctypes.c_void_p, wintypes.DWORD]
kernel32.SetInformationJobObject.restype = wintypes.BOOL
kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
kernel32.TerminateJobObject.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
kernel32.WaitForSingleObject.restype = wintypes.DWORD


class WindowsSandboxLimitExceeded(RuntimeError):
    """Raised when Windows sandbox containment trips."""


@dataclass
class WindowsJobObject:
    policy: SandboxPolicy
    process: object

    def __post_init__(self) -> None:
        self._handle = kernel32.CreateJobObjectW(None, None)
        if not self._handle:
            raise WindowsSandboxLimitExceeded(f"CreateJobObjectW failed: {ctypes.get_last_error()}")
        try:
            self._apply_limits()
            process_handle = wintypes.HANDLE(int(self.process._handle))  # type: ignore[attr-defined]
            if not kernel32.AssignProcessToJobObject(self._handle, process_handle):
                raise WindowsSandboxLimitExceeded(
                    f"AssignProcessToJobObject failed: {ctypes.get_last_error()}"
                )
        except Exception:
            self.close()
            raise

    def __enter__(self) -> "WindowsJobObject":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def terminate(self) -> None:
        if self._handle:
            kernel32.TerminateJobObject(self._handle, 1)

    def close(self) -> None:
        handle = getattr(self, "_handle", None)
        if handle:
            kernel32.CloseHandle(handle)
            self._handle = None

    def _apply_limits(self) -> None:
        self._apply_required_limits()
        self._apply_optional_limit(
            JOB_OBJECT_LIMIT_PROCESS_TIME,
            per_process_user_time_limit=self.policy.timeout_seconds * 10_000_000,
        )
        self._apply_optional_limit(
            JOB_OBJECT_LIMIT_WORKINGSET,
            minimum_working_set_size=0,
            maximum_working_set_size=self.policy.memory_bytes,
        )

    def _apply_required_limits(self) -> None:
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = (
            JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            | JOB_OBJECT_LIMIT_ACTIVE_PROCESS
            | JOB_OBJECT_LIMIT_PROCESS_MEMORY
        )
        limits.BasicLimitInformation.ActiveProcessLimit = self.policy.max_processes
        limits.ProcessMemoryLimit = self.policy.memory_bytes
        self._set_extended_limit_information(limits, ignore_invalid_parameter=False)

    def _apply_optional_limit(
        self,
        limit_flag: int,
        *,
        per_process_user_time_limit: int | None = None,
        minimum_working_set_size: int | None = None,
        maximum_working_set_size: int | None = None,
    ) -> None:
        limits = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
        limits.BasicLimitInformation.LimitFlags = limit_flag
        if per_process_user_time_limit is not None:
            limits.BasicLimitInformation.PerProcessUserTimeLimit = per_process_user_time_limit
        if minimum_working_set_size is not None:
            limits.BasicLimitInformation.MinimumWorkingSetSize = minimum_working_set_size
        if maximum_working_set_size is not None:
            limits.BasicLimitInformation.MaximumWorkingSetSize = maximum_working_set_size
        self._set_extended_limit_information(limits, ignore_invalid_parameter=True)

    def _set_extended_limit_information(
        self,
        limits: JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        *,
        ignore_invalid_parameter: bool,
    ) -> None:
        if kernel32.SetInformationJobObject(
            self._handle,
            JobObjectExtendedLimitInformation,
            ctypes.byref(limits),
            ctypes.sizeof(limits),
        ):
            return
        error_code = ctypes.get_last_error()
        if ignore_invalid_parameter and error_code == ERROR_INVALID_PARAMETER:
            return
        raise WindowsSandboxLimitExceeded(f"SetInformationJobObject failed: {error_code}")
