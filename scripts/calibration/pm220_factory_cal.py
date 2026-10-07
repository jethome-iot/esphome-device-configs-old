#!/usr/bin/env python3
"""DRAFT: factory calibration runner for the JXD-PM220 metering board (BL0906, 6 channels).

Status: a draft for review, not used in production. It drives the factory firmware build that
doc/pm220-calibration.md proposes (the ``cal_*`` API actions), and that build does not exist
yet, so against a real device this file is a sketch of the protocol. ``--simulate`` runs the
whole procedure against a simulated board and a perfect reference source, which checks the
arithmetic, the record layout and the order of the steps end to end.

Per board it:
  1. reads the metering board identity (JEEFS board header in the EEPROM at 0x56);
  2. puts the firmware in raw mode (design coefficients, creep thresholds off, PHASE
     registers at their defaults) and measures a no-load point and a gain point;
  3. with --phase, measures PF 0.5 inductive and derives each channel's phase error;
  4. builds meter.cal (record v1, the layout of components/meter_calibration/README.md in
     esphome-device-configs, branch feature/meter-cal-record), writes it without the
     line-check flag, reloads it and measures the acceptance points through the firmware's
     own conversion;
  5. when every point passes, rewrites the record with the line-check flag and the worst
     errors, and saves a JSON report.

Why the native API (aioesphomeapi) and not the web server REST API: API actions take typed
arrays and answer with JSON, so one call carries a whole measurement or a whole record and
the device can refuse it with a reason; aioesphomeapi already ships in the project's .venv as
an ESPHome dependency.

Usage:
  .venv/bin/python scripts/calibration/pm220_factory_cal.py --simulate
  .venv/bin/python scripts/calibration/pm220_factory_cal.py --host 192.168.1.50 \\
      --station-id ST1 --instrument-id REF-0001 --operator 7 --ambient 23.5 --phase
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import random
import struct
import sys
import time
import zlib
from dataclasses import asdict, dataclass, field
from pathlib import Path

CHANNELS = 6

# ---------------------------------------------------------------------------------------------
# Design values of JXD-D3-PM1-6 rev 1.1.0 (BL0906 datasheet V1.02 section 3.4.1, app note
# V1.02 "关于电参数转换"): 4 x 20k into a 1:1 current-type VT with a 100 ohm burden gives
# 1.25 mV per volt; a 2000:1 CT into 5.1 + 5.1 ohm gives 5.1 mV per primary ampere.
VREF = 1.097
KV0 = 13162 * 1.25 / VREF  # LSB per volt, ~14997.7
KI0 = 12875 * 5.1 / VREF  # LSB per primary ampere at 2000:1, ~59856.4
KP0 = 40.4125 * 5.1 * 1.25 / VREF**2  # LSB per watt, ~214.08
C_WATT = 40.4125 / (13162 * 12875)  # WATT = C_WATT * V_RMS * I_RMS * cos(phi), in LSB
CF_WH_X_KP = (
    4194304 * 0.032768 * 16 / (3600 * 16)
)  # Wh per CF pulse times Kp, CFDIV = 0x10
CT_RATIO = 2000
PHASE_LSB_DEG = 0.0045  # PHASE[n] step: 250 ns at 50 Hz
PHASE_DEFAULT = 0x10
PHASE_MAX = 0x7F
RMS_CREEP_LSB = 0x200 * 2  # datasheet 3.4.5: the register is doubled before the compare
WA_CREEP_LSB = 0x04C * 2  # app note: WATT = 2 * WA_CREEP

# Sanity window for a measured coefficient against the design value. Parts are 1 %, the VT
# ratio error is up to -0.6 %, the chip gain spread is under 1 %: 5 % means a fault.
DESIGN_WINDOW = 0.05

ZERO_PSK = base64.b64encode(bytes(32)).decode()  # the key a device without one accepts

# ---------------------------------------------------------------------------------------------
# meter.cal v1 and JEEFS, byte for byte as esphome-device-configs reads them.
BOARD_MODEL = "JXD-D3-PM1-6"
BOARD_REVISION = "1.1.0"
RECORD_SIZE = 256
RECORD_MAGIC = b"JHMCAL\0\0"
CHIP_BL0906 = 2
FLAG_GAIN_UI = 1 << 0
FLAG_OFFSET_UI = 1 << 1
FLAG_OFFSET_PQ = 1 << 2
FLAG_GAIN_ENERGY = 1 << 3
FLAG_PHASE = 1 << 4
FLAG_LINE_VERIFIED = 1 << 5
HEAD_FMT = "<8sBBBB32s8s32sIIHBBhH12s16s"  # offsets 0-127
BODY_FMT = "<I6I6I6h2s6H6h6h10s"  # offsets 128-239, the BL0906 body
TAIL_FMT = "<qI"  # timestamp, operator_code; crc32 follows
BOARD_HEADER_SIZE = 256
FILE_HEADER_FMT = "<16sHIH"  # name, data_size, crc32, next; header_crc32 follows
FILE_HEADER_SIZE = 28
FILE_HEADER_ADDR = BOARD_HEADER_SIZE
RECORD_ADDR = FILE_HEADER_ADDR + FILE_HEADER_SIZE  # 284
IMAGE_USED = RECORD_ADDR + RECORD_SIZE  # 540

assert struct.calcsize(HEAD_FMT) == 128
assert struct.calcsize(BODY_FMT) == 112
assert struct.calcsize(TAIL_FMT) == 12


def crc32(data: bytes) -> int:
    return zlib.crc32(data) & 0xFFFFFFFF


def text(value: str, size: int) -> bytes:
    raw = value.encode("ascii")
    if len(raw) > size:
        raise ValueError(f"{value!r} does not fit {size} bytes")
    return raw  # struct pads with NUL


def untext(raw: bytes) -> str:
    return raw.split(b"\0", 1)[0].decode("ascii", "replace")


@dataclass
class Coefficients:
    """What the firmware converts raw registers with: the factory layer of the doc."""

    kv: float = KV0
    ki: list[float] = field(default_factory=lambda: [KI0] * CHANNELS)
    kp: list[float] = field(default_factory=lambda: [KP0] * CHANNELS)
    i_off: list[float] = field(
        default_factory=lambda: [0.0] * CHANNELS
    )  # A, in squares
    p_off: list[float] = field(default_factory=lambda: [0.0] * CHANNELS)  # W
    phase_mdeg: list[int] = field(default_factory=lambda: [0] * CHANNELS)


def build_record(
    *,
    serial: str,
    coeffs: Coefficients,
    ref_volts: float,
    ref_amps: float,
    flags: int,
    err_worst: list[float],
    station: str,
    instrument: str,
    operator: int,
    ambient_c: float,
    timestamp: int,
    line_hz: int = 50,
) -> bytes:
    head = struct.pack(
        HEAD_FMT,
        RECORD_MAGIC,
        1,  # record_version
        0,  # signature_version
        CHIP_BL0906,
        CHANNELS,
        text(BOARD_MODEL, 32),
        text(BOARD_REVISION, 8),
        text(serial, 32),
        round(ref_volts * 1000),
        round(ref_amps / CT_RATIO * 1e6),  # secondary current, uA
        CT_RATIO,
        line_hz,
        0,  # pga_code: x1 on every channel
        round(ambient_c * 10),
        flags,
        text(station, 12),
        text(instrument, 16),
    )
    body = struct.pack(
        BODY_FMT,
        round(coeffs.kv * 1000),
        *(round(k * 1000) for k in coeffs.ki),
        *(round(k * 1e6) for k in coeffs.kp),
        *(clamp_i16(m) for m in coeffs.phase_mdeg),
        bytes(2),
        *(min(0xFFFF, round(a * 1000)) for a in coeffs.i_off),
        *(clamp_i16(round(w * 100)) for w in coeffs.p_off),
        *(clamp_i16(round(e * 100)) for e in err_worst),
        bytes(10),
    )
    data = head + body + struct.pack(TAIL_FMT, timestamp, operator)
    return data + struct.pack("<I", crc32(data))


def clamp_i16(value: float) -> int:
    return max(-32768, min(32767, int(value)))


def parse_record(raw: bytes) -> tuple[dict, Coefficients]:
    """Raises ValueError like the firmware's check_record() would refuse the record."""
    if len(raw) != RECORD_SIZE or raw[:8] != RECORD_MAGIC:
        raise ValueError("not a meter.cal v1 record")
    if raw[8] != 1:
        raise ValueError("unknown record version")
    if crc32(raw[:252]) != struct.unpack_from("<I", raw, 252)[0]:
        raise ValueError("record CRC32 mismatch")
    h = struct.unpack_from(HEAD_FMT, raw, 0)
    b = struct.unpack_from(BODY_FMT, raw, 128)
    ts, op = struct.unpack_from(TAIL_FMT, raw, 240)
    meta = {
        "chip_type": h[3],
        "channel_count": h[4],
        "board_model": untext(h[5]),
        "board_revision": untext(h[6]),
        "board_serial": untext(h[7]),
        "ref_voltage_mv": h[8],
        "ref_current_ua": h[9],
        "ct_nominal_ratio": h[10],
        "line_freq_hz": h[11],
        "pga_code": h[12],
        "ambient_ddeg": h[13],
        "flags": h[14],
        "station_id": untext(h[15]),
        "ref_instrument_id": untext(h[16]),
        "timestamp": ts,
        "operator_code": op,
        "crc32": f"{crc32(raw[:252]):08x}",
    }
    if raw[9] != 0:
        raise ValueError("unknown signature version")
    if meta["chip_type"] != CHIP_BL0906 or meta["channel_count"] != CHANNELS:
        raise ValueError("not a BL0906 record")
    if meta["flags"] & ~0x3F:
        raise ValueError("unknown flag bits")
    if meta["ct_nominal_ratio"] != CT_RATIO or meta["line_freq_hz"] not in (50, 60):
        raise ValueError("CT ratio or line frequency not allowed")
    if any(b[19]) or any(b[38]):
        raise ValueError("reserved bytes are not zero")
    kv, ki, kp = b[0], b[1:7], b[7:13]
    if meta["flags"] & FLAG_GAIN_UI and (kv == 0 or 0 in ki):
        raise ValueError("a calibrated gain is zero")
    if meta["flags"] & FLAG_GAIN_ENERGY and 0 in kp:
        raise ValueError("a calibrated power gain is zero")
    coeffs = Coefficients(
        kv=kv / 1000,
        ki=[k / 1000 for k in ki],
        kp=[k / 1e6 for k in kp],
        phase_mdeg=list(b[13:19]),
        i_off=[ma / 1000 for ma in b[20:26]],
        p_off=[cw / 100 for cw in b[26:32]],
    )
    meta["err_worst_pct"] = [e / 100 for e in b[32:38]]
    return meta, coeffs


