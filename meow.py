from __future__ import annotations

import sys
import os
import math
import time
import threading
import ctypes
import struct
import subprocess
import traceback
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

_REQUIRED = {
    "pymem":        "pymem",
    "win32api":     "pywin32",
    "win32gui":     "pywin32",
    "win32con":     "pywin32",
    "keyboard":     "keyboard",
}

def _ensure_deps():
    missing = []
    for mod, pkg in _REQUIRED.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    missing = list(dict.fromkeys(missing))   # deduplicate
    if missing:
        print(f"[meow.cc] Installing missing packages: {missing}")
        for pkg in missing:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])
        print("[meow.cc] Done. Restart the script.")
        sys.exit(0)

_ensure_deps()

import pymem
import pymem.process
import win32gui
import win32con
import win32api
import keyboard
import tkinter as tk
from tkinter import ttk

class Off:
    # Pointers (client.dll)
    dwLocalPlayer          = 0xDEF97C
    dwEntityList           = 0x4E051DC
    dwViewMatrix           = 0x4DF6024
    dwGlowObjectManager    = 0x535BAD0
    dwForceJump            = 0x52C0F50
    dwForceAttack          = 0x3233024
    dwPlayerResource       = 0x3231380
    dwGameRulesProxy       = 0x5334764

    # engine.dll
    dwClientState          = 0x59F19C
    dwClientState_ViewAngles = 0x4D90

    # Entity members
    m_iHealth              = 0x100
    m_iTeamNum             = 0xF4
    m_bDormant             = 0xED
    m_vecOrigin            = 0x138
    m_vecViewOffset        = 0x108
    m_vecVelocity          = 0x114
    m_dwBoneMatrix         = 0x26A8
    m_iDefaultFOV          = 0x333C
    m_iFOV                 = 0x31F4
    m_iGlowIndex           = 0x10488
    m_AimPunchAngle        = 0x303C
    m_iShotsFired          = 0x103E0
    m_fFlags               = 0x104
    m_flFlashMaxAlpha      = 0x1046C
    m_flFlashDuration      = 0x10470
    m_clrRender            = 0x70
    m_szLastPlaceName      = 0x35C4
    m_lifeState            = 0x25F
    m_bIsScoped            = 0x9974
    # CS2-style crosshair / entity index offset
    m_iIDEntIndex          = 0x11838 

    # Weapon
    m_hMyWeapons           = 0x2E08
    m_iItemDefinitionIndex = 0x2FBA
    m_OriginalOwnerXuidLow = 0x31D0
    m_iItemIDHigh          = 0x2FD0
    m_nFallbackPaintKit    = 0x31D8
    m_iAccountID           = 0x2FD8
    m_nFallbackStatTrak    = 0x31E4
    m_nFallbackSeed        = 0x31DC
    m_flFallbackWear       = 0x31E0

    # model_ambient_min (engine.dll)
    model_ambient_min      = 0x5A1194



WEAPON_ID_MAP = {
    7:"AK-47", 9:"AWP", 61:"USP-S", 1:"Desert Eagle", 4:"Glock",
    3:"Five-Seven", 36:"P250", 30:"Tec-9", 16:"M4A4", 60:"M4A1-S",
    13:"Galil", 10:"Famas", 8:"AUG", 39:"SG-553", 40:"Scout",
    17:"Mac-10", 33:"MP7", 34:"MP9", 26:"PP-Bizon", 19:"P90",
    24:"UMP", 27:"Mag-7", 35:"Nova", 29:"Sawed Off", 25:"XM1014",
    64:"Revolver", 63:"CZ75-Auto", 2:"Dualies", 32:"P2000",
    23:"MP5-SD", 28:"Negev", 14:"M249", 11:"G3SG1", 38:"Scar-20",
}

WEAPON_SEEDS = {7: 661}   

@dataclass
class Config:
    # Aimbot
    aimbot_enabled: bool  = True
    aimbot_key: int       = 0x12      
    aimbot_fov: float     = 5.0
    aimbot_smooth: float  = 1.0
    aimbot_bone: int      = 8        
    aimbot_team_check: bool = True
    aimbot_rcs: bool      = True
    aimbot_rcs_x: float   = 2.0
    aimbot_rcs_y: float   = 2.0
    aimbot_silent: bool   = False     # silent aim 

    # Triggerbot
    triggerbot_enabled: bool = False
    triggerbot_key: int   = 0x70      # VK_F1
    triggerbot_delay: float = 0.03    # seconds before firing
    triggerbot_team_check: bool = True

    # ESP
    esp_enabled: bool     = True
    esp_box: bool         = True
    esp_health: bool      = True
    esp_head_dot: bool    = True
    esp_distance: bool    = True
    esp_name: bool        = True
    esp_snaplines: bool   = False
    esp_team_check: bool  = True
    esp_box_r: float      = 1.0
    esp_box_g: float      = 0.0
    esp_box_b: float      = 0.0
    esp_box_a: float      = 1.0

    # Glow
    glow_enabled: bool    = True
    glow_team_check: bool = True

    # Chams
    chams_enabled: bool   = False

    # BHop
    bhop_enabled: bool    = True
    bhop_key: int         = 0x20      # VK_SPACE

    # FOV
    fov_enabled: bool     = True
    fov_value: int        = 120

    # No-Flash
    no_flash: bool        = True

    # Skin Changer
    skinchanger_enabled: bool = False
    skin_file: str        = "skins.txt"

    # Radar
    radar_enabled: bool   = False

    # Third-Person
    thirdperson_enabled: bool = False
    thirdperson_on_key: int   = 0x73    # VK_F4  — enable third-person
    thirdperson_off_key: int  = 0x74    # VK_F5  — back to first-person

    # Misc
    menu_key: int         = 0x2D      # INSERT
    exit_key: int         = 0x23      # END
    render_hz: int        = 60
    show_fps: bool        = True



