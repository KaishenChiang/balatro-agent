"""Windows game lifecycle only. No save, game-state, shell or arbitrary commands."""
import ctypes
from ctypes import wintypes as w
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import subprocess

from .local_audit import no_links

APP_ID = '2379780'


class GameProcessError(Exception):
    def __init__(self, code):
        self.code = code


def vdf_value(text, name):
    # Only fixed leaf fields from Steam's installation metadata, never saves.
    values = re.findall(r'"' + re.escape(name) + r'"\s*"([^"\r\n]*)"', text)
    if len(values) != 1:
        raise GameProcessError('installation_unverified')
    return values[0].replace('\\\\', '\\')


@dataclass(frozen=True)
class Installation:
    steam: Path
    game: Path

    @classmethod
    def verify(cls, steam_dir, library_dir):
        steam_dir, library_dir = Path(steam_dir), Path(library_dir)
        if not steam_dir.is_absolute() or not library_dir.is_absolute():
            raise GameProcessError('installation_unverified')
        manifest = library_dir / 'steamapps/appmanifest_2379780.acf'
        no_links(manifest)
        if manifest.stat().st_size > 65536:
            raise GameProcessError('installation_unverified')
        text = manifest.read_text(encoding='utf-8')
        if len(text) > 65536 or vdf_value(text, 'appid') != APP_ID:
            raise GameProcessError('installation_unverified')
        folder = vdf_value(text, 'installdir')
        if not folder or folder in ('.', '..') or re.search(r'[/\\:]|[\x00-\x1f]', folder):
            raise GameProcessError('installation_unverified')
        steam = steam_dir / 'steam.exe'
        game = library_dir / 'steamapps/common' / folder / 'Balatro.exe'
        for path in (steam, game):
            no_links(path)
            if not path.is_file():
                raise GameProcessError('installation_unverified')
        return cls(steam.resolve(), game.resolve())

    @classmethod
    def discover(cls, config):
        if os.name != 'nt':
            raise GameProcessError('windows_only')
        if config.exists():
            no_links(config)
            if config.stat().st_size > 8192:
                raise GameProcessError('installation_unverified')
            data = json.loads(config.read_text(encoding='utf-8-sig'))
            if set(data) != {'steam_dir', 'library_dir'} or not all(isinstance(v, str) for v in data.values()):
                raise GameProcessError('installation_unverified')
            return cls.verify(data['steam_dir'], data['library_dir'])
        import winreg
        candidates = []
        for hive, key, value in (
            (winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam', 'SteamPath'),
            (winreg.HKEY_LOCAL_MACHINE, r'Software\Valve\Steam', 'InstallPath'),
            (winreg.HKEY_LOCAL_MACHINE, r'Software\WOW6432Node\Valve\Steam', 'InstallPath'),
        ):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    steam_dir = Path(winreg.QueryValueEx(handle, value)[0])
                libraries = [steam_dir]
                folders = steam_dir / 'steamapps/libraryfolders.vdf'
                no_links(folders)
                if folders.is_file():
                    text = folders.read_text(encoding='utf-8')
                    if len(text) > 262144:
                        raise GameProcessError('installation_unverified')
                    libraries += [Path(v.replace('\\\\', '\\')) for v in re.findall(r'"path"\s*"([^"\r\n]*)"', text)]
                for library in libraries:
                    try:
                        installation = cls.verify(steam_dir, library)
                        if installation not in candidates:
                            candidates.append(installation)
                    except (OSError, ValueError, GameProcessError):
                        pass
            except (OSError, ValueError, TypeError):
                pass
        if len(candidates) != 1:
            raise GameProcessError('installation_unverified')
        return candidates[0]


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    created: int


class ProcessEntry(ctypes.Structure):
    _fields_ = [('size', w.DWORD), ('usage', w.DWORD), ('pid', w.DWORD),
               ('heap', ctypes.c_size_t), ('module', w.DWORD), ('threads', w.DWORD),
               ('parent', w.DWORD), ('priority', w.LONG), ('flags', w.DWORD),
               ('exe', w.WCHAR * 260)]


class WindowsGame:
    def __init__(self, config):
        self.config = config
        self.installation = None

    def _init(self):
        if self.installation is not None:
            return
        installation = Installation.discover(self.config)
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.u = ctypes.WinDLL('user32', use_last_error=True)
        self.enum_callback = ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)
        declarations = [
            (self.k, 'CreateToolhelp32Snapshot', [w.DWORD, w.DWORD], w.HANDLE),
            (self.k, 'Process32FirstW', [w.HANDLE, ctypes.POINTER(ProcessEntry)], w.BOOL),
            (self.k, 'Process32NextW', [w.HANDLE, ctypes.POINTER(ProcessEntry)], w.BOOL),
            (self.k, 'OpenProcess', [w.DWORD, w.BOOL, w.DWORD], w.HANDLE),
            (self.k, 'QueryFullProcessImageNameW', [w.HANDLE, w.DWORD, w.LPWSTR, ctypes.POINTER(w.DWORD)], w.BOOL),
            (self.k, 'GetProcessTimes', [w.HANDLE] + [ctypes.POINTER(w.FILETIME)] * 4, w.BOOL),
            (self.k, 'CloseHandle', [w.HANDLE], w.BOOL),
            (self.u, 'EnumWindows', [self.enum_callback, w.LPARAM], w.BOOL),
            (self.u, 'GetWindowThreadProcessId', [w.HWND, ctypes.POINTER(w.DWORD)], w.DWORD),
            (self.u, 'GetClassNameW', [w.HWND, w.LPWSTR, ctypes.c_int], ctypes.c_int),
            (self.u, 'IsWindowVisible', [w.HWND], w.BOOL),
            (self.u, 'IsIconic', [w.HWND], w.BOOL),
            (self.u, 'ShowWindowAsync', [w.HWND, ctypes.c_int], w.BOOL),
            (self.u, 'SetForegroundWindow', [w.HWND], w.BOOL),
            (self.u, 'GetForegroundWindow', [], w.HWND),
            (self.u, 'PostMessageW', [w.HWND, w.UINT, w.WPARAM, w.LPARAM], w.BOOL),
        ]
        for dll, name, args, result in declarations:
            func = getattr(dll, name)
            func.argtypes, func.restype = args, result
        self.installation = installation

    def _identity(self, pid):
        handle = self.k.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            raise GameProcessError('process_unverified')
        try:
            buf, size = ctypes.create_unicode_buffer(32768), w.DWORD(32768)
            if not self.k.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                raise GameProcessError('process_unverified')
            if os.path.normcase(buf.value) != os.path.normcase(str(self.installation.game)):
                raise GameProcessError('process_unverified')
            times = [w.FILETIME() for _ in range(4)]
            if not self.k.GetProcessTimes(handle, *[ctypes.byref(t) for t in times]):
                raise GameProcessError('process_unverified')
            created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
            return ProcessIdentity(pid, created)
        finally:
            self.k.CloseHandle(handle)

    def find(self):
        self._init()
        snap = self.k.CreateToolhelp32Snapshot(2, 0)
        if snap == ctypes.c_void_p(-1).value:
            raise GameProcessError('process_unverified')
        matches = []
        try:
            entry = ProcessEntry()
            entry.size = ctypes.sizeof(entry)
            available = self.k.Process32FirstW(snap, ctypes.byref(entry))
            while available:
                if entry.exe.casefold() == 'balatro.exe':
                    # An inaccessible or differently installed Balatro is an
                    # ambiguity, never permission to start/close another one.
                    matches.append(self._identity(entry.pid))
                available = self.k.Process32NextW(snap, ctypes.byref(entry))
        finally:
            self.k.CloseHandle(snap)
        if len(matches) > 1:
            raise GameProcessError('multiple_game_processes')
        return matches[0] if matches else None

    def _window(self, process):
        if self.find() != process:
            raise GameProcessError('process_changed')
        windows = []

        @self.enum_callback
        def visit(hwnd, _):
            pid = w.DWORD()
            self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value == process.pid and self.u.IsWindowVisible(hwnd):
                # Fixed Windows LÖVE/SDL game window. Lovely may also own a
                # visible ConsoleWindowClass; WM_CLOSE must never target it.
                kind = ctypes.create_unicode_buffer(128)
                if self.u.GetClassNameW(hwnd, kind, len(kind)) > 0 and kind.value == 'SDL_app':
                    windows.append(hwnd)
            return True

        if not self.u.EnumWindows(visit, 0) or len(windows) != 1:
            raise GameProcessError('game_window_unverified')
        return windows[0]

    def focus(self, process):
        hwnd = self._window(process)
        if self.u.IsIconic(hwnd):
            self.u.ShowWindowAsync(hwnd, 9)  # SW_RESTORE
        self.u.SetForegroundWindow(hwnd)
        return self.u.GetForegroundWindow() == hwnd

    def launch(self):
        self._init()
        # Fixed Steam application and arguments; the model cannot supply a path,
        # executable, shell expression, process ID or command line.
        subprocess.Popen([str(self.installation.steam), '-applaunch', APP_ID],
                         cwd=self.installation.steam.parent,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)

    def close(self, process):
        hwnd = self._window(process)
        if self._identity(process.pid) != process:
            raise GameProcessError('process_changed')
        pid = w.DWORD()
        self.u.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != process.pid:
            raise GameProcessError('process_changed')
        if not self.u.PostMessageW(hwnd, 0x0010, 0, 0):  # native WM_CLOSE
            raise GameProcessError('close_dispatch_failed')