def build_board_header(serial: str, timestamp: int) -> bytes:
    """JEEFS board header v4 for the metering board: board-scoped serial, no USID/CPUID/MAC."""
    data = struct.pack(
        "<8sBBBB32s32s32s32s32s6s2s64sq",
        b"JETHOME\0",
        4,  # version
        0,  # signature_version
        1,  # fs_version: JEEFS v1, a file chain follows
        0,
        text(BOARD_MODEL, 32),
        text(BOARD_REVISION, 32),
        text(serial, 32),
        b"",
        b"",
        bytes(6),
        bytes(2),
        bytes(64),
        timestamp,
    )
    assert len(data) == 252
    return data + struct.pack("<I", crc32(data))


def build_file_header(record: bytes) -> bytes:
    data = struct.pack(FILE_HEADER_FMT, b"meter.cal", len(record), crc32(record), 0)
    return data + struct.pack("<I", crc32(data))


def read_board_serial(image: bytes) -> str | None:
    """The serial in a sound v4 header, None for a blank part; raises on a damaged header."""
    if image[:8] != b"JETHOME\0":
        return None
    if image[8] != 4 or crc32(image[:252]) != struct.unpack_from("<I", image, 252)[0]:
        raise ValueError(
            "the metering board EEPROM holds a damaged or non-v4 board header"
        )
    if image[10] != 1:
        raise ValueError("the board header has no JEEFS file chain")
    return untext(image[76:108])