class CheatCore:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.pm: Optional[pymem.Pymem] = None
        self.client: int  = 0
        self.engine: int  = 0
        self.alive: bool  = True
        self.connected: bool = False
        self.status_msg: str = "Not connected"

        self.old_punch = [0.0, 0.0]
        self._csgo_hwnd: Optional[int] = None
        self._vm_cache: Optional[List[float]] = None
        self._vm_frame: int = -1
        self._frame: int    = 0

        # Skin paints loaded from file
        self._skin_map: dict[int, int] = {}   # weapon_id → paint_kit

        # Shared state (written by threads, read by GUI/overlay)
        self.lock = threading.Lock()
        self.entities: List[dict] = []          # snapshot for overlay/radar

    # ── connection ──────────────────────────────────────────────────────────
    def connect(self) -> bool:
        try:
            self.pm = pymem.Pymem("csgo.exe")
            self.client = pymem.process.module_from_name(
                self.pm.process_handle, "client.dll").lpBaseOfDll
            self.engine = pymem.process.module_from_name(
                self.pm.process_handle, "engine.dll").lpBaseOfDll
            self._find_window()
            self.connected = True
            self.status_msg = "Connected"
            return True
        except Exception as e:
            self.status_msg = f"Connect error: {e}"
            return False

    def _find_window(self):
        def _cb(hwnd, res):
            if win32gui.IsWindowVisible(hwnd):
                t = win32gui.GetWindowText(hwnd)
                if "Counter-Strike" in t or "csgo" in t.lower():
                    res.append(hwnd)
        res: list = []
        win32gui.EnumWindows(_cb, res)
        self._csgo_hwnd = res[0] if res else None

    def is_focused(self) -> bool:
        try:
            fg = ctypes.windll.user32.GetForegroundWindow()
            if not self._csgo_hwnd:
                self._find_window()
            return fg == self._csgo_hwnd
        except:
            return True

    # ── raw memory ──────────────────────────────────────────────────────────
    def ri(self, addr: int) -> int:
        try: return self.pm.read_int(addr)
        except: return 0

    def rf(self, addr: int) -> float:
        try: return self.pm.read_float(addr)
        except: return 0.0

    def ru(self, addr: int) -> int:
        try: return self.pm.read_uint(addr)
        except: return 0

    def rl(self, addr: int) -> int:
        """Read 8-byte unsigned (needed for CS2 entity list pointers)"""
        try:
            data = self.pm.read_bytes(addr, 8)
            return struct.unpack("<Q", data)[0]
        except: return 0

    def rs(self, addr: int, length: int = 32) -> str:
        try:
            b = self.pm.read_bytes(addr, length)
            return b.split(b"\x00")[0].decode("utf-8", errors="replace")
        except: return ""

    def wi(self, addr: int, val: int):
        try: self.pm.write_int(addr, val)
        except: pass

    def wf(self, addr: int, val: float):
        try: self.pm.write_float(addr, val)
        except: pass

    def wu(self, addr: int, val: int):
        try: self.pm.write_uchar(addr, val)
        except: pass

    # ── game helpers ────────────────────────────────────────────────────────
    def local_player(self) -> int:
        return self.ru(self.client + Off.dwLocalPlayer)

    def client_state(self) -> int:
        return self.ru(self.engine + Off.dwClientState)

    def get_entity(self, index: int) -> int:
        return self.ru(self.client + Off.dwEntityList + index * 0x10)

    # CS2-correct entity lookup via entity list indirection
    def get_entity_cs2(self, crosshair_id: int) -> int:
        """Resolve entity pawn from crosshair entity index (CS2 style)."""
        entity_list = self.rl(self.client + Off.dwEntityList)
        if not entity_list:
            return 0
        list_entry = self.rl(entity_list + 0x8 * (crosshair_id >> 9) + 0x10)
        if not list_entry:
            return 0
        return self.rl(list_entry + 120 * (crosshair_id & 0x1FF))

    def view_matrix(self) -> List[float]:
        if self._vm_frame == self._frame and self._vm_cache:
            return self._vm_cache
        base = self.client + Off.dwViewMatrix
        m = [self.rf(base + i * 4) for i in range(16)]
        self._vm_cache = m
        self._vm_frame = self._frame
        return m

    def tick_frame(self):
        self._frame += 1

    def w2s(self, pos: Tuple[float, float, float],
             W: int, H: int) -> Optional[Tuple[float, float]]:
        m = self.view_matrix()
        w = m[12]*pos[0] + m[13]*pos[1] + m[14]*pos[2] + m[15]
        if w < 0.001:
            return None
        x = m[0]*pos[0] + m[1]*pos[1] + m[2]*pos[2] + m[3]
        y = m[4]*pos[0] + m[5]*pos[1] + m[6]*pos[2] + m[7]
        return (W/2 * (1 + x/w), H/2 * (1 - y/w))

    def bone_pos(self, entity: int, bone: int) -> Optional[Tuple[float,float,float]]:
        bm = self.ru(entity + Off.m_dwBoneMatrix)
        if bm < 0x10000:
            return None
        return (self.rf(bm + 0x30*bone + 0x0C),
                self.rf(bm + 0x30*bone + 0x1C),
                self.rf(bm + 0x30*bone + 0x2C))

    def eye_pos(self, entity: int) -> Tuple[float,float,float]:
        ox = Off.m_vecOrigin
        return (self.rf(entity + ox),
                self.rf(entity + ox + 4),
                self.rf(entity + ox + 8) + self.rf(entity + Off.m_vecViewOffset + 8))

    def calc_angles(self, src, dst) -> Tuple[float, float]:
        dx, dy, dz = dst[0]-src[0], dst[1]-src[1], dst[2]-src[2]
        hyp = math.sqrt(dx*dx + dy*dy)
        return (-math.atan2(dz, hyp)*180/math.pi,
                 math.atan2(dy, dx)*180/math.pi)

    def norm_angles(self, p: float, y: float) -> Tuple[float,float]:
        p = max(-89.0, min(89.0, p))
        while y >  180.0: y -= 360.0
        while y < -180.0: y += 360.0
        return p, y

    def get_view_angles(self, cs: int) -> Tuple[float,float]:
        return (self.rf(cs + Off.dwClientState_ViewAngles),
                self.rf(cs + Off.dwClientState_ViewAngles + 4))

    def set_view_angles(self, cs: int, pitch: float, yaw: float):
        self.wf(cs + Off.dwClientState_ViewAngles,     pitch)
        self.wf(cs + Off.dwClientState_ViewAngles + 4, yaw)

    def left_click(self):
        ctypes.windll.user32.mouse_event(2, 0, 0, 0, 0)   # MOUSEEVENTF_LEFTDOWN
        time.sleep(0.01)
        ctypes.windll.user32.mouse_event(4, 0, 0, 0, 0)   # MOUSEEVENTF_LEFTUP

    def load_skins(self) -> bool:
        try:
            self._skin_map.clear()
            sf = self.cfg.skin_file
            if not os.path.isabs(sf):
                sf = os.path.join(os.path.dirname(__file__), sf)
            with open(sf, encoding="utf-8") as fh:
                lines = fh.readlines()
            # Map weapon name → paint kit from file
            name_to_kit: dict[str, int] = {}
            for line in lines:
                line = line.strip()
                if not line or "=" not in line:
                    continue
                name, kit = line.rsplit("=", 1)
                name_to_kit[name.strip()] = int(kit.strip())
            # Reverse-map via WEAPON_ID_MAP
            for wid, wname in WEAPON_ID_MAP.items():
                if wname in name_to_kit:
                    self._skin_map[wid] = name_to_kit[wname]
            return True
        except Exception as e:
            self.status_msg = f"Skin load error: {e}"
            return False



