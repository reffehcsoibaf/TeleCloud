"""Binding mínimo do WinFsp via ctypes (estruturas conforme winfsp.h / fsctl.h, WinFsp 2.x)."""
import os
from ctypes import (CFUNCTYPE, POINTER, Structure, WinDLL, byref, c_size_t, c_ubyte, c_uint16,
                    c_uint32, c_uint64, c_void_p, c_wchar, c_wchar_p, cast, sizeof)

STATUS_SUCCESS = 0
STATUS_UNSUCCESSFUL = 0xC0000001
STATUS_NOT_IMPLEMENTED = 0xC0000002
STATUS_OBJECT_NAME_NOT_FOUND = 0xC0000034
STATUS_OBJECT_NAME_COLLISION = 0xC0000035
STATUS_OBJECT_PATH_NOT_FOUND = 0xC000003A
STATUS_FILE_IS_A_DIRECTORY = 0xC00000BA
STATUS_DIRECTORY_NOT_EMPTY = 0xC0000101
STATUS_NOT_A_DIRECTORY = 0xC0000103
STATUS_ACCESS_DENIED = 0xC0000022

FILE_ATTRIBUTE_DIRECTORY = 0x10
FILE_ATTRIBUTE_NORMAL = 0x80
FILE_DIRECTORY_FILE = 0x1
FspCleanupDelete = 0x01


class FileInfo(Structure):
    _fields_ = [
        ("FileAttributes", c_uint32), ("ReparseTag", c_uint32),
        ("AllocationSize", c_uint64), ("FileSize", c_uint64),
        ("CreationTime", c_uint64), ("LastAccessTime", c_uint64),
        ("LastWriteTime", c_uint64), ("ChangeTime", c_uint64),
        ("IndexNumber", c_uint64), ("HardLinks", c_uint32), ("EaSize", c_uint32),
    ]


class VolumeInfo(Structure):
    _fields_ = [("TotalSize", c_uint64), ("FreeSize", c_uint64),
                ("VolumeLabelLength", c_uint16), ("VolumeLabel", c_wchar * 32)]


class DirInfoCab(Structure):
    """Cabeçalho de FSP_FSCTL_DIR_INFO; o nome (UTF-16) vem logo após, no deslocamento 104."""
    _fields_ = [("Size", c_uint16), ("FileInfo", FileInfo), ("Padding", c_ubyte * 24)]


CAB = sizeof(DirInfoCab)  # 104


class VolumeParams(Structure):
    _fields_ = [
        ("Version", c_uint16), ("SectorSize", c_uint16),
        ("SectorsPerAllocationUnit", c_uint16), ("MaxComponentLength", c_uint16),
        ("VolumeCreationTime", c_uint64), ("VolumeSerialNumber", c_uint32),
        ("TransactTimeout", c_uint32), ("IrpTimeout", c_uint32), ("IrpCapacity", c_uint32),
        ("FileInfoTimeout", c_uint32), ("Flags", c_uint32),
        ("Prefix", c_wchar * 192), ("FileSystemName", c_wchar * 16),
        ("Flags1", c_uint32), ("VolumeInfoTimeout", c_uint32), ("DirInfoTimeout", c_uint32),
        ("SecurityTimeout", c_uint32), ("StreamInfoTimeout", c_uint32), ("EaTimeout", c_uint32),
        ("FsextControlCode", c_uint32), ("Reserved32", c_uint32), ("Reserved64", c_uint64 * 2),
    ]


assert sizeof(VolumeParams) == 504, sizeof(VolumeParams)
assert CAB == 104, CAB

# bits de Flags
CasePreservedNames = 1 << 1
UnicodeOnDisk = 1 << 2
PostCleanupWhenModifiedOnly = 1 << 10

P, S, FI = c_void_p, c_wchar_p, POINTER(FileInfo)
U32, U64, B = c_uint32, c_uint64, c_ubyte