def evaluate_image(image: bytes, serial: str) -> tuple[str, dict | None]:
    """The status names of components/meter_calibration (only the simple layout of the doc)."""
    try:
        if read_board_serial(image) is None:
            return "missing", None
    except ValueError:
        return "corrupt", None
    fh = image[FILE_HEADER_ADDR : FILE_HEADER_ADDR + FILE_HEADER_SIZE]
    name, size, data_crc, _next = struct.unpack_from(FILE_HEADER_FMT, fh, 0)
    if fh[:1] in (b"\0", b"\xff"):
        return "missing", None
    if (
        crc32(fh[:24]) != struct.unpack_from("<I", fh, 24)[0]
        or untext(name) != "meter.cal"
    ):
        return "corrupt", None
    record = image[RECORD_ADDR : RECORD_ADDR + size]
    if size != RECORD_SIZE or crc32(record) != data_crc:
        return "corrupt", None
    try:
        meta, _ = parse_record(record)
    except ValueError:
        return "corrupt", None
    if meta["board_model"] != BOARD_MODEL or meta["board_serial"] != serial:
        return "foreign", meta
    return ("factory" if meta["flags"] & FLAG_LINE_VERIFIED else "unverified"), meta


def phase_codes(mdeg: list[int]) -> tuple[list[int], int, list[float]]:
    """PHASE[n] and PHASE[V] codes for the wanted corrections, and the corrections they give.

    A positive correction delays the current channel (it read P high at PF 0.5 lagging); a
    negative one is made by delaying the voltage channel, common to all six, and the rest
    relative to it. 127 steps of 0.0045 deg in all: whatever does not fit is clamped.
    The direction has to be confirmed on hardware (doc, "Что проверить на железе").
    """
    deg = [m / 1000 for m in mdeg]
    lead_v = max(0.0, -min(deg))
    code_v = min(PHASE_MAX, PHASE_DEFAULT + math.ceil(lead_v / PHASE_LSB_DEG))
    codes = [min(PHASE_MAX, max(0, code_v + round(d / PHASE_LSB_DEG))) for d in deg]
    return codes, code_v, [(c - code_v) * PHASE_LSB_DEG for c in codes]