def _key_held(vk: int) -> bool:
    return bool(ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000)


def thread_aimbot(core: CheatCore):
    """Aimbot — holds AIM_KEY, finds closest head in FOV, smoothly aims."""
    while core.alive:
        try:
            cfg = core.cfg
            if not cfg.aimbot_enabled or not core.connected:
                time.sleep(0.01); continue
            if not _key_held(cfg.aimbot_key):
                time.sleep(0.005); continue

            local = core.local_player()
            cs    = core.client_state()
            if not local or not cs:
                time.sleep(0.005); continue

            my_team = core.ri(local + Off.m_iTeamNum)
            my_pos  = core.eye_pos(local)
            vx, vy  = core.get_view_angles(cs)

            best_fov = 99999.0
            best_ang = None

            for i in range(1, 64):
                ent = core.get_entity(i)
                if not ent or ent < 0x10000: continue
                if core.ri(ent + Off.m_bDormant):  continue
                hp = core.ri(ent + Off.m_iHealth)
                if hp <= 0: continue
                team = core.ri(ent + Off.m_iTeamNum)
                if cfg.aimbot_team_check and team == my_team: continue

                head = core.bone_pos(ent, cfg.aimbot_bone)
                if not head: continue

                tp, ty = core.calc_angles(my_pos, head)
                fov_d = math.sqrt((tp - vx)**2 + (ty - vy)**2)

                if fov_d < cfg.aimbot_fov and fov_d < best_fov:
                    best_fov = fov_d
                    best_ang = (tp, ty)

            if best_ang:
                sm = max(1.0, cfg.aimbot_smooth)
                np = vx + (best_ang[0] - vx) / sm
                ny = vy + (best_ang[1] - vy) / sm
                np, ny = core.norm_angles(np, ny)
                core.set_view_angles(cs, np, ny)

            time.sleep(0.001)
        except:
            time.sleep(0.02)


def thread_rcs(core: CheatCore):
    """Recoil Control System — compensates punch angle after first shot."""
    while core.alive:
        try:
            cfg = core.cfg
            if not cfg.aimbot_rcs or not core.connected:
                time.sleep(0.05); continue

            local = core.local_player()
            cs    = core.client_state()
            if not local or not cs:
                time.sleep(0.005); continue

            shots = core.ri(local + Off.m_iShotsFired)
            if shots > 1:
                vx, vy  = core.get_view_angles(cs)
                px = core.rf(local + Off.m_AimPunchAngle)
                py = core.rf(local + Off.m_AimPunchAngle + 4)
                nx = vx + (core.old_punch[0] - px * cfg.aimbot_rcs_x)
                ny = vy + (core.old_punch[1] - py * cfg.aimbot_rcs_y)
                nx, ny = core.norm_angles(nx, ny)
                core.set_view_angles(cs, nx, ny)
                core.old_punch[0] = px * cfg.aimbot_rcs_x
                core.old_punch[1] = py * cfg.aimbot_rcs_y
            else:
                core.old_punch = [0.0, 0.0]

            time.sleep(0.002)
        except:
            time.sleep(0.02)


def thread_triggerbot(core: CheatCore):

    while core.alive:
        try:
            cfg = core.cfg
            if not cfg.triggerbot_enabled or not core.connected:
                time.sleep(0.01); continue
            if not _key_held(cfg.triggerbot_key):
                time.sleep(0.003); continue

            local = core.local_player()
            if not local:
                time.sleep(0.005); continue

            local_team    = core.ri(local + Off.m_iTeamNum)
            crosshair_id  = core.ri(local + Off.m_iIDEntIndex)

            if crosshair_id <= 0:
                time.sleep(0.003); continue

            # CS2-style entity resolution (the fix from UnknownCheats)
            entity_pawn = core.get_entity_cs2(crosshair_id)
            if not entity_pawn:
                time.sleep(0.003); continue

            hp = core.ri(entity_pawn + Off.m_iHealth)
            if hp <= 0:
                time.sleep(0.003); continue

            entity_team = core.ri(entity_pawn + Off.m_iTeamNum)
            if cfg.triggerbot_team_check and entity_team == local_team:
                time.sleep(0.003); continue

            # Delay before shooting (avoid detection pattern)
            time.sleep(cfg.triggerbot_delay)
            core.left_click()
            time.sleep(0.05)   # brief cooldown after shot

        except:
            time.sleep(0.02)


def thread_bhop(core: CheatCore):
    while core.alive:
        try:
            cfg = core.cfg
            if not cfg.bhop_enabled or not core.connected:
                time.sleep(0.05); continue
            if not _key_held(cfg.bhop_key):
                time.sleep(0.002); continue

            local = core.local_player()
            if not local:
                time.sleep(0.005); continue

            flags = core.ri(local + Off.m_fFlags)
            # 257 / 263 = on ground
            if flags == 257 or flags == 263:
                core.wi(core.client + Off.dwForceJump, 5)
                time.sleep(0.015)
                core.wi(core.client + Off.dwForceJump, 4)

            time.sleep(0.002)
        except:
            time.sleep(0.02)


def thread_glow(core: CheatCore):
    while core.alive:
        try:
            cfg = core.cfg
            if not cfg.glow_enabled or not core.connected:
                time.sleep(0.1); continue

            gm    = core.ru(core.client + Off.dwGlowObjectManager)
            local = core.local_player()
            if not gm or not local:
                time.sleep(0.2); continue

            my_team = core.ri(local + Off.m_iTeamNum)

            for i in range(1, 64):
                ent = core.get_entity(i)
                if not ent or ent < 0x10000: continue
                hp  = core.ri(ent + Off.m_iHealth)
                if hp <= 0: continue
                team  = core.ri(ent + Off.m_iTeamNum)
                gidx  = core.ri(ent + Off.m_iGlowIndex)
                if gidx < 0: continue

                base = gm + gidx * 0x38
                if team == my_team:
                    if cfg.glow_team_check: continue
                    r, g, b = 0.0, 1.0, 0.0   # green = teammate
                else:
                    r, g, b = 1.0, 0.1, 0.1   # red   = enemy

                core.wf(base + 0x8,  r)
                core.wf(base + 0xC,  g)
                core.wf(base + 0x10, b)
                core.wf(base + 0x14, 1.0)
                core.wi(base + 0x28, 1)

            time.sleep(0.02)
        except:
            time.sleep(0.2)