# (nome, índice na tabela de 64 entradas, tipo de retorno, argumentos)
OPERACOES = {
    "GetVolumeInfo": (0, U32, (P, POINTER(VolumeInfo))),
    "GetSecurityByName": (2, U32, (P, S, POINTER(U32), P, POINTER(c_size_t))),
    "Create": (3, U32, (P, S, U32, U32, U32, P, U64, POINTER(P), FI)),
    "Open": (4, U32, (P, S, U32, U32, POINTER(P), FI)),
    "Overwrite": (5, U32, (P, P, U32, B, U64, FI)),
    "Cleanup": (6, None, (P, P, S, U32)),
    "Close": (7, None, (P, P)),
    "Read": (8, U32, (P, P, P, U64, U32, POINTER(U32))),
    "Write": (9, U32, (P, P, P, U64, U32, B, B, POINTER(U32), FI)),
    "Flush": (10, U32, (P, P, FI)),
    "GetFileInfo": (11, U32, (P, P, FI)),
    "SetBasicInfo": (12, U32, (P, P, U32, U64, U64, U64, U64, FI)),
    "SetFileSize": (13, U32, (P, P, U64, B, FI)),
    "CanDelete": (14, U32, (P, P, S)),
    "Rename": (15, U32, (P, P, S, S, B)),
    "ReadDirectory": (18, U32, (P, P, S, S, P, U32, POINTER(U32))),
    "SetDelete": (26, U32, (P, P, S, B)),
}


def _carregar():
    base = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    dll = WinDLL(os.path.join(base, "WinFsp", "bin", "winfsp-x64.dll"))
    dll.FspFileSystemCreate.argtypes = [c_wchar_p, POINTER(VolumeParams), c_void_p, POINTER(c_void_p)]
    dll.FspFileSystemCreate.restype = U32
    dll.FspFileSystemSetMountPoint.argtypes = [c_void_p, c_wchar_p]
    dll.FspFileSystemSetMountPoint.restype = U32
    dll.FspFileSystemStartDispatcher.argtypes = [c_void_p, U32]
    dll.FspFileSystemStartDispatcher.restype = U32
    dll.FspFileSystemStopDispatcher.argtypes = [c_void_p]
    dll.FspFileSystemStopDispatcher.restype = None
    dll.FspFileSystemDelete.argtypes = [c_void_p]
    dll.FspFileSystemDelete.restype = None
    dll.FspFileSystemAddDirInfo.argtypes = [c_void_p, c_void_p, U32, POINTER(U32)]
    dll.FspFileSystemAddDirInfo.restype = B
    return dll


class SistemaDeArquivos:
    """Monta uma unidade. `ops` é um objeto com métodos com os mesmos nomes de OPERACOES."""

    def __init__(self, ops, ponto="T:", rotulo="TeleCloud"):
        self.dll = _carregar()
        self.ops = ops
        self.ponto = ponto
        self.fs = c_void_p()
        self._refs = []

        vp = VolumeParams()
        vp.Version = sizeof(VolumeParams)
        vp.SectorSize = 4096
        vp.SectorsPerAllocationUnit = 1
        vp.MaxComponentLength = 255
        vp.VolumeSerialNumber = 0x7E1EC10D
        vp.FileInfoTimeout = 1000
        vp.Flags = CasePreservedNames | UnicodeOnDisk | PostCleanupWhenModifiedOnly
        vp.FileSystemName = "TeleCloud"

        tabela = (c_void_p * 64)()
        for nome, (i, ret, args) in OPERACOES.items():
            proto = CFUNCTYPE(ret, *args)
            cb = proto(getattr(ops, nome))
            self._refs.append(cb)
            tabela[i] = cast(cb, c_void_p)
        self._tabela = tabela
        self._vp = vp

        st = self.dll.FspFileSystemCreate("WinFsp.Disk", byref(vp), tabela, byref(self.fs))
        if st:
            raise OSError(f"FspFileSystemCreate falhou: 0x{st:08X}")
        st = self.dll.FspFileSystemSetMountPoint(self.fs, ponto)
        if st:
            self.dll.FspFileSystemDelete(self.fs)
            raise OSError(f"FspFileSystemSetMountPoint({ponto}) falhou: 0x{st:08X}")
        st = self.dll.FspFileSystemStartDispatcher(self.fs, 0)
        if st:
            self.dll.FspFileSystemDelete(self.fs)
            raise OSError(f"FspFileSystemStartDispatcher falhou: 0x{st:08X}")

    def adicionar_dir_info(self, buf, tam, transferido, bloco):
        return self.dll.FspFileSystemAddDirInfo(bloco, buf, tam, transferido)

    def desmontar(self):
        if self.fs:
            self.dll.FspFileSystemStopDispatcher(self.fs)
            self.dll.FspFileSystemDelete(self.fs)
            self.fs = c_void_p()