# ---------------------------------------------------------------------------------------------
# What the firmware does with the coefficients (the doc's formulas), shared by the simulator.


def to_physical(raw_v: float, raw_i: list[float], raw_w: list[float], c: Coefficients):
    volts = raw_v / c.kv
    amps = [
        math.sqrt(max(0.0, (raw_i[n] / c.ki[n]) ** 2 - c.i_off[n] ** 2))
        for n in range(CHANNELS)
    ]
    # WATT reads 0 under the chip's creep threshold, and the offset must not turn that into a load
    watts = [
        0.0 if raw_w[n] == 0 else raw_w[n] / c.kp[n] - c.p_off[n]
        for n in range(CHANNELS)
    ]
    return volts, amps, watts


# ---------------------------------------------------------------------------------------------
# Measurement points. Currents are primary-equivalent at the nominal 2000:1 ratio.


@dataclass(frozen=True)
class Point:
    name: str
    volts: float
    amps: float
    pf: float = 1.0  # 0.5 = 60 deg lagging
    tol_v: float | None = None  # %, None = not checked at this point
    tol_i: float | None = None
    tol_p: float | None = None
    seconds: float = 20.0
    energy: bool = False  # also compare the CF pulse count with the reference energy
    no_load: bool = False  # expect I = 0 and P = 0 with the chip's creep thresholds


CAL_ZERO = Point("cal: no load", 230.0, 0.0)
CAL_GAIN = Point("cal: gain", 230.0, 5.0)
CAL_PHASE = Point("cal: PF 0.5L", 230.0, 5.0, pf=0.5)
CHECKS = [
    Point("V 200", 200.0, 5.0, tol_v=0.3),
    Point("V 250", 250.0, 5.0, tol_v=0.3),
    Point("I 0.25", 230.0, 0.25, tol_i=1.0, tol_p=1.0),
    Point("I 1", 230.0, 1.0, tol_i=0.5, tol_p=0.5),
    Point("I 5", 230.0, 5.0, tol_v=0.3, tol_i=0.5, tol_p=0.5),
    Point(
        "I 20 + energy", 230.0, 20.0, tol_i=0.5, tol_p=0.5, seconds=60.0, energy=True
    ),
    Point("PF 0.5L", 230.0, 5.0, pf=0.5, tol_i=0.5, tol_p=1.0),
    Point("no load", 230.0, 0.0, no_load=True),
]
ENERGY_TOL = 0.5  # %, on top of one pulse of quantisation


@dataclass
class RefValues:
    volts: float
    amps: float  # primary-equivalent
    watts: float
    pf: float


@dataclass
class Measurement:
    n: int
    raw_v: float
    raw_i: list[float]
    raw_w: list[float]
    sd_i: list[float]  # relative standard deviation, for the stability check
    cal_v: float
    cal_i: list[float]
    cal_p: list[float]
    cf_delta: list[int]
    cf_ms: int


class StationError(RuntimeError):
    """The board is rejected or the station cannot go on; the message says why."""


# ---------------------------------------------------------------------------------------------
# The device behind the factory build's API actions.


class ApiDevice:
    REQUIRED = {
        "cal_info",
        "cal_raw_mode",
        "cal_set_phase",
        "cal_measure_start",
        "cal_measure_result",
        "cal_eeprom_read",
        "cal_write",
    }

    def __init__(self, host: str, port: int, psk: str):
        from aioesphomeapi import APIClient  # in .venv as an ESPHome dependency

        self._client = APIClient(
            host, port, None, noise_psk=psk, client_info="pm220-factory-cal"
        )
        self._services: dict = {}

    async def connect(self) -> None:
        await self._client.connect(login=True)
        _, services = await self._client.list_entities_services()
        self._services = {s.name: s for s in services}
        missing = self.REQUIRED - set(self._services)
        if missing:
            raise StationError(
                f"not the PM220 factory build, no actions {sorted(missing)}"
            )

    async def close(self) -> None:
        await self._client.disconnect()

    async def _call(self, name: str, **data) -> dict:
        resp = await self._client.execute_service(
            self._services[name], data, return_response=True, timeout=15
        )
        if resp is None or not resp.success:
            raise StationError(f"{name}: {resp.error_message if resp else 'no answer'}")
        return json.loads(resp.response_data) if resp.response_data else {}

    async def info(self) -> dict:
        return await self._call("cal_info")

    async def raw_mode(self, enabled: bool) -> None:
        await self._call("cal_raw_mode", enabled=enabled)

    async def set_phase(self, mdeg: list[int]) -> None:
        await self._call("cal_set_phase", mdeg=list(mdeg))

    async def measure(self, seconds: float) -> Measurement:
        await self._call("cal_measure_start", seconds=int(math.ceil(seconds)))
        await asyncio.sleep(seconds)
        for _ in range(30):
            try:
                r = await self._call("cal_measure_result")
                break
            except StationError as err:
                if "busy" not in str(err):
                    raise
                await asyncio.sleep(1)
        else:
            raise StationError("the measurement did not finish")
        return Measurement(
            n=r["n"],
            raw_v=r["raw"]["v"],
            raw_i=r["raw"]["i"],
            raw_w=r["raw"]["w"],
            sd_i=r["rsd"]["i"],
            cal_v=r["cal"]["v"],
            cal_i=r["cal"]["i"],
            cal_p=r["cal"]["p"],
            cf_delta=r["raw"]["cf"],
            cf_ms=r["raw"]["cf_ms"],
        )

    async def eeprom_read(self, offset: int, length: int) -> bytes:
        out = b""
        while len(out) < length:
            chunk = min(128, length - len(out))
            r = await self._call(
                "cal_eeprom_read", offset=offset + len(out), length=chunk
            )
            out += bytes.fromhex(r["hex"])
        return out

    async def write(self, board_header: bytes | None, record: bytes) -> dict:
        """The firmware checks the record as production would, writes page by page, reads back."""
        return await self._call(
            "cal_write",
            board_header_hex=board_header.hex() if board_header else "",
            record_hex=record.hex(),
        )