def thread_chams(core: CheatCore):

    while core.alive:
        try:
            cfg = core.cfg
            if not cfg.chams_enabled or not core.connected:
                time.sleep(0.1); continue

            # Brighten ambient so tint is visible
            core.wf(core.engine + Off.model_ambient_min, 10.0)

            local = core.local_player()
            if not local:
                time.sleep(0.05); continue

            my_team = core.ri(local + Off.m_iTeamNum)

            for i in range(1, 64):
                ent = core.get_entity(i)
                if not ent or ent < 0x10000: continue
                if core.ri(ent + Off.m_bDormant):  continue
                hp = core.ri(ent + Off.m_iHealth)
                if hp <= 0: continue

                team = core.ri(ent + Off.m_iTeamNum)
                base = ent + Off.m_clrRender

                if team != my_team:
                    core.wu(base,     255); core.wu(base+1, 0)
                    core.wu(base+2,   0);   core.wu(base+3, 255)
                else:
                    core.wu(base,     0);   core.wu(base+1, 0)
                    core.wu(base+2,   255); core.wu(base+3, 120)

            time.sleep(0.05)
        except:
            time.sleep(0.2)


def thread_no_flash(core: CheatCore):

    while core.alive:
        try:
            if not core.cfg.no_flash or not core.connected:
                time.sleep(0.3); continue
            local = core.local_player()
            if local:
                core.wf(local + Off.m_flFlashMaxAlpha, 0.0)
            time.sleep(0.1)
        except:
            time.sleep(0.3)


def thread_fov(core: CheatCore):

    while core.alive:
        try:
            cfg = core.cfg
            if not cfg.fov_enabled or not core.connected:
                time.sleep(0.5); continue
            local = core.local_player()
            if local:
                core.wi(local + Off.m_iDefaultFOV, cfg.fov_value)
            time.sleep(0.5)
        except:
            time.sleep(0.5)


def thread_skinchanger(core: CheatCore):

    while core.alive:
        try:
            cfg = core.cfg
            if not cfg.skinchanger_enabled or not core.connected:
                time.sleep(0.5); continue
            if not core._skin_map:
                core.load_skins()

            local = core.local_player()
            cs    = core.client_state()
            if not local or not cs:
                time.sleep(0.5); continue

            for i in range(8):
                try:
                    slot = core.ru(local + Off.m_hMyWeapons + i * 4) & 0xFFF
                    waddr = core.ru(core.client + Off.dwEntityList + (slot - 1) * 0x10)
                    if not waddr: continue
                    wid = core.pm.read_short(waddr + Off.m_iItemDefinitionIndex)
                    if wid not in core._skin_map: continue

                    paint = core._skin_map[wid]
                    seed  = WEAPON_SEEDS.get(wid, 420)
                    owner = core.ri(waddr + Off.m_OriginalOwnerXuidLow)

                    core.wi(waddr + Off.m_iItemIDHigh,         -1)
                    core.wi(waddr + Off.m_nFallbackPaintKit,    paint)
                    core.wi(waddr + Off.m_iAccountID,           owner)
                    core.wi(waddr + Off.m_nFallbackStatTrak,    187)
                    core.wi(waddr + Off.m_nFallbackSeed,        seed)
                    core.wf(waddr + Off.m_flFallbackWear,       0.000001)
                except:
                    continue

            # F6 = force update
            if keyboard.is_pressed("f6"):
                core.wi(cs + 0x174, -1)

            time.sleep(0.1)
        except:
            time.sleep(0.5)


def thread_thirdperson(core: CheatCore):
    _TP_ON  = 1    # third-person
    _TP_OFF = 0    # first-person
    _prev_enabled = False

    while core.alive:
        try:
            cfg = core.cfg
            if not core.connected:
                time.sleep(0.05); continue

            local = core.local_player()
            if not local:
                time.sleep(0.05); continue

            # Key press toggles
            if _key_held(cfg.thirdperson_on_key):
                cfg.thirdperson_enabled = True
            elif _key_held(cfg.thirdperson_off_key):
                cfg.thirdperson_enabled = False

            # Write observer mode only when state changes OR continuously
            # while enabled (some builds reset it each frame)
            mode = _TP_ON if cfg.thirdperson_enabled else _TP_OFF
            core.wi(local + Off.m_iObserverMode, mode)

            # When feature is freshly disabled, force first-person once more
            if _prev_enabled and not cfg.thirdperson_enabled:
                core.wi(local + Off.m_iObserverMode, _TP_OFF)

            _prev_enabled = cfg.thirdperson_enabled
            time.sleep(0.01)
        except:
            time.sleep(0.05)


def thread_entity_snapshot(core: CheatCore):
    while core.alive:
        try:
            if not core.connected:
                time.sleep(0.05); continue

            local = core.local_player()
            if not local:
                with core.lock:
                    core.entities.clear()
                time.sleep(0.05); continue

            my_team = core.ri(local + Off.m_iTeamNum)
            my_pos  = core.eye_pos(local)
            snap: List[dict] = []

            for i in range(1, 64):
                ent = core.get_entity(i)
                if not ent or ent < 0x10000: continue
                if core.ri(ent + Off.m_bDormant):  continue
                hp = core.ri(ent + Off.m_iHealth)
                if hp <= 0: continue
                team = core.ri(ent + Off.m_iTeamNum)

                ox = Off.m_vecOrigin
                foot = (core.rf(ent + ox),
                        core.rf(ent + ox + 4),
                        core.rf(ent + ox + 8))
                head = core.bone_pos(ent, 8)
                if not head: continue

                dist = math.sqrt(sum((a-b)**2 for a,b in zip(head, my_pos))) / 100.0
                name = core.rs(ent + Off.m_szLastPlaceName, 32)
                scoped = bool(core.ri(ent + Off.m_bIsScoped))

                snap.append({
                    "addr": ent, "hp": hp, "team": team, "enemy": team != my_team,
                    "foot": foot, "head": head, "dist": dist,
                    "name": name, "scoped": scoped,
                })

            core.tick_frame()
            with core.lock:
                core.entities = snap

            time.sleep(1.0 / 60.0)   # 60 Hz read loop
        except:
            time.sleep(0.05)


