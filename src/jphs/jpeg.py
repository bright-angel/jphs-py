"""JPEG reading/writing for the jphs port.

The reader targets the subset of JPEG needed by jphs covers: baseline and
progressive Huffman, sequential and progressive arithmetic coding, arbitrary
sampling factors and restart intervals.  It returns quantized DCT
coefficients exactly as libjpeg's ``read_coefficients`` would, including the
padding blocks the DCT traversal never touches.

The writer reproduces libjpeg 8a's transcoding path
(``jpeg_copy_critical_parameters`` + ``optimize_coding = TRUE``) byte for
byte: JFIF/Adobe markers, DQT/DHT ordering, optimal Huffman tables, dummy
edge blocks and entropy bit packing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ._tables import ARITH_QE, NATURAL_ORDER

__all__ = ["JpegError", "Component", "JpegImage", "parse_jpeg", "encode_jpeg"]


class JpegError(Exception):
    """Raised when a JPEG cannot be parsed or an unsupported feature is hit."""


M_SOF0 = 0xC0
M_SOF1 = 0xC1
M_SOF2 = 0xC2
M_SOF9 = 0xC9
M_SOF10 = 0xCA
M_DHT = 0xC4
M_DAC = 0xCC
M_SOI = 0xD8
M_EOI = 0xD9
M_SOS = 0xDA
M_DQT = 0xDB
M_DRI = 0xDD
M_APP0 = 0xE0
M_APP14 = 0xEE

JCS_GRAYSCALE = "GRAYSCALE"
JCS_RGB = "RGB"
JCS_YCbCr = "YCbCr"
JCS_CMYK = "CMYK"
JCS_YCCK = "YCCK"
JCS_UNKNOWN = "UNKNOWN"

_TAIL1 = 12000
_TAIL2 = 1200
_TAIL3 = 120


def _ceil_div(a: int, b: int) -> int:
    return -(-a // b)


def _round_up(a: int, b: int) -> int:
    return _ceil_div(a, b) * b


@dataclass
class Component:
    component_id: int
    h_samp: int
    v_samp: int
    quant_tbl_no: int
    width_in_blocks: int = 0
    height_in_blocks: int = 0
    # One flat list per block row: width_in_blocks * 64 coefficients, padded
    # out to a multiple of h_samp like libjpeg's virtual arrays.
    rows: list[list[int]] = field(default_factory=list)
    dc_tbl_no: int = 0
    ac_tbl_no: int = 0
    last_col_width: int = 0
    last_row_height: int = 0

    def get_coef(self, row: int, index: int) -> int:
        return self.rows[row][index]

    def put_coef(self, row: int, index: int, value: int) -> None:
        self.rows[row][index] = value


@dataclass
class JpegImage:
    width: int
    height: int
    precision: int
    progressive: bool
    arithmetic: bool
    baseline: bool
    components: list[Component]
    max_h_samp: int
    max_v_samp: int
    quant_tables: dict[int, list[int]]
    colorspace: str
    saw_jfif: bool
    jfif_major: int
    jfif_minor: int
    density_unit: int
    x_density: int
    y_density: int
    saw_adobe: bool
    adobe_transform: int


# ---------------------------------------------------------------------------
# Huffman tables
# ---------------------------------------------------------------------------


@dataclass
class _HuffSpec:
    bits: list[int]  # index 1..16
    values: list[int]


class _HuffDecode:
    __slots__ = ("bits", "values", "maxcode", "valoffset", "look_nbits", "look_sym")

    def __init__(self, spec: _HuffSpec) -> None:
        self.bits = spec.bits
        self.values = spec.values

        huffsize: list[int] = []
        for length in range(1, 17):
            huffsize.extend([length] * spec.bits[length])
        huffcode: list[int] = []
        code = 0
        si = huffsize[0] if huffsize else 0
        p = 0
        while p < len(huffsize):
            while p < len(huffsize) and huffsize[p] == si:
                huffcode.append(code)
                code += 1
                p += 1
            code <<= 1
            si += 1

        self.maxcode = [-1] * 18
        self.valoffset = [0] * 18
        p = 0
        for length in range(1, 17):
            if spec.bits[length]:
                self.valoffset[length] = p - huffcode[p]
                p += spec.bits[length]
                self.maxcode[length] = huffcode[p - 1]
        self.maxcode[17] = 0xFFFFF

        self.look_nbits = [0] * 256
        self.look_sym = [0] * 256
        p = 0
        for length in range(1, 9):
            for _ in range(spec.bits[length]):
                look = huffcode[p] << (8 - length)
                for _ in range(1 << (8 - length)):
                    self.look_nbits[look] = length
                    self.look_sym[look] = spec.values[p]
                    look += 1
                p += 1


class _BitReader:
    """MSB-first bit reader over one entropy-coded segment."""

    __slots__ = ("data", "pos", "buf", "n")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.buf = 0
        self.n = 0

    def _fill(self, need: int) -> None:
        while self.n < need:
            if self.pos < len(self.data):
                self.buf = (self.buf << 8) | self.data[self.pos]
                self.pos += 1
            else:
                self.buf <<= 8
            self.n += 8

    def peek(self, count: int) -> int:
        self._fill(count)
        return (self.buf >> (self.n - count)) & ((1 << count) - 1)

    def drop(self, count: int) -> None:
        self.n -= count
        if self.n:
            self.buf &= (1 << self.n) - 1
        else:
            self.buf = 0

    def get_bits(self, count: int) -> int:
        if count == 0:
            return 0
        value = self.peek(count)
        self.drop(count)
        return value


def _huff_decode(reader: _BitReader, table: _HuffDecode) -> int:
    look = reader.peek(8)
    nbits = table.look_nbits[look]
    if nbits:
        reader.drop(nbits)
        return table.look_sym[look]
    code = reader.get_bits(9)
    length = 9
    while code > table.maxcode[length]:
        code = (code << 1) | reader.get_bits(1)
        length += 1
        if length > 16:
            return 0
    return table.values[code + table.valoffset[length]]


def _extend(value: int, size: int) -> int:
    if value < (1 << (size - 1)):
        return value - (1 << size) + 1
    return value


class _ArithDecoder:
    """Arithmetic entropy decoder, a direct port of ``jdarith.c``."""

    __slots__ = ("data", "pos", "c", "a", "ct")

    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.c = 0
        self.a = 0
        self.ct = -16

    def _byte(self) -> int:
        if self.pos < len(self.data):
            value = self.data[self.pos]
            self.pos += 1
            return value
        # Arithmetic coding pads with zero data at the end of a segment.
        return 0

    def decode(self, stats: list[int], index: int) -> int:
        while self.a < 0x8000:
            self.ct -= 1
            if self.ct < 0:
                self.c = (self.c << 8) | self._byte()
                self.ct += 8
                if self.ct < 0:
                    self.ct += 1
                    if self.ct == 0:
                        self.a = 0x8000
            self.a <<= 1

        sv = stats[index]
        qe = ARITH_QE[sv & 0x7F]
        nl = qe & 0xFF
        qe >>= 8
        nm = qe & 0xFF
        qe >>= 8

        temp = self.a - qe
        self.a = temp
        temp <<= self.ct
        if self.c >= temp:
            self.c -= temp
            if self.a < qe:
                self.a = qe
                stats[index] = (sv & 0x80) ^ nm
            else:
                self.a = qe
                stats[index] = (sv & 0x80) ^ nl
                sv ^= 0x80
        elif self.a < 0x8000:
            if self.a < qe:
                stats[index] = (sv & 0x80) ^ nl
                sv ^= 0x80
            else:
                stats[index] = (sv & 0x80) ^ nm
        return sv >> 7


# ---------------------------------------------------------------------------
# Parser / decoder
# ---------------------------------------------------------------------------


class _Parser:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.pos = 0
        self.width = 0
        self.height = 0
        self.max_h_samp = 1
        self.max_v_samp = 1
        self.precision = 8
        self.progressive = False
        self.arithmetic = False
        self.baseline = False
        self.components: list[Component] = []
        self.quant: dict[int, list[int]] = {}
        self.dc_specs: dict[int, _HuffSpec] = {}
        self.ac_specs: dict[int, _HuffSpec] = {}
        self.arith_dc_l = [0] * 16
        self.arith_dc_u = [1] * 16
        self.arith_ac_k = [5] * 16
        self._arith_fixed_bin = [113]
        self.restart_interval = 0
        self.saw_jfif = False
        self.jfif_major = 1
        self.jfif_minor = 1
        self.density_unit = 0
        self.x_density = 1
        self.y_density = 1
        self.saw_adobe = False
        self.adobe_transform = 0
        self.colorspace = JCS_UNKNOWN
        self._frozen_colorspace: str | None = None
        self.saw_sof = False

    # -- helpers ---------------------------------------------------------

    def _u8(self) -> int:
        value = self.data[self.pos]
        self.pos += 1
        return value

    def _u16(self) -> int:
        value = (self.data[self.pos] << 8) | self.data[self.pos + 1]
        self.pos += 2
        return value

    def _need(self, count: int) -> None:
        if self.pos + count > len(self.data):
            raise JpegError("Premature end of JPEG file")

    # -- marker segments -------------------------------------------------

    def parse(self) -> JpegImage:
        data = self.data
        if len(data) < 2 or data[0] != 0xFF or data[1] != M_SOI:
            raise JpegError("Not a JPEG file: missing SOI marker")
        self.pos = 2

        while self.pos < len(data):
            if data[self.pos] != 0xFF:
                raise JpegError("Bogus marker length")
            while self.pos < len(data) and data[self.pos] == 0xFF:
                self.pos += 1
            if self.pos >= len(data):
                break
            marker = data[self.pos]
            self.pos += 1

            if marker == M_EOI:
                break
            if marker in (M_SOI, 0x01) or 0xD0 <= marker <= 0xD7:
                continue

            self._need(2)
            length = self._u16()
            if length < 2 or self.pos + length - 2 > len(data):
                raise JpegError("Bogus marker length")
            end = self.pos + length - 2

            if marker in (M_SOF0, M_SOF1, M_SOF2, M_SOF9, M_SOF10):
                self._parse_sof(marker, end)
            elif marker == M_DQT:
                self._parse_dqt(end)
            elif marker == M_DHT:
                self._parse_dht(end)
            elif marker == M_DAC:
                self._parse_dac(end)
            elif marker == M_DRI:
                self.restart_interval = self._u16()
            elif marker == M_APP0:
                self._parse_app0(end)
            elif marker == M_APP14:
                self._parse_app14(end)
            elif marker == M_SOS:
                self._parse_sos(end)
                continue
            self.pos = end

        return self._finish()

    def _parse_sof(self, marker: int, end: int) -> None:
        if self.saw_sof:
            raise JpegError("Duplicate SOF marker")
        self.saw_sof = True
        self.baseline = marker == M_SOF0
        self.progressive = marker in (M_SOF2, M_SOF10)
        self.arithmetic = marker in (M_SOF9, M_SOF10)
        self.precision = self._u8()
        self.height = self._u16()
        self.width = self._u16()
        count = self._u8()
        if self.height <= 0 or self.width <= 0 or count <= 0:
            raise JpegError("Empty JPEG image (DNL not supported)")
        if self.pos + count * 3 != end:
            raise JpegError("Bogus SOF marker length")
        comps: list[Component] = []
        for _ in range(count):
            cid = self._u8()
            samp = self._u8()
            qno = self._u8()
            comps.append(Component(cid, samp >> 4, samp & 15, qno))
        self.components = comps
        max_h = max(c.h_samp for c in comps)
        max_v = max(c.v_samp for c in comps)
        if any(not 1 <= c.h_samp <= 4 or not 1 <= c.v_samp <= 4 for c in comps):
            raise JpegError("Bogus sampling factors")
        self.max_h_samp = max_h
        self.max_v_samp = max_v
        for comp in comps:
            comp.width_in_blocks = _ceil_div(self.width * comp.h_samp, max_h * 8)
            comp.height_in_blocks = _ceil_div(self.height * comp.v_samp, max_v * 8)
            padded_w = _round_up(comp.width_in_blocks, comp.h_samp)
            padded_h = _round_up(comp.height_in_blocks, comp.v_samp)
            comp.rows = [[0] * (padded_w * 64) for _ in range(padded_h)]

    def _parse_dqt(self, end: int) -> None:
        while self.pos < end:
            pq_tq = self._u8()
            pq = pq_tq >> 4
            tq = pq_tq & 15
            table = [0] * 64
            for i in range(64):
                if pq:
                    value = self._u16()
                else:
                    value = self._u8()
                table[NATURAL_ORDER[i]] = value
            if pq:
                # Keep a marker for the encoder's 16-bit check.
                table = [v for v in table]
                self.quant[tq] = table
                setattr(self, f"_q16_{tq}", True)
            else:
                self.quant[tq] = table

    def _parse_dht(self, end: int) -> None:
        while self.pos < end:
            tc_th = self._u8()
            tc = tc_th >> 4
            th = tc_th & 15
            bits = [0] * 17
            for i in range(1, 17):
                bits[i] = self._u8()
            nvals = sum(bits)
            if self.pos + nvals > end:
                raise JpegError("Bogus DHT marker length")
            values = list(self.data[self.pos : self.pos + nvals])
            self.pos += nvals
            spec = _HuffSpec(bits, values)
            if tc == 0:
                self.dc_specs[th] = spec
            else:
                self.ac_specs[th] = spec

    def _parse_dac(self, end: int) -> None:
        while self.pos < end:
            index = self._u8()
            value = self._u8()
            if index >= 32:
                raise JpegError("Bogus DAC index")
            if index >= 16:
                self.arith_ac_k[index - 16] = value
            else:
                self.arith_dc_l[index] = value & 15
                self.arith_dc_u[index] = value >> 4
                if self.arith_dc_l[index] > self.arith_dc_u[index]:
                    raise JpegError("Bogus DAC value")

    def _parse_app0(self, end: int) -> None:
        if end - self.pos >= 14 and self.data[self.pos : self.pos + 5] == b"JFIF\x00":
            base = self.pos + 5
            self.saw_jfif = True
            self.jfif_major = self.data[base]
            self.jfif_minor = self.data[base + 1]
            self.density_unit = self.data[base + 2]
            self.x_density = (self.data[base + 3] << 8) | self.data[base + 4]
            self.y_density = (self.data[base + 5] << 8) | self.data[base + 6]

    def _parse_app14(self, end: int) -> None:
        if end - self.pos >= 12 and self.data[self.pos : self.pos + 5] == b"Adobe":
            self.saw_adobe = True
            self.adobe_transform = self.data[self.pos + 11]

    def _colorspace(self) -> str:
        if len(self.components) == 1:
            return JCS_GRAYSCALE
        if len(self.components) == 3:
            if self.saw_jfif:
                return JCS_YCbCr
            if self.saw_adobe:
                if self.adobe_transform == 0:
                    return JCS_RGB
                return JCS_YCbCr
            ids = [c.component_id for c in self.components]
            if ids == [1, 2, 3]:
                return JCS_YCbCr
            if ids == [82, 71, 66]:
                return JCS_RGB
            return JCS_YCbCr
        if len(self.components) == 4:
            if self.saw_adobe:
                if self.adobe_transform == 0:
                    return JCS_CMYK
                return JCS_YCCK
            return JCS_CMYK
        return JCS_UNKNOWN

    # -- scans -----------------------------------------------------------

    def _parse_sos(self, end: int) -> None:
        if not self.saw_sof:
            raise JpegError("SOS marker before SOF")
        count = self._u8()
        if count <= 0 or self.pos + count * 2 + 3 != end:
            raise JpegError("Bogus SOS marker length")
        scan: list[tuple[int, int, int]] = []  # (component index, dc, ac)
        for _ in range(count):
            cid = self._u8()
            tables = self._u8()
            index = next(
                (i for i, c in enumerate(self.components) if c.component_id == cid),
                None,
            )
            if index is None:
                raise JpegError("Invalid component ID in SOS")
            scan.append((index, tables >> 4, tables & 15))
        ss = self._u8()
        se = self._u8()
        ahal = self._u8()
        ah = ahal >> 4
        al = ahal & 15

        if self._frozen_colorspace is None:
            self._frozen_colorspace = self._colorspace()
        self.colorspace = self._frozen_colorspace

        segments, self.pos = _read_scan_segments(self.data, self.pos)
        if self.arithmetic:
            self._decode_scan_arith(scan, ss, se, ah, al, segments)
        else:
            self._decode_scan(scan, ss, se, ah, al, segments)

    def _decode_scan(
        self,
        scan: list[tuple[int, int, int]],
        ss: int,
        se: int,
        ah: int,
        al: int,
        segments: list[bytes],
    ) -> None:
        comps = self.components
        nscan = len(scan)
        if nscan == 1:
            comp = comps[scan[0][0]]
            mcus_per_row = comp.width_in_blocks
            mcu_rows = comp.height_in_blocks
        else:
            mcus_per_row = _ceil_div(self.width, self.max_h_samp * 8)
            mcu_rows = _ceil_div(self.height, self.max_v_samp * 8)

        if self.progressive:
            need_dc = ss == 0 and ah == 0
            need_ac = ss > 0
            limit = 63
        else:
            limit = 63 if self.baseline else se
            need_dc = True
            need_ac = limit > 0

        dc_tables = [
            self._dc_decode(scan[i][1]) if need_dc else None for i in range(nscan)
        ]
        ac_tables = [
            self._ac_decode(scan[i][2]) if need_ac else None for i in range(nscan)
        ]
        preds = [0] * nscan
        eobrun = 0
        restart_interval = self.restart_interval
        restarts_to_go = restart_interval
        seg_index = 0
        reader = _BitReader(segments[0] if segments else b"")

        # Progressive parameters.
        al_shift = 1 << al
        p1 = al_shift
        m1 = -al_shift

        for irow in range(mcu_rows):
            for mcol in range(mcus_per_row):
                if restart_interval:
                    if restarts_to_go == 0:
                        seg_index += 1
                        reader = _BitReader(
                            segments[seg_index] if seg_index < len(segments) else b""
                        )
                        preds = [0] * nscan
                        eobrun = 0
                        restarts_to_go = restart_interval
                    restarts_to_go -= 1

                if nscan == 1:
                    index = scan[0][0]
                    comp = comps[index]
                    block = comp.rows[irow]
                    off = mcol * 64
                else:
                    block = None
                    off = 0

                if self.progressive:
                    if ss == 0 and ah == 0:
                        # DC first scan.
                        if nscan == 1:
                            s = _huff_decode(reader, dc_tables[0])
                            if s:
                                s = _extend(reader.get_bits(s), s)
                            s += preds[0]
                            preds[0] = s
                            block[off] = s << al
                        else:
                            for bi, (cidx, _td, _ta) in enumerate(scan):
                                comp = comps[cidx]
                                for y in range(comp.v_samp):
                                    row = comp.rows[irow * comp.v_samp + y]
                                    for x in range(comp.h_samp):
                                        pos = (mcol * comp.h_samp + x) * 64
                                        s = _huff_decode(reader, dc_tables[bi])
                                        if s:
                                            s = _extend(reader.get_bits(s), s)
                                        s += preds[bi]
                                        preds[bi] = s
                                        row[pos] = s << al
                    elif ss == 0:
                        # DC refinement.
                        if nscan == 1:
                            if reader.get_bits(1):
                                block[off] |= p1
                        else:
                            for cidx, _td, _ta in scan:
                                comp = comps[cidx]
                                for y in range(comp.v_samp):
                                    row = comp.rows[irow * comp.v_samp + y]
                                    for x in range(comp.h_samp):
                                        pos = (mcol * comp.h_samp + x) * 64
                                        if reader.get_bits(1):
                                            row[pos] |= p1
                    elif ah == 0:
                        # AC first scan, one component.
                        eobrun = self._decode_ac_first(
                            reader, ac_tables[0], block, off, ss, se, al_shift, eobrun
                        )
                    else:
                        eobrun = self._decode_ac_refine(
                            reader, ac_tables[0], block, off, ss, se, p1, m1, eobrun
                        )
                else:
                    # Sequential.
                    if nscan == 1:
                        s = _huff_decode(reader, dc_tables[0])
                        if s:
                            s = _extend(reader.get_bits(s), s)
                        s += preds[0]
                        preds[0] = s
                        block[off] = s
                        self._decode_ac_sequential(
                            reader, ac_tables[0], block, off, limit
                        )
                    else:
                        for bi, (cidx, _td, _ta) in enumerate(scan):
                            comp = comps[cidx]
                            for y in range(comp.v_samp):
                                row = comp.rows[irow * comp.v_samp + y]
                                for x in range(comp.h_samp):
                                    pos = (mcol * comp.h_samp + x) * 64
                                    s = _huff_decode(reader, dc_tables[bi])
                                    if s:
                                        s = _extend(reader.get_bits(s), s)
                                    s += preds[bi]
                                    preds[bi] = s
                                    row[pos] = s
                                    self._decode_ac_sequential(
                                        reader, ac_tables[bi], row, pos, limit
                                    )

    # -- arithmetic scans ------------------------------------------------

    def _decode_scan_arith(
        self,
        scan: list[tuple[int, int, int]],
        ss: int,
        se: int,
        ah: int,
        al: int,
        segments: list[bytes],
    ) -> None:
        comps = self.components
        nscan = len(scan)
        progressive = self.progressive
        if nscan == 1:
            comp = comps[scan[0][0]]
            mcus_per_row = comp.width_in_blocks
            mcu_rows = comp.height_in_blocks
        else:
            mcus_per_row = _ceil_div(self.width, self.max_h_samp * 8)
            mcu_rows = _ceil_div(self.height, self.max_v_samp * 8)

        if progressive:
            need_dc = ss == 0 and ah == 0
            need_ac = ss > 0
        else:
            need_dc = True
            need_ac = se > 0

        dc_stats: dict[int, list[int]] = {}
        if need_dc:
            for _cidx, td, _ta in scan:
                dc_stats.setdefault(td, [0] * 64)
        ac_stats: dict[int, list[int]] = {}
        if need_ac:
            for _cidx, _td, ta in scan:
                ac_stats.setdefault(ta, [0] * 256)

        last_dc = [0] * nscan
        dc_context = [0] * nscan
        lim_se = se if not progressive else 63

        restart_interval = self.restart_interval
        restarts_to_go = restart_interval
        seg_index = 0
        reader = _ArithDecoder(segments[0] if segments else b"")

        al_shift = 1 << al
        p1 = al_shift
        m1 = -al_shift

        for irow in range(mcu_rows):
            for mcol in range(mcus_per_row):
                if restart_interval:
                    if restarts_to_go == 0:
                        seg_index += 1
                        segment = (
                            segments[seg_index] if seg_index < len(segments) else b""
                        )
                        reader = _ArithDecoder(segment)
                        for stats in dc_stats.values():
                            stats[:] = [0] * 64
                        for stats in ac_stats.values():
                            stats[:] = [0] * 256
                        last_dc = [0] * nscan
                        dc_context = [0] * nscan
                        restarts_to_go = restart_interval
                    restarts_to_go -= 1

                if nscan == 1:
                    comp = comps[scan[0][0]]
                    blocks = [(0, comp.rows[irow], mcol * 64)]
                else:
                    blocks = []
                    for bi, (cidx, _td, _ta) in enumerate(scan):
                        comp = comps[cidx]
                        for y in range(comp.v_samp):
                            row = comp.rows[irow * comp.v_samp + y]
                            for x in range(comp.h_samp):
                                blocks.append(
                                    (bi, row,
                                     (mcol * comp.h_samp + x) * 64)
                                )

                if progressive:
                    if ss == 0 and ah == 0:
                        for bi, row, pos in blocks:
                            td = scan[bi][1]
                            row[pos] = (
                                self._arith_decode_dc(
                                    reader, dc_stats[td], last_dc,
                                    dc_context, bi, td,
                                )
                                << al
                            )
                    elif ss == 0:
                        for _bi, row, pos in blocks:
                            if reader.decode(self._arith_fixed_bin, 0):
                                row[pos] |= p1
                    else:
                        (_, row, pos) = blocks[0]
                        ta = scan[0][2]
                        if ah == 0:
                            self._arith_ac_first(
                                reader, ac_stats[ta], ta, row, pos,
                                ss, se, al_shift,
                            )
                        else:
                            self._arith_ac_refine(
                                reader, ac_stats[ta], row, pos,
                                ss, se, p1, m1,
                            )
                else:
                    for bi, row, pos in blocks:
                        td = scan[bi][1]
                        ta = scan[bi][2]
                        row[pos] = self._arith_decode_dc(
                            reader, dc_stats[td], last_dc, dc_context, bi, td,
                        )
                        self._arith_ac_seq(
                            reader, ac_stats[ta], ta, row, pos, lim_se,
                        )

    def _arith_decode_dc(
        self,
        reader: _ArithDecoder,
        stats: list[int],
        last_dc: list[int],
        dc_context: list[int],
        ci: int,
        tbl: int,
    ) -> int:
        context = dc_context[ci]
        if reader.decode(stats, context) == 0:
            dc_context[ci] = 0
        else:
            sign = reader.decode(stats, context + 1)
            index = context + 2 + sign
            m = reader.decode(stats, index)
            if m:
                index = 20
                while reader.decode(stats, index):
                    m <<= 1
                    if m == 0x8000:
                        raise JpegError("Bogus arithmetic-coded data")
                    index += 1
            low = (1 << self.arith_dc_l[tbl]) >> 1
            high = (1 << self.arith_dc_u[tbl]) >> 1
            if m < low:
                dc_context[ci] = 0
            elif m > high:
                dc_context[ci] = 12 + sign * 4
            else:
                dc_context[ci] = 4 + sign * 4

            value = m
            index += 14
            while True:
                m >>= 1
                if not m:
                    break
                if reader.decode(stats, index):
                    value |= m
            value += 1
            if sign:
                value = -value
            last_dc[ci] += value
        return last_dc[ci]

    def _arith_ac_seq(
        self,
        reader: _ArithDecoder,
        stats: list[int],
        tbl: int,
        block: list[int],
        off: int,
        lim_se: int,
    ) -> None:
        k = 1
        while k <= lim_se:
            index = 3 * (k - 1)
            if reader.decode(stats, index):
                break
            while reader.decode(stats, index + 1) == 0:
                index += 3
                k += 1
                if k > lim_se:
                    raise JpegError("Bogus arithmetic-coded data")
            sign = reader.decode(self._arith_fixed_bin, 0)
            index += 2
            m = reader.decode(stats, index)
            if m:
                if reader.decode(stats, index):
                    m <<= 1
                    index = 189 if k <= self.arith_ac_k[tbl] else 217
                    while reader.decode(stats, index):
                        m <<= 1
                        if m == 0x8000:
                            raise JpegError("Bogus arithmetic-coded data")
                        index += 1
            value = m
            index += 14
            while True:
                m >>= 1
                if not m:
                    break
                if reader.decode(stats, index):
                    value |= m
            value += 1
            if sign:
                value = -value
            block[off + NATURAL_ORDER[k]] = value
            k += 1

    def _arith_ac_first(
        self,
        reader: _ArithDecoder,
        stats: list[int],
        tbl: int,
        block: list[int],
        off: int,
        ss: int,
        se: int,
        al_shift: int,
    ) -> None:
        k = ss
        while k <= se:
            index = 3 * (k - 1)
            if reader.decode(stats, index):
                break
            while reader.decode(stats, index + 1) == 0:
                index += 3
                k += 1
                if k > se:
                    raise JpegError("Bogus arithmetic-coded data")
            sign = reader.decode(self._arith_fixed_bin, 0)
            index += 2
            m = reader.decode(stats, index)
            if m:
                if reader.decode(stats, index):
                    m <<= 1
                    index = 189 if k <= self.arith_ac_k[tbl] else 217
                    while reader.decode(stats, index):
                        m <<= 1
                        if m == 0x8000:
                            raise JpegError("Bogus arithmetic-coded data")
                        index += 1
            value = m
            index += 14
            while True:
                m >>= 1
                if not m:
                    break
                if reader.decode(stats, index):
                    value |= m
            value += 1
            if sign:
                value = -value
            block[off + NATURAL_ORDER[k]] = value * al_shift
            k += 1

    def _arith_ac_refine(
        self,
        reader: _ArithDecoder,
        stats: list[int],
        block: list[int],
        off: int,
        ss: int,
        se: int,
        p1: int,
        m1: int,
    ) -> None:
        kex = se
        while kex > 0 and block[off + NATURAL_ORDER[kex]] == 0:
            kex -= 1

        k = ss
        while k <= se:
            index = 3 * (k - 1)
            if k > kex and reader.decode(stats, index):
                break
            while True:
                pos = off + NATURAL_ORDER[k]
                coef = block[pos]
                if coef:
                    if reader.decode(stats, index + 2):
                        block[pos] = coef + (m1 if coef < 0 else p1)
                    break
                if reader.decode(stats, index + 1):
                    block[pos] = (
                        m1 if reader.decode(self._arith_fixed_bin, 0) else p1
                    )
                    break
                index += 3
                k += 1
                if k > se:
                    raise JpegError("Bogus arithmetic-coded data")
            k += 1

    @staticmethod
    def _decode_ac_sequential(
        reader: _BitReader,
        table: _HuffDecode,
        block: list[int],
        off: int,
        limit: int,
    ) -> None:
        k = 1
        while k <= limit:
            rs = _huff_decode(reader, table)
            r = rs >> 4
            s = rs & 15
            if s:
                k += r
                value = _extend(reader.get_bits(s), s)
                block[off + NATURAL_ORDER[k]] = value
            else:
                if r != 15:
                    break
                k += 15
            k += 1

    @staticmethod
    def _decode_ac_first(
        reader: _BitReader,
        table: _HuffDecode,
        block: list[int],
        off: int,
        ss: int,
        se: int,
        al_shift: int,
        eobrun: int,
    ) -> int:
        if eobrun > 0:
            return eobrun - 1
        k = ss
        while k <= se:
            rs = _huff_decode(reader, table)
            r = rs >> 4
            s = rs & 15
            if s:
                k += r
                value = _extend(reader.get_bits(s), s) * al_shift
                block[off + NATURAL_ORDER[k]] = value
            else:
                if r == 15:
                    k += 15
                else:
                    eobrun = 1 << r
                    if r:
                        eobrun += reader.get_bits(r)
                    eobrun -= 1
                    break
            k += 1
        return eobrun

    @staticmethod
    def _decode_ac_refine(
        reader: _BitReader,
        table: _HuffDecode,
        block: list[int],
        off: int,
        ss: int,
        se: int,
        p1: int,
        m1: int,
        eobrun: int,
    ) -> int:
        k = ss
        if eobrun == 0:
            while k <= se:
                rs = _huff_decode(reader, table)
                r = rs >> 4
                s = rs & 15
                if s:
                    value = p1 if reader.get_bits(1) else m1
                else:
                    if r != 15:
                        eobrun = 1 << r
                        if r:
                            eobrun += reader.get_bits(r)
                        break
                    value = 0
                while True:
                    pos = off + NATURAL_ORDER[k]
                    coef = block[pos]
                    if coef != 0:
                        if reader.get_bits(1):
                            if (coef & p1) == 0:
                                block[pos] = coef + (p1 if coef >= 0 else m1)
                    else:
                        r -= 1
                        if r < 0:
                            break
                    k += 1
                    if k > se:
                        break
                if s:
                    block[off + NATURAL_ORDER[k]] = value
                k += 1
        if eobrun > 0:
            while k <= se:
                pos = off + NATURAL_ORDER[k]
                coef = block[pos]
                if coef != 0:
                    if reader.get_bits(1):
                        if (coef & p1) == 0:
                            block[pos] = coef + (p1 if coef >= 0 else m1)
                k += 1
            eobrun -= 1
        return eobrun

    def _dc_decode(self, table_no: int) -> _HuffDecode:
        spec = self.dc_specs.get(table_no)
        if spec is None:
            raise JpegError(f"Missing DC Huffman table {table_no}")
        return _HuffDecode(spec)

    def _ac_decode(self, table_no: int) -> _HuffDecode:
        spec = self.ac_specs.get(table_no)
        if spec is None:
            raise JpegError(f"Missing AC Huffman table {table_no}")
        return _HuffDecode(spec)

    def _finish(self) -> JpegImage:
        if not self.saw_sof:
            raise JpegError("JPEG file has no image data")
        for comp in self.components:
            if comp.quant_tbl_no not in self.quant:
                raise JpegError(f"Missing quantization table {comp.quant_tbl_no}")
        max_h = max(c.h_samp for c in self.components)
        max_v = max(c.v_samp for c in self.components)
        return JpegImage(
            width=self.width,
            height=self.height,
            precision=self.precision,
            progressive=self.progressive,
            arithmetic=self.arithmetic,
            baseline=self.baseline,
            components=self.components,
            max_h_samp=max_h,
            max_v_samp=max_v,
            quant_tables=self.quant,
            colorspace=self.colorspace,
            saw_jfif=self.saw_jfif,
            jfif_major=self.jfif_major,
            jfif_minor=self.jfif_minor,
            density_unit=self.density_unit,
            x_density=self.x_density,
            y_density=self.y_density,
            saw_adobe=self.saw_adobe,
            adobe_transform=self.adobe_transform,
        )


def _read_scan_segments(data: bytes, pos: int) -> tuple[list[bytes], int]:
    """Split one scan's entropy data at restart markers.

    Returns the unstuffed segments and the offset of the marker that ended
    the scan (which the caller parses next).
    """
    segments: list[bytes] = []
    current = bytearray()
    i = pos
    size = len(data)
    while i < size:
        byte = data[i]
        if byte != 0xFF:
            current.append(byte)
            i += 1
            continue
        j = i + 1
        while j < size and data[j] == 0xFF:
            j += 1
        if j >= size:
            i = size
            break
        code = data[j]
        if code == 0x00:
            current.append(0xFF)
            i = j + 1
            continue
        if 0xD0 <= code <= 0xD7:
            segments.append(bytes(current))
            current = bytearray()
            i = j + 1
            continue
        segments.append(bytes(current))
        return segments, i
    segments.append(bytes(current))
    return segments, size


def parse_jpeg(data: bytes) -> JpegImage:
    return _Parser(data).parse()


# ---------------------------------------------------------------------------
# Encoder (libjpeg 8a transcode path)
# ---------------------------------------------------------------------------


def _gen_optimal_table(freq_in: list[int]) -> _HuffSpec:
    freq = freq_in[:]
    bits = [0] * 33
    codesize = [0] * 257
    others = [-1] * 257
    freq[256] = 1

    while True:
        c1 = -1
        best = 1000000000
        for i in range(257):
            if freq[i] and freq[i] <= best:
                best = freq[i]
                c1 = i
        c2 = -1
        best = 1000000000
        for i in range(257):
            if freq[i] and freq[i] <= best and i != c1:
                best = freq[i]
                c2 = i
        if c2 < 0:
            break
        freq[c1] += freq[c2]
        freq[c2] = 0
        codesize[c1] += 1
        while others[c1] >= 0:
            c1 = others[c1]
            codesize[c1] += 1
        others[c1] = c2
        codesize[c2] += 1
        while others[c2] >= 0:
            c2 = others[c2]
            codesize[c2] += 1

    for i in range(257):
        if codesize[i]:
            bits[codesize[i]] += 1

    for i in range(32, 16, -1):
        while bits[i] > 0:
            j = i - 2
            while bits[j] == 0:
                j -= 1
            bits[i] -= 2
            bits[i - 1] += 1
            bits[j + 1] += 2
            bits[j] -= 1

    i = 16
    while bits[i] == 0:
        i -= 1
    bits[i] -= 1

    table_bits = [0] * 17
    for k in range(1, 17):
        table_bits[k] = bits[k]

    values: list[int] = []
    for length in range(1, 33):
        for symbol in range(256):
            if codesize[symbol] == length:
                values.append(symbol)
    return _HuffSpec(table_bits, values)


def _derive_codes(spec: _HuffSpec) -> tuple[list[int], list[int]]:
    codes = [0] * 256
    sizes = [0] * 256
    code = 0
    p = 0
    for length in range(1, 17):
        for _ in range(spec.bits[length]):
            symbol = spec.values[p]
            codes[symbol] = code
            sizes[symbol] = length
            code += 1
            p += 1
        code <<= 1
    return codes, sizes


class _BitWriter:
    __slots__ = ("out", "buf", "nbits")

    def __init__(self, out: bytearray) -> None:
        self.out = out
        self.buf = 0
        self.nbits = 0

    def emit(self, code: int, size: int) -> None:
        if size == 0:
            raise JpegError("Missing Huffman code")
        self.buf = ((code & ((1 << size) - 1)) << (24 - (self.nbits + size))) | self.buf
        self.nbits += size
        while self.nbits >= 8:
            byte = (self.buf >> 16) & 0xFF
            self.out.append(byte)
            if byte == 0xFF:
                self.out.append(0)
            self.buf = (self.buf << 8) & 0xFFFFFF
            self.nbits -= 8

    def flush(self) -> None:
        self.emit(0x7F, 7)
        self.buf = 0
        self.nbits = 0


def _table_numbers(colorspace: str, count: int) -> list[tuple[int, int]]:
    if colorspace == JCS_YCbCr:
        return [(0, 0)] + [(1, 1)] * (count - 1)
    if colorspace == JCS_YCCK:
        return [(0, 0), (1, 1), (1, 1)] + [(0, 0)] * (count - 3)
    return [(0, 0)] * count


def _iter_mcus(image: JpegImage):
    comps = image.components
    mcus_per_row = _ceil_div(image.width, image.max_h_samp * 8)
    mcu_rows = _ceil_div(image.height, image.max_v_samp * 8)
    last_mcu_col = mcus_per_row - 1
    last_mcu_row = mcu_rows - 1

    for comp in comps:
        comp.last_col_width = comp.width_in_blocks % comp.h_samp
        if comp.last_col_width == 0:
            comp.last_col_width = comp.h_samp
        comp.last_row_height = comp.height_in_blocks % comp.v_samp
        if comp.last_row_height == 0:
            comp.last_row_height = comp.v_samp

    for irow in range(mcu_rows):
        for mcol in range(mcus_per_row):
            blocks: list[tuple[int, list[int]]] = []
            for ci, comp in enumerate(comps):
                start_col = mcol * comp.h_samp
                blockcnt = (
                    comp.h_samp if mcol < last_mcu_col else comp.last_col_width
                )
                for yidx in range(comp.v_samp):
                    if irow < last_mcu_row or yidx < comp.last_row_height:
                        row = comp.rows[irow * comp.v_samp + yidx]
                        for xidx in range(blockcnt):
                            off = (start_col + xidx) * 64
                            blocks.append((ci, row[off : off + 64]))
                        last_dc = blocks[-1][1][0]
                        for _ in range(blockcnt, comp.h_samp):
                            dummy = [0] * 64
                            dummy[0] = last_dc
                            blocks.append((ci, dummy))
                    else:
                        last_dc = blocks[-1][1][0] if blocks else 0
                        for _ in range(comp.h_samp):
                            dummy = [0] * 64
                            dummy[0] = last_dc
                            blocks.append((ci, dummy))
            yield blocks


def _htest_block(
    block: list[int], last_dc: int, dc_counts: list[int], ac_counts: list[int]
) -> None:
    temp = block[0] - last_dc
    if temp < 0:
        temp = -temp
    nbits = temp.bit_length()
    dc_counts[nbits] += 1

    run = 0
    for k in range(1, 64):
        temp = block[NATURAL_ORDER[k]]
        if temp == 0:
            run += 1
        else:
            while run > 15:
                ac_counts[0xF0] += 1
                run -= 16
            if temp < 0:
                temp = -temp
            nbits = temp.bit_length()
            ac_counts[(run << 4) + nbits] += 1
            run = 0
    if run > 0:
        ac_counts[0] += 1


def _encode_block(
    writer: _BitWriter,
    block: list[int],
    last_dc: int,
    dc_codes: list[int],
    dc_sizes: list[int],
    ac_codes: list[int],
    ac_sizes: list[int],
) -> None:
    diff = block[0] - last_dc
    temp = diff
    temp2 = diff
    if temp < 0:
        temp = -temp
        temp2 -= 1
    nbits = temp.bit_length()
    writer.emit(dc_codes[nbits], dc_sizes[nbits])
    if nbits:
        writer.emit(temp2, nbits)

    run = 0
    for k in range(1, 64):
        temp = block[NATURAL_ORDER[k]]
        if temp == 0:
            run += 1
        else:
            while run > 15:
                writer.emit(ac_codes[0xF0], ac_sizes[0xF0])
                run -= 16
            temp2 = temp
            if temp < 0:
                temp = -temp
                temp2 -= 1
            nbits = temp.bit_length()
            symbol = (run << 4) + nbits
            writer.emit(ac_codes[symbol], ac_sizes[symbol])
            writer.emit(temp2, nbits)
            run = 0
    if run > 0:
        writer.emit(ac_codes[0], ac_sizes[0])


def _emit_marker(out: bytearray, marker: int, payload: bytes) -> None:
    out.append(0xFF)
    out.append(marker)
    length = len(payload) + 2
    out.append((length >> 8) & 0xFF)
    out.append(length & 0xFF)
    out.extend(payload)


def encode_jpeg(image: JpegImage) -> bytes:
    count = len(image.components)
    if count == 0:
        raise JpegError("Empty image")
    for comp in image.components:
        if comp.quant_tbl_no not in image.quant_tables:
            raise JpegError(f"Missing quantization table {comp.quant_tbl_no}")

    table_nos = _table_numbers(image.colorspace, count)
    for comp, (dc_no, ac_no) in zip(image.components, table_nos):
        comp.dc_tbl_no = dc_no
        comp.ac_tbl_no = ac_no

    # ---- Huffman optimization pass ----
    dc_counts = [[0] * 257 for _ in range(4)]
    ac_counts = [[0] * 257 for _ in range(4)]
    last_dc = [0] * count
    for mcu in _iter_mcus(image):
        for ci, block in mcu:
            dc_no = table_nos[ci][0]
            ac_no = table_nos[ci][1]
            _htest_block(block, last_dc[ci], dc_counts[dc_no], ac_counts[ac_no])
            last_dc[ci] = block[0]

    used_dc = sorted({t[0] for t in table_nos})
    used_ac = sorted({t[1] for t in table_nos})
    dc_specs = {tbl: _gen_optimal_table(dc_counts[tbl]) for tbl in used_dc}
    ac_specs = {tbl: _gen_optimal_table(ac_counts[tbl]) for tbl in used_ac}
    dc_derived = {tbl: _derive_codes(spec) for tbl, spec in dc_specs.items()}
    ac_derived = {tbl: _derive_codes(spec) for tbl, spec in ac_specs.items()}

    out = bytearray()
    out += b"\xff\xd8"

    # APP0 / APP14
    if image.colorspace in (JCS_YCbCr, JCS_GRAYSCALE):
        major = image.jfif_major if image.saw_jfif and image.jfif_major == 1 else 1
        minor = image.jfif_minor if image.saw_jfif and image.jfif_major == 1 else 1
        payload = bytearray(b"JFIF\x00")
        payload += bytes((major, minor, image.density_unit))
        payload += image.x_density.to_bytes(2, "big")
        payload += image.y_density.to_bytes(2, "big")
        payload += b"\x00\x00"
        _emit_marker(out, M_APP0, bytes(payload))
    elif image.colorspace in (JCS_RGB, JCS_CMYK, JCS_YCCK):
        transform = {JCS_YCbCr: 1, JCS_YCCK: 2}.get(image.colorspace, 0)
        payload = bytearray(b"Adobe")
        payload += (100).to_bytes(2, "big")
        payload += b"\x00\x00\x00\x00"
        payload.append(transform)
        _emit_marker(out, M_APP14, bytes(payload))

    # DQT, in component order, duplicates suppressed.
    sent_q: set[int] = set()
    prec_any = False
    for comp in image.components:
        qno = comp.quant_tbl_no
        if qno in sent_q:
            continue
        sent_q.add(qno)
        table = image.quant_tables[qno]
        prec = 1 if any(table[NATURAL_ORDER[i]] > 255 for i in range(64)) else 0
        if prec:
            prec_any = True
        payload = bytearray([(prec << 4) | qno])
        for i in range(64):
            value = table[NATURAL_ORDER[i]]
            if prec:
                payload.append((value >> 8) & 0xFF)
            payload.append(value & 0xFF)
        _emit_marker(out, M_DQT, bytes(payload))

    # SOF0 / SOF1
    # Transcoding always emits a single sequential Huffman scan, so the SOF
    # choice depends only on the output sample precision and tables.
    is_baseline = (
        image.precision == 8
        and not prec_any
        and all(dc <= 1 and ac <= 1 for dc, ac in table_nos)
    )
    payload = bytearray([image.precision])
    payload += image.height.to_bytes(2, "big")
    payload += image.width.to_bytes(2, "big")
    payload.append(count)
    for comp in image.components:
        payload.append(comp.component_id & 0xFF)
        payload.append((comp.h_samp << 4) | comp.v_samp)
        payload.append(comp.quant_tbl_no)
    _emit_marker(out, M_SOF0 if is_baseline else M_SOF1, bytes(payload))

    # DHT, in scan order, duplicates suppressed.
    sent_dc: set[int] = set()
    sent_ac: set[int] = set()
    for comp in image.components:
        dc_no = comp.dc_tbl_no
        if dc_no not in sent_dc:
            sent_dc.add(dc_no)
            spec = dc_specs[dc_no]
            payload = bytearray([dc_no])
            payload += bytes(spec.bits[1:17])
            payload += bytes(spec.values)
            _emit_marker(out, M_DHT, bytes(payload))
        ac_no = comp.ac_tbl_no
        if ac_no not in sent_ac:
            sent_ac.add(ac_no)
            spec = ac_specs[ac_no]
            payload = bytearray([0x10 | ac_no])
            payload += bytes(spec.bits[1:17])
            payload += bytes(spec.values)
            _emit_marker(out, M_DHT, bytes(payload))

    # SOS
    payload = bytearray([count])
    for comp in image.components:
        payload.append(comp.component_id & 0xFF)
        payload.append((comp.dc_tbl_no << 4) | comp.ac_tbl_no)
    payload += b"\x00\x3f\x00"
    _emit_marker(out, M_SOS, bytes(payload))

    # Entropy-coded data
    writer = _BitWriter(out)
    last_dc = [0] * count
    for mcu in _iter_mcus(image):
        for ci, block in mcu:
            dc_no, ac_no = table_nos[ci]
            dc_codes, dc_sizes = dc_derived[dc_no]
            ac_codes, ac_sizes = ac_derived[ac_no]
            _encode_block(
                writer, block, last_dc[ci], dc_codes, dc_sizes, ac_codes, ac_sizes
            )
            last_dc[ci] = block[0]
    writer.flush()

    out += b"\xff\xd9"
    return bytes(out)