# ---------------------------------------------------------------------------------------------
# Simulated board, firmware and reference: random but plausible part errors.


class SimDevice:
    def __init__(self, seed: int, blank: bool):
        rnd = random.Random(seed)
        self.rnd = rnd
        self.kv = KV0 * (1 + rnd.gauss(0, 0.006))
        self.ki = [KI0 * (1 + rnd.gauss(0, 0.01)) for _ in range(CHANNELS)]
        self.kp = [C_WATT * self.kv * ki * (1 + rnd.gauss(0, 0.002)) for ki in self.ki]
        self.i_noise = [rnd.uniform(0.004, 0.012) for _ in range(CHANNELS)]  # A
        self.w_noise = [rnd.gauss(0, 0.15) for _ in range(CHANNELS)]  # W
        common = rnd.uniform(0.15, 0.35)  # the VT, shared by every channel
        self.phase = [common + rnd.gauss(0, 0.04) for _ in range(CHANNELS)]  # deg
        self.source = (0.0, 0.0, 1.0)
        self.raw = False
        self.applied = [0.0] * CHANNELS
        self.coeffs = Coefficients()
        self.eeprom = bytearray(b"\xff" * 8192)
        if not blank:
            self.eeprom[:256] = build_board_header(
                "PM16-SIM-%04d" % (seed % 10000), int(time.time())
            )
        self._apply_record()

    async def connect(self) -> None:
        pass

    async def close(self) -> None:
        pass

    def _serial(self) -> str:
        return read_board_serial(bytes(self.eeprom)) or ""

    def _apply_record(self) -> None:
        status, _ = evaluate_image(bytes(self.eeprom), self._serial())
        self.status = status
        if status in ("factory", "unverified"):
            _, self.coeffs = parse_record(bytes(self.eeprom[RECORD_ADDR:IMAGE_USED]))
        else:
            self.coeffs = Coefficients()
        self.applied = (
            [0.0] * CHANNELS if self.raw else phase_codes(self.coeffs.phase_mdeg)[2]
        )

    async def info(self) -> dict:
        return {
            "board_serial": self._serial(),
            "board_model": BOARD_MODEL,
            "meter_cal": self.status,
        }

    async def raw_mode(self, enabled: bool) -> None:
        self.raw = enabled
        self._apply_record()

    async def set_phase(self, mdeg: list[int]) -> None:
        self.applied = phase_codes(mdeg)[2]

    async def measure(self, seconds: float) -> Measurement:
        volts, amps, pf = self.source
        phi = math.acos(pf)
        n = max(1, int(seconds))
        acc_v, acc_i, acc_w = 0.0, [0.0] * CHANNELS, [0.0] * CHANNELS
        sq_i = [0.0] * CHANNELS
        for _ in range(n):
            acc_v += self.kv * volts * (1 + self.rnd.gauss(0, 1e-4))
            for c in range(CHANNELS):
                i = (
                    self.ki[c]
                    * math.hypot(amps, self.i_noise[c])
                    * (1 + self.rnd.gauss(0, 2e-4))
                )
                p_true = (
                    volts
                    * amps
                    * math.cos(phi - math.radians(self.phase[c] - self.applied[c]))
                )
                w = (
                    self.kp[c]
                    * (p_true + self.w_noise[c])
                    * (1 + self.rnd.gauss(0, 2e-4))
                )
                if not self.raw:
                    i = 0.0 if i < RMS_CREEP_LSB else i
                    w = 0.0 if abs(w) < WA_CREEP_LSB else w
                acc_i[c] += i
                sq_i[c] += i * i
                acc_w[c] += w
        raw_v = acc_v / n
        raw_i = [a / n for a in acc_i]
        raw_w = [a / n for a in acc_w]
        rsd = [
            math.sqrt(max(0.0, sq_i[c] / n - raw_i[c] ** 2)) / raw_i[c]
            if raw_i[c]
            else 0.0
            for c in range(CHANNELS)
        ]
        coeffs = Coefficients() if self.raw else self.coeffs
        cal_v, cal_i, cal_p = to_physical(raw_v, raw_i, raw_w, coeffs)
        cf = [int(max(0.0, w) * seconds / (3600 * CF_WH_X_KP)) for w in raw_w]
        return Measurement(
            n, raw_v, raw_i, raw_w, rsd, cal_v, cal_i, cal_p, cf, int(seconds * 1000)
        )

    async def eeprom_read(self, offset: int, length: int) -> bytes:
        return bytes(self.eeprom[offset : offset + length])

    async def write(self, board_header: bytes | None, record: bytes) -> dict:
        parse_record(record)  # the firmware refuses what production would refuse
        if board_header:
            if self.eeprom[:8] == b"JETHOME\0":
                raise StationError("cal_write: the board already has a header")
            self.eeprom[:256] = board_header
        self.eeprom[RECORD_ADDR:IMAGE_USED] = record
        self.eeprom[FILE_HEADER_ADDR:RECORD_ADDR] = build_file_header(record)
        self._apply_record()
        return {"status": self.status, "crc32": f"{crc32(record[:252]):08x}"}