class NativeOverlayApp:
    def __init__(self, core: CheatCore):
        self.core = core
        self.cfg = core.cfg


        self.root = tk.Tk()
        self.root.title("meow.cc Overlay")
        self.root.overrideredirect(True)
        self.root.wm_attributes("-topmost", True)

        self.W = self.root.winfo_screenwidth()
        self.H = self.root.winfo_screenheight()
        self.root.geometry(f"{self.W}x{self.H}+0+0")

        # System key color for 100% transparency
        self.TRANS_COLOR = "#000001"
        self.root.config(bg=self.TRANS_COLOR)
        self.root.wm_attributes("-transparentcolor", self.TRANS_COLOR)

        self.canvas = tk.Canvas(
            self.root,
            width=self.W,
            height=self.H,
            bg=self.TRANS_COLOR,
            highlightthickness=0,
            bd=0
        )
        self.canvas.pack(fill="both", expand=True)

        self.overlay_hwnd = None
        self.root.update_idletasks()
        try:
            self.overlay_hwnd = win32gui.FindWindow(None, "meow.cc Overlay")
            if self.overlay_hwnd:
                # Force clickthrough on the canvas overlay
                ex_style = win32gui.GetWindowLong(self.overlay_hwnd, win32con.GWL_EXSTYLE)
                ex_style |= win32con.WS_EX_TRANSPARENT | win32con.WS_EX_LAYERED
                win32gui.SetWindowLong(self.overlay_hwnd, win32con.GWL_EXSTYLE, ex_style)
        except Exception:
            pass

        # ── Setup Floating Modern Menu Window ──────────────────────────────────
        self.menu_window = tk.Toplevel(self.root)
        self.menu_window.title("meow.cc")
        self.menu_window.geometry("460x540+60+60")
        self.menu_window.configure(bg="#121212")
        self.menu_window.attributes("-topmost", True)
        self.menu_window.resizable(False, False)

        # Style menu widgets
        self.setup_menu_style()
        self.build_menu_ui()

        self.menu_open = True
        self.last_menu_key = False

        # Periodic loops
        self.root.after(10, self.render_esp)
        self.root.after(20, self.poll_hotkeys)

    def setup_menu_style(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")

        # Notebook tabs styling
        self.style.configure(
            "TNotebook",
            background="#121212",
            borderwidth=0
        )
        self.style.configure(
            "TNotebook.Tab",
            background="#1e1e1e",
            foreground="#aaaaaa",
            padding=[14, 8],
            font=("Consolas", 10, "bold")
        )
        self.style.map(
            "TNotebook.Tab",
            background=[("selected", "#00aa00")],
            foreground=[("selected", "#ffffff")]
        )

        # Checkbutton styling
        self.style.configure(
            "TCheckbutton",
            background="#181818",
            foreground="#ffffff",
            font=("Consolas", 10)
        )
        self.style.map(
            "TCheckbutton",
            foreground=[("active", "#00ff00")],
            background=[("active", "#181818")]
        )

    def build_menu_ui(self):
        # Header banner
        header = tk.Frame(self.menu_window, bg="#0d0d0d", pady=8, padx=12)
        header.pack(fill="x")

        title_lbl = tk.Label(
            header,
            text="meow.cc ★ CS2/CSGO All-In-One",
            fg="#00ff00",
            bg="#0d0d0d",
            font=("Consolas", 12, "bold")
        )
        title_lbl.pack(side="left")

        self.status_lbl = tk.Label(
            header,
            text="[Connected]",
            fg="#00cc00",
            bg="#0d0d0d",
            font=("Consolas", 9)
        )
        self.status_lbl.pack(side="right")

        # Instruction note
        sub_bar = tk.Frame(self.menu_window, bg="#1a1a1a", pady=3, padx=12)
        sub_bar.pack(fill="x")
        tk.Label(
            sub_bar,
            text="INSERT: Toggle Menu  |  END: Exit Cheat",
            fg="#888888",
            bg="#1a1a1a",
            font=("Consolas", 8)
        ).pack(side="left")

        notebook = ttk.Notebook(self.menu_window)
        notebook.pack(fill="both", expand=True, padx=8, pady=8)

        # ── Tab: Aimbot ──────────────────────────────────────────
        tab_aim = tk.Frame(notebook, bg="#181818", padx=14, pady=12)
        notebook.add(tab_aim, text="Aimbot")

        self.cb_aim = tk.BooleanVar(value=self.cfg.aimbot_enabled)
        ttk.Checkbutton(tab_aim, text="Enable Aimbot (Hold ALT)", variable=self.cb_aim,
                        command=lambda: setattr(self.cfg, "aimbot_enabled", self.cb_aim.get())).pack(anchor="w", pady=4)

        self.cb_aim_team = tk.BooleanVar(value=self.cfg.aimbot_team_check)
        ttk.Checkbutton(tab_aim, text="Team Check", variable=self.cb_aim_team,
                        command=lambda: setattr(self.cfg, "aimbot_team_check", self.cb_aim_team.get())).pack(anchor="w", pady=4)

        self.cb_rcs = tk.BooleanVar(value=self.cfg.aimbot_rcs)
        ttk.Checkbutton(tab_aim, text="Recoil Control System (RCS)", variable=self.cb_rcs,
                        command=lambda: setattr(self.cfg, "aimbot_rcs", self.cb_rcs.get())).pack(anchor="w", pady=4)

        tk.Label(tab_aim, text="Aimbot FOV:", fg="#ffffff", bg="#181818", font=("Consolas", 9)).pack(anchor="w", pady=(10, 2))
        self.scale_fov = tk.Scale(tab_aim, from_=0.5, to=40.0, resolution=0.5, orient="horizontal",
                                  bg="#181818", fg="#00ff00", highlightthickness=0,
                                  command=lambda v: setattr(self.cfg, "aimbot_fov", float(v)))
        self.scale_fov.set(self.cfg.aimbot_fov)
        self.scale_fov.pack(fill="x")

        tk.Label(tab_aim, text="Smoothness:", fg="#ffffff", bg="#181818", font=("Consolas", 9)).pack(anchor="w", pady=(8, 2))
        self.scale_smooth = tk.Scale(tab_aim, from_=1.0, to=20.0, resolution=0.5, orient="horizontal",
                                     bg="#181818", fg="#00ff00", highlightthickness=0,
                                     command=lambda v: setattr(self.cfg, "aimbot_smooth", float(v)))
        self.scale_smooth.set(self.cfg.aimbot_smooth)
        self.scale_smooth.pack(fill="x")

        # ── Tab: Triggerbot ──────────────────────────────────────
        tab_trig = tk.Frame(notebook, bg="#181818", padx=14, pady=12)
        notebook.add(tab_trig, text="Trigger")

        tk.Label(tab_trig, text="CS2 External Trigger Bot (Hold F1)", fg="#00e5ff", bg="#181818", font=("Consolas", 10, "bold")).pack(anchor="w", pady=(0, 8))

        self.cb_trig = tk.BooleanVar(value=self.cfg.triggerbot_enabled)
        ttk.Checkbutton(tab_trig, text="Enable Triggerbot", variable=self.cb_trig,
                        command=lambda: setattr(self.cfg, "triggerbot_enabled", self.cb_trig.get())).pack(anchor="w", pady=4)

        self.cb_trig_team = tk.BooleanVar(value=self.cfg.triggerbot_team_check)
        ttk.Checkbutton(tab_trig, text="Team Check (Enemies Only)", variable=self.cb_trig_team,
                        command=lambda: setattr(self.cfg, "triggerbot_team_check", self.cb_trig_team.get())).pack(anchor="w", pady=4)

        tk.Label(tab_trig, text="Pre-fire Delay (Seconds):", fg="#ffffff", bg="#181818", font=("Consolas", 9)).pack(anchor="w", pady=(12, 2))
        self.scale_tdelay = tk.Scale(tab_trig, from_=0.0, to=0.25, resolution=0.01, orient="horizontal",
                                     bg="#181818", fg="#00ff00", highlightthickness=0,
                                     command=lambda v: setattr(self.cfg, "triggerbot_delay", float(v)))
        self.scale_tdelay.set(self.cfg.triggerbot_delay)
        self.scale_tdelay.pack(fill="x")

        tk.Label(tab_trig, text="✓ Features 64-bit CS2 entity pointer resolution fix", fg="#888888", bg="#181818", font=("Consolas", 8)).pack(anchor="w", pady=(18, 2))
        tk.Label(tab_trig, text="✓ Automatically clicks when crosshair hits target", fg="#888888", bg="#181818", font=("Consolas", 8)).pack(anchor="w")

        # ── Tab: ESP ─────────────────────────────────────────────
        tab_esp = tk.Frame(notebook, bg="#181818", padx=14, pady=12)
        notebook.add(tab_esp, text="ESP")

        self.cb_esp = tk.BooleanVar(value=self.cfg.esp_enabled)
        ttk.Checkbutton(tab_esp, text="Enable Visual ESP", variable=self.cb_esp,
                        command=lambda: setattr(self.cfg, "esp_enabled", self.cb_esp.get())).pack(anchor="w", pady=4)

        self.cb_box = tk.BooleanVar(value=self.cfg.esp_box)
        ttk.Checkbutton(tab_esp, text="Corner Bounding Box", variable=self.cb_box,
                        command=lambda: setattr(self.cfg, "esp_box", self.cb_box.get())).pack(anchor="w", pady=4)

        self.cb_hp = tk.BooleanVar(value=self.cfg.esp_health)
        ttk.Checkbutton(tab_esp, text="Dynamic Health Bar", variable=self.cb_hp,
                        command=lambda: setattr(self.cfg, "esp_health", self.cb_hp.get())).pack(anchor="w", pady=4)

        self.cb_head = tk.BooleanVar(value=self.cfg.esp_head_dot)
        ttk.Checkbutton(tab_esp, text="Head Dot", variable=self.cb_head,
                        command=lambda: setattr(self.cfg, "esp_head_dot", self.cb_head.get())).pack(anchor="w", pady=4)

        self.cb_dist = tk.BooleanVar(value=self.cfg.esp_distance)
        ttk.Checkbutton(tab_esp, text="Distance Indicator", variable=self.cb_dist,
                        command=lambda: setattr(self.cfg, "esp_distance", self.cb_dist.get())).pack(anchor="w", pady=4)

        self.cb_snap = tk.BooleanVar(value=self.cfg.esp_snaplines)
        ttk.Checkbutton(tab_esp, text="Snaplines", variable=self.cb_snap,
                        command=lambda: setattr(self.cfg, "esp_snaplines", self.cb_snap.get())).pack(anchor="w", pady=4)

        self.cb_esp_team = tk.BooleanVar(value=self.cfg.esp_team_check)
        ttk.Checkbutton(tab_esp, text="Filter Out Teammates", variable=self.cb_esp_team,
                        command=lambda: setattr(self.cfg, "esp_team_check", self.cb_esp_team.get())).pack(anchor="w", pady=4)

        # ── Tab: Visuals ─────────────────────────────────────────
        tab_vis = tk.Frame(notebook, bg="#181818", padx=14, pady=12)
        notebook.add(tab_vis, text="Visuals")

        self.cb_glow = tk.BooleanVar(value=self.cfg.glow_enabled)
        ttk.Checkbutton(tab_vis, text="Enable Glow ESP", variable=self.cb_glow,
                        command=lambda: setattr(self.cfg, "glow_enabled", self.cb_glow.get())).pack(anchor="w", pady=4)

        self.cb_glow_team = tk.BooleanVar(value=self.cfg.glow_team_check)
        ttk.Checkbutton(tab_vis, text="Skip Teammates (Glow)", variable=self.cb_glow_team,
                        command=lambda: setattr(self.cfg, "glow_team_check", self.cb_glow_team.get())).pack(anchor="w", pady=4)

        self.cb_chams = tk.BooleanVar(value=self.cfg.chams_enabled)
        ttk.Checkbutton(tab_vis, text="Enable Chams (Color Tint)", variable=self.cb_chams,
                        command=lambda: setattr(self.cfg, "chams_enabled", self.cb_chams.get())).pack(anchor="w", pady=4)

        self.cb_skins = tk.BooleanVar(value=self.cfg.skinchanger_enabled)
        ttk.Checkbutton(tab_vis, text="Enable Skin Changer", variable=self.cb_skins,
                        command=lambda: setattr(self.cfg, "skinchanger_enabled", self.cb_skins.get())).pack(anchor="w", pady=4)

        reload_btn = tk.Button(tab_vis, text="Reload skins.txt", bg="#2a2a2a", fg="#ffffff", font=("Consolas", 9),
                               command=lambda: self.core.load_skins())
        reload_btn.pack(anchor="w", pady=8)

        # ── Tab: Keybinds ────────────────────────────────────────
        tab_keys = tk.Frame(notebook, bg="#181818", padx=14, pady=12)
        notebook.add(tab_keys, text="Keybinds")

        tk.Label(tab_keys, text="Custom Hotkeys & Keybinds", fg="#00ff00", bg="#181818", font=("Consolas", 10, "bold")).pack(anchor="w", pady=(0, 10))

        self.key_names = {
            0x01: "Left Click", 0x02: "Right Click", 0x04: "Middle Click",
            0x05: "Mouse X1", 0x06: "Mouse X2", 0x10: "SHIFT", 0x11: "CTRL",
            0x12: "ALT", 0x20: "SPACE", 0x2D: "INSERT", 0x2E: "DELETE",
            0x23: "END", 0x24: "HOME", 0x70: "F1", 0x71: "F2", 0x72: "F3",
            0x73: "F4", 0x74: "F5", 0x75: "F6", 0x76: "F7", 0x77: "F8",
            0x78: "F9", 0x79: "F10", 0x7A: "F11", 0x7B: "F12"
        }
        for k in range(0x41, 0x5B):
            self.key_names[k] = chr(k)

        self.bind_buttons = {}

        def create_keybind_row(parent, label_text, config_attr):
            row = tk.Frame(parent, bg="#181818", pady=4)
            row.pack(fill="x")

            lbl = tk.Label(row, text=label_text, fg="#ffffff", bg="#181818", font=("Consolas", 9), width=24, anchor="w")
            lbl.pack(side="left")

            current_vk = getattr(self.cfg, config_attr)
            btn_text = self.key_names.get(current_vk, f"0x{current_vk:X}")
            btn = tk.Button(row, text=btn_text, width=12, bg="#262626", fg="#00e5ff",
                            font=("Consolas", 9, "bold"), relief="flat", activebackground="#333333")
            btn.pack(side="right")
            self.bind_buttons[config_attr] = btn

            def start_bind(attr=config_attr, b=btn):
                b.config(text="[Press Key...]", fg="#ffff00")
                self.listening_bind = attr

            btn.config(command=start_bind)

        create_keybind_row(tab_keys, "Aimbot Hold Key:", "aimbot_key")
        create_keybind_row(tab_keys, "Triggerbot Hold Key:", "triggerbot_key")
        create_keybind_row(tab_keys, "Bunny Hop Key:", "bhop_key")
        create_keybind_row(tab_keys, "Third-Person ON Key:", "thirdperson_on_key")
        create_keybind_row(tab_keys, "Third-Person OFF Key:", "thirdperson_off_key")
        create_keybind_row(tab_keys, "Toggle Menu Key:", "menu_key")
        create_keybind_row(tab_keys, "Exit Cheat Key:", "exit_key")

        self.listening_bind = None

        tk.Label(tab_keys, text="Click any button, then press any key or mouse button to bind.", fg="#888888", bg="#181818", font=("Consolas", 8)).pack(anchor="w", pady=(14, 0))

        # ── Tab: Misc ────────────────────────────────────────────
        tab_misc = tk.Frame(notebook, bg="#181818", padx=14, pady=12)
        notebook.add(tab_misc, text="Misc")

        self.cb_bhop = tk.BooleanVar(value=self.cfg.bhop_enabled)
        ttk.Checkbutton(tab_misc, text="Bunny Hop", variable=self.cb_bhop,
                        command=lambda: setattr(self.cfg, "bhop_enabled", self.cb_bhop.get())).pack(anchor="w", pady=4)

        self.cb_noflash = tk.BooleanVar(value=self.cfg.no_flash)
        ttk.Checkbutton(tab_misc, text="No Flash Effect", variable=self.cb_noflash,
                        command=lambda: setattr(self.cfg, "no_flash", self.cb_noflash.get())).pack(anchor="w", pady=4)

        self.cb_fov = tk.BooleanVar(value=self.cfg.fov_enabled)
        ttk.Checkbutton(tab_misc, text="Custom FOV Changer", variable=self.cb_fov,
                        command=lambda: setattr(self.cfg, "fov_enabled", self.cb_fov.get())).pack(anchor="w", pady=4)

        tk.Label(tab_misc, text="Field of View Value:", fg="#ffffff", bg="#181818", font=("Consolas", 9)).pack(anchor="w", pady=(6, 2))
        self.scale_fovval = tk.Scale(tab_misc, from_=60, to=150, orient="horizontal",
                                     bg="#181818", fg="#00ff00", highlightthickness=0,
                                     command=lambda v: setattr(self.cfg, "fov_value", int(v)))
        self.scale_fovval.set(self.cfg.fov_value)
        self.scale_fovval.pack(fill="x")

        self.cb_tp = tk.BooleanVar(value=self.cfg.thirdperson_enabled)
        ttk.Checkbutton(tab_misc, text="Third-Person View", variable=self.cb_tp,
                        command=lambda: setattr(self.cfg, "thirdperson_enabled", self.cb_tp.get())).pack(anchor="w", pady=(10, 4))

        self.tp_status = tk.Label(tab_misc, text="Status: First-Person", fg="#888888", bg="#181818", font=("Consolas", 8))
        self.tp_status.pack(anchor="w")

    def poll_hotkeys(self):
        # Check if user is currently binding a key
        if self.listening_bind:
            for vk in range(1, 255):
                # Ignore common virtual modifier duplicates
                if vk in (0x10, 0x11, 0x12, 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5):
                    # Check physical Shift/Ctrl/Alt keys instead
                    pass
                if ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000:
                    setattr(self.cfg, self.listening_bind, vk)
                    btn_text = self.key_names.get(vk, f"0x{vk:X}")
                    if self.listening_bind in self.bind_buttons:
                        self.bind_buttons[self.listening_bind].config(text=btn_text, fg="#00e5ff")
                    self.listening_bind = None
                    time.sleep(0.15)
                    break

        # Dynamic toggle menu key
        menu_key = bool(ctypes.windll.user32.GetAsyncKeyState(self.cfg.menu_key) & 0x8000)
        if menu_key and not self.last_menu_key:
            self.menu_open = not self.menu_open
            if self.menu_open:
                self.menu_window.deiconify()
                self.menu_window.lift()
            else:
                self.menu_window.withdraw()
        self.last_menu_key = menu_key

        # Update Third-person label & checkbox
        if hasattr(self, "cb_tp"):
            self.cb_tp.set(self.cfg.thirdperson_enabled)
            if self.cfg.thirdperson_enabled:
                self.tp_status.config(text="Status: Third-Person ACTIVE", fg="#00ff00")
            else:
                self.tp_status.config(text="Status: First-Person", fg="#888888")

        # Update status header
        if self.core.connected:
            local = self.core.local_player()
            if local:
                hp = self.core.ri(local + Off.m_iHealth)
                self.status_lbl.config(text=f"[HP: {hp} | Enemies: {len(self.core.entities)}]", fg="#00ff00")
            else:
                self.status_lbl.config(text="[Not In-Game]", fg="#ffaa00")
        else:
            self.status_lbl.config(text="[Not Connected]", fg="#ff4444")

        # Dynamic exit key
        if bool(ctypes.windll.user32.GetAsyncKeyState(self.cfg.exit_key) & 0x8000):
            self.core.alive = False
            self.root.destroy()
            return

        self.root.after(30, self.poll_hotkeys)

    def render_esp(self):
        self.canvas.delete("all")
        cfg = self.cfg
        core = self.core

        if cfg.esp_enabled and core.connected:
            local = core.local_player()
            if local:
                with core.lock:
                    ents = list(core.entities)

                W, H = self.W, self.H
                snap_ox = W / 2
                snap_oy = H

                for e in ents:
                    if not e["enemy"] and cfg.esp_team_check:
                        continue

                    hs = core.w2s(e["head"], W, H)
                    fs = core.w2s(e["foot"], W, H)
                    if not hs or not fs:
                        continue

                    hx, hy = hs
                    fx, fy = fs

                    if hx < -200 or hx > W + 200:
                        continue

                    box_h = fy - hy
                    if box_h < 6 or box_h > 1200:
                        continue
                    box_w = box_h * 0.42
                    bx = hx - box_w / 2

                    col = "#ff3333" if e["enemy"] else "#33ff33"

                    # ── Corner-Bracket Bounding Box ───────────────────────────
                    if cfg.esp_box:
                        clen = max(6.0, box_w * 0.25)
                        rx, ry = bx + box_w, hy + box_h
                        # Top-left
                        self.canvas.create_line(bx, hy, bx + clen, hy, fill=col, width=2)
                        self.canvas.create_line(bx, hy, bx, hy + clen, fill=col, width=2)
                        # Top-right
                        self.canvas.create_line(rx, hy, rx - clen, hy, fill=col, width=2)
                        self.canvas.create_line(rx, hy, rx, hy + clen, fill=col, width=2)
                        # Bottom-left
                        self.canvas.create_line(bx, ry, bx + clen, ry, fill=col, width=2)
                        self.canvas.create_line(bx, ry, bx, ry - clen, fill=col, width=2)
                        # Bottom-right
                        self.canvas.create_line(rx, ry, rx - clen, ry, fill=col, width=2)
                        self.canvas.create_line(rx, ry, rx, ry - clen, fill=col, width=2)

                    # ── Health Bar ───────────────────────────────────────────
                    if cfg.esp_health:
                        hp = max(0, min(100, e["hp"]))
                        ratio = hp / 100.0
                        bar_h = box_h * ratio
                        # Background bar
                        self.canvas.create_rectangle(bx - 7, hy, bx - 3, hy + box_h, fill="#000000", outline="")
                        # Health fill (color transition)
                        hp_col = "#00ff00" if hp > 50 else ("#ffff00" if hp > 25 else "#ff0000")
                        self.canvas.create_rectangle(bx - 7, hy + box_h - bar_h, bx - 3, hy + box_h, fill=hp_col, outline="")

                    # ── Head Dot ─────────────────────────────────────────────
                    if cfg.esp_head_dot:
                        self.canvas.create_oval(hx - 3, hy - 3, hx + 3, hy + 3, fill="#ffffff", outline="")

                    # ── Snapline ─────────────────────────────────────────────
                    if cfg.esp_snaplines:
                        self.canvas.create_line(snap_ox, snap_oy, hx, hy, fill="#ffff00", width=1)

                    # ── Distance Text ────────────────────────────────────────
                    if cfg.esp_distance:
                        self.canvas.create_text(bx + box_w + 4, hy + 2, text=f"{e['dist']:.0f}m", fill="#ffffff", anchor="w", font=("Consolas", 9, "bold"))

                    # ── Scoped Tag ───────────────────────────────────────────
                    if e.get("scoped"):
                        self.canvas.create_text(bx, hy - 10, text="[SCOPED]", fill="#ffcc00", anchor="w", font=("Consolas", 8, "bold"))

        # ~100Hz render update
        self.root.after(10, self.render_esp)

    def run(self):
        self.root.mainloop()


def main():
    print("=" * 60)
    print("  meow.cc — CS2/CSGO All-In-One Cheat")
    print("  GUI: Native Windows Transparent Overlay (100% Zero-Lag)")
    print("  INSERT = Toggle Menu  |  END = Exit")
    print("=" * 60)

    cfg = Config()
    core = CheatCore(cfg)

    if not core.connect():
        print(f"[!] {core.status_msg}")
        print("    Make sure CS:GO / CS2 is running as Administrator,")
        print("    then run THIS script as Administrator too.")
        input("Press Enter to exit...")
        return

    print(f"[+] {core.status_msg}")

    # Load skins if enabled
    if cfg.skinchanger_enabled:
        core.load_skins()

    # Feature threads
    thread_defs = [
        ("aimbot",       thread_aimbot),
        ("rcs",          thread_rcs),
        ("triggerbot",   thread_triggerbot),
        ("bhop",         thread_bhop),
        ("glow",         thread_glow),
        ("chams",        thread_chams),
        ("no_flash",     thread_no_flash),
        ("fov",          thread_fov),
        ("skinchanger",  thread_skinchanger),
        ("thirdperson",  thread_thirdperson),
        ("snapshot",     thread_entity_snapshot),
    ]

    threads = []
    for name, fn in thread_defs:
        t = threading.Thread(target=fn, args=(core,), daemon=True, name=name)
        t.start()
        threads.append(t)

    print(f"[+] Started {len(threads)} feature threads")

    app = NativeOverlayApp(core)
    print("[+] Native Overlay running — Press INSERT to toggle Menu")

    try:
        app.run()
    except Exception:
        traceback.print_exc()
    finally:
        core.alive = False
        print("[*] Exited cleanly")


if __name__ == "__main__":
    main()