class SimReference:
    def __init__(self, device: SimDevice):
        self.device = device

    async def apply(self, point: Point, current_input: str) -> RefValues:
        self.device.source = (point.volts, point.amps, point.pf)
        return RefValues(
            point.volts, point.amps, point.volts * point.amps * point.pf, point.pf
        )

    async def off(self) -> None:
        self.device.source = (0.0, 0.0, 1.0)


class ManualReference:
    """The operator sets the source and types what the reference meter shows."""

    async def apply(self, point: Point, current_input: str) -> RefValues:
        if current_input == "secondary":
            setp = f"{point.amps / CT_RATIO * 1000:.4f} mA into every channel"
        else:
            setp = f"{point.amps:.3f} A through the station CTs"
        print(
            f"\n[{point.name}] set U = {point.volts:.1f} V, I = {setp}, PF = {point.pf:.2f} (lagging)"
        )
        line = await asyncio.to_thread(
            input, "  reference U[V] I[A or mA] P[W], or Enter to take the setpoints: "
        )
        if not line.strip():
            return RefValues(
                point.volts, point.amps, point.volts * point.amps * point.pf, point.pf
            )
        v, i, p = (float(x) for x in line.split())
        amps = i / 1000 * CT_RATIO if current_input == "secondary" else i
        return RefValues(v, amps, p, p / (v * amps) if v * amps else 1.0)

    async def off(self) -> None:
        print("\nSwitch the source off.")


# ---------------------------------------------------------------------------------------------
# The procedure.


def compute(zero: Measurement, gain: Measurement, ref: RefValues) -> Coefficients:
    c = Coefficients(kv=gain.raw_v / ref.volts)
    for n in range(CHANNELS):
        signal = math.sqrt(max(0.0, gain.raw_i[n] ** 2 - zero.raw_i[n] ** 2))
        c.ki[n] = signal / ref.amps
        c.i_off[n] = zero.raw_i[n] / c.ki[n]
        c.kp[n] = (gain.raw_w[n] - zero.raw_w[n]) / ref.watts
        c.p_off[n] = zero.raw_w[n] / c.kp[n]
    checks = [("Kv", c.kv, KV0)] + [
        (f"Ki{n + 1}", c.ki[n], KI0) for n in range(CHANNELS)
    ]
    checks += [(f"Kp{n + 1}", c.kp[n], KP0) for n in range(CHANNELS)]
    for name, value, design in checks:
        if abs(value / design - 1) > DESIGN_WINDOW:
            raise StationError(
                f"{name} = {value:.1f} is {100 * (value / design - 1):+.1f} % off design: wiring or a faulty part"
            )
    return c


def phase_from(
    zero: Measurement, meas: Measurement, ref: RefValues, c: Coefficients
) -> list[int]:
    phi = math.acos(ref.pf)
    out = []
    for n in range(CHANNELS):
        ratio = (meas.raw_w[n] - zero.raw_w[n]) / c.kp[n] / ref.watts
        delta = phi - math.acos(max(-1.0, min(1.0, ratio * math.cos(phi))))
        out.append(round(math.degrees(delta) * 1000))
    return out


def stable(m: Measurement, point: Point) -> None:
    if point.amps == 0:
        return
    worst = max(m.sd_i)
    if worst > 0.005:
        raise StationError(
            f"[{point.name}] current not stable: relative SD {100 * worst:.2f} %"
        )


def evaluate(point: Point, ref: RefValues, m: Measurement, c: Coefficients) -> dict:
    row: dict = {"point": point.name, "ref": asdict(ref), "errors": {}, "passed": True}

    def check(key: str, measured: float, reference: float, tol: float | None) -> None:
        if tol is None:
            return
        err = 100 * (measured / reference - 1)
        row["errors"][key] = round(err, 3)
        if abs(err) > tol:
            row["passed"] = False

    if point.no_load:
        bad = [
            n + 1 for n in range(CHANNELS) if m.cal_i[n] != 0 or abs(m.cal_p[n]) > 0.05
        ]
        row["errors"]["no_load_channels_reading"] = bad
        row["passed"] = not bad
        return row
    check("V", m.cal_v, ref.volts, point.tol_v)
    for n in range(CHANNELS):
        check(f"I{n + 1}", m.cal_i[n], ref.amps, point.tol_i)
        check(f"P{n + 1}", m.cal_p[n], ref.watts, point.tol_p)
        if point.energy and m.cf_ms:
            e_dev = m.cf_delta[n] * CF_WH_X_KP / c.kp[n]
            e_ref = ref.watts * m.cf_ms / 3.6e6
            pulse = CF_WH_X_KP / c.kp[n]
            check(f"E{n + 1}", e_dev, e_ref, ENERGY_TOL + 100 * pulse / e_ref)
    return row


async def run(dev, ref, opts) -> dict:
    report: dict = {
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "station": opts.station_id,
    }
    info = await dev.info()
    report["device"] = info
    serial = info.get("board_serial") or ""
    header = None
    if not serial:
        if not opts.board_serial:
            raise StationError(
                "the metering board EEPROM has no board header: pass --board-serial"
            )
        serial = opts.board_serial
        header = build_board_header(serial, int(time.time()))
    report["board_serial"] = serial
    print(f"Board {BOARD_MODEL} {serial}, meter.cal before: {info.get('meter_cal')}")

    await dev.raw_mode(True)
    await dev.set_phase([0] * CHANNELS)
    if opts.warmup:
        await ref.apply(CAL_GAIN, opts.current_input)
        print(f"Warming up for {opts.warmup} s")
        await asyncio.sleep(opts.warmup)

    zero_ref = await ref.apply(CAL_ZERO, opts.current_input)
    zero = await dev.measure(CAL_ZERO.seconds)
    gain_ref = await ref.apply(CAL_GAIN, opts.current_input)
    gain = await dev.measure(CAL_GAIN.seconds)
    stable(gain, CAL_GAIN)
    coeffs = compute(zero, gain, gain_ref)
    flags = FLAG_GAIN_UI | FLAG_OFFSET_UI | FLAG_OFFSET_PQ | FLAG_GAIN_ENERGY
    if opts.phase:
        ph_ref = await ref.apply(CAL_PHASE, opts.current_input)
        ph = await dev.measure(CAL_PHASE.seconds)
        stable(ph, CAL_PHASE)
        coeffs.phase_mdeg = phase_from(zero, ph, ph_ref, coeffs)
        _, _, applied = phase_codes(coeffs.phase_mdeg)
        if any(
            abs(a - m / 1000) > PHASE_LSB_DEG
            for a, m in zip(applied, coeffs.phase_mdeg)
        ):
            print(
                "  warning: a phase correction is beyond the PHASE register range and is clamped"
            )
        flags |= FLAG_PHASE
    report["raw"] = {
        "zero": asdict(zero),
        "gain": asdict(gain),
        "zero_ref": asdict(zero_ref),
    }
    report["coefficients"] = asdict(coeffs)

    def record(flags_: int, err_worst: list[float]) -> bytes:
        return build_record(
            serial=serial,
            coeffs=coeffs,
            ref_volts=gain_ref.volts,
            ref_amps=gain_ref.amps,
            flags=flags_,
            err_worst=err_worst,
            station=opts.station_id,
            instrument=opts.instrument_id,
            operator=opts.operator,
            ambient_c=opts.ambient,
            timestamp=int(time.time()),
        )

    answer = await dev.write(header, record(flags, [0.0] * CHANNELS))
    if answer.get("status") != "unverified":
        raise StationError(f"the device does not take the record: {answer}")
    await dev.raw_mode(False)  # from here on the production conversion with the record

    rows = []
    for point in CHECKS:
        point_ref = await ref.apply(point, opts.current_input)
        m = await dev.measure(point.seconds)
        stable(m, point)
        rows.append(evaluate(point, point_ref, m, coeffs))
    await ref.off()
    report["checks"] = rows
    passed = all(r["passed"] for r in rows)
    worst = [0.0] * CHANNELS
    for r in rows:
        for key, err in r["errors"].items():
            if key[:1] in "IP" and key[1:].isdigit():
                n = int(key[1:]) - 1
                worst[n] = max(worst[n], abs(err))
    report["err_worst_pct"] = worst
    if passed:
        final = record(flags | FLAG_LINE_VERIFIED, worst)
        answer = await dev.write(None, final)
        if answer.get("status") != "factory":
            raise StationError(
                f"the verified record does not read back as factory: {answer}"
            )
        image = await dev.eeprom_read(0, IMAGE_USED)
        status, meta = evaluate_image(image, serial)
        if status != "factory":
            raise StationError(f"the EEPROM image reads back as {status}")
        report["record_hex"] = final.hex()
        report["record"] = meta
    report["passed"] = passed
    return report


def print_summary(report: dict) -> None:
    c = report.get("coefficients", {})
    if c:
        print("\nCoefficients (design ratio):")
        print(f"  Kv {c['kv']:.1f} ({c['kv'] / KV0:.4f})")
        for n in range(CHANNELS):
            print(
                f"  ch{n + 1}: Ki {c['ki'][n]:.1f} ({c['ki'][n] / KI0:.4f})  Kp {c['kp'][n]:.3f} ({c['kp'][n] / KP0:.4f})"
                f"  Ioff {1000 * c['i_off'][n]:.1f} mA  Poff {c['p_off'][n]:+.2f} W  phase {c['phase_mdeg'][n]} mdeg"
            )
    print("\nAcceptance:")
    for row in report.get("checks", []):
        errs = ", ".join(
            f"{k} {v:+.2f}%" if isinstance(v, float) else f"{k} {v}"
            for k, v in row["errors"].items()
        )
        print(f"  {'PASS' if row['passed'] else 'FAIL'} {row['point']:<14} {errs}")
    print(
        f"\nBoard {report.get('board_serial')}: {'PASSED' if report.get('passed') else 'REJECTED'}"
    )


async def amain(opts) -> int:
    if opts.simulate:
        dev = SimDevice(opts.seed, blank=opts.sim_blank)
        ref = SimReference(dev)
        opts.warmup = 0
        if opts.sim_blank and not opts.board_serial:
            opts.board_serial = "PM16-SIM-NEW1"
    else:
        dev = ApiDevice(opts.host, opts.port, opts.psk)
        ref = ManualReference()
    await dev.connect()
    try:
        report = await run(dev, ref, opts)
    except StationError as err:
        print(f"\nREJECTED: {err}", file=sys.stderr)
        return 2
    finally:
        await dev.close()
    print_summary(report)
    out = Path(opts.out)
    out.mkdir(parents=True, exist_ok=True)
    name = f"pm220-{report['board_serial']}-{time.strftime('%Y%m%dT%H%M%S')}.json"
    (out / name).write_text(json.dumps(report, indent=2, ensure_ascii=False))
    print(f"Report: {out / name}")
    return 0 if report["passed"] else 1


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--host", help="the device running the PM220 factory build")
    p.add_argument("--port", type=int, default=6053)
    p.add_argument(
        "--psk",
        default=ZERO_PSK,
        help="API noise key, base64; default: the all-zero key",
    )
    p.add_argument("--station-id", default="ST-DRAFT")
    p.add_argument("--instrument-id", default="REF-UNKNOWN")
    p.add_argument("--operator", type=int, default=0)
    p.add_argument(
        "--ambient", type=float, default=23.0, help="ambient temperature, deg C"
    )
    p.add_argument(
        "--board-serial",
        help="write a JEEFS v4 header with this serial on a blank part",
    )
    p.add_argument(
        "--current-input",
        choices=["primary", "secondary"],
        default="primary",
        help="primary: station CTs on a primary loop; secondary: current injected into the CT inputs",
    )
    p.add_argument(
        "--phase", action="store_true", help="calibrate phase at PF 0.5 lagging"
    )
    p.add_argument(
        "--warmup",
        type=int,
        default=120,
        help="seconds at the gain point before measuring",
    )
    p.add_argument("--out", default="calibration-reports")
    p.add_argument(
        "--simulate", action="store_true", help="simulated board and perfect reference"
    )
    p.add_argument(
        "--sim-blank",
        action="store_true",
        help="simulate a metering board with a blank EEPROM",
    )
    p.add_argument("--seed", type=int, default=1)
    opts = p.parse_args()
    if not opts.simulate and not opts.host:
        p.error("--host is required without --simulate")
    return asyncio.run(amain(opts))


if __name__ == "__main__":
    sys.exit(main())
