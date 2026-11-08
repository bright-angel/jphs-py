"""jphs steganography core.

This is a direct transcription of the state machine in the upstream
``jphide.c`` / ``jpseek.c``: payload bits are merged into the low bits of
quantized DCT coefficients, walked in the fixed carrier order given by
``ltable.h`` and gated by four Blowfish bit streams seeded from the first
eight coefficients of the Y DC block.
"""

from __future__ import annotations

from ._tables import LTAB
from .blowfish import Blowfish
from .jpeg import JpegImage, encode_jpeg

__all__ = [
    "StegoError",
    "NotEnoughSpaceError",
    "RecoveryError",
    "hide",
    "seek",
]

NKSTREAMS = 4
TAIL1 = 12000
TAIL2 = 1200
TAIL3 = 120


class StegoError(Exception):
    """Base class for jphs steganography failures."""


class NotEnoughSpaceError(StegoError):
    """The cover image cannot hold the payload."""


class RecoveryError(StegoError):
    """The carrier space ended before the payload was recovered."""


class _Walker:
    """Coefficient traversal plus the four Blowfish bit streams."""

    __slots__ = (
        "planes",
        "hib",
        "wib",
        "coef",
        "mode",
        "spos",
        "lh",
        "lt",
        "lw",
        "d",
        "tail",
        "tail_on",
        "cpos",
        "cdata",
        "bkey",
        "lendata",
        "okfile",
        "data_pos",
        "data_char",
    )

    def __init__(self, planes, passphrase: bytes) -> None:
        self.planes = planes
        self.hib = [c.height_in_blocks for c in planes]
        self.wib = [64 * c.width_in_blocks - 1 for c in planes]

        self.coef = LTAB[0]
        self.spos = LTAB[1]
        self.mode = LTAB[2]
        self.d = 0
        self.lh = 0
        self.lw = self.spos - 64
        self.lt = 0

        self.tail = 0
        self.tail_on = 0
        self.okfile = True
        self.data_pos = 0
        self.data_char = 0

        self.bkey = Blowfish(passphrase)
        iv = bytearray(9)
        first_row = planes[0].rows[0]
        for i in range(8):
            iv[i] = first_row[i] & 0xFF

        self.cpos = [0] * NKSTREAMS
        self.cdata = []
        for _ in range(NKSTREAMS):
            self.cdata.append(self.bkey.encrypt_block(bytes(iv[:8])))
            iv[8] = iv[0]
            for j in range(8):
                iv[j] = iv[j + 1]
        self.lendata = self.bkey.encrypt_block(bytes(iv[:8]))

    # -- keystream -------------------------------------------------------

    def get_code_bit(self, k: int) -> int:
        b = self.cpos[k] & 63
        if b == 0:
            self.cdata[k] = self.bkey.encrypt_block(self.cdata[k])
        x = self.cdata[k][b >> 3]
        z = ((x << (b & 7)) & 0xFF) >> 7
        self.cpos[k] += 1
        return z

    # -- carrier traversal ----------------------------------------------

    def get_word(self, okfile: bool, exhausted: int) -> tuple[int, int]:
        """Return ``(status, value)``.

        ``status`` is 0 for a usable carrier, ``1`` when the traversal ended
        because the payload file is exhausted, and ``exhausted`` (``-1`` for
        the hider) when the carrier table ran out.
        """
        planes = self.planes
        while True:
            self.lw += 64
            if self.lw > self.wib[self.coef]:
                self.lw = self.spos
                self.lh += 1
                if not (self.lh < self.hib[self.coef]):
                    if not okfile:
                        return 1, 0
                    self.lt += 3
                    if LTAB[self.lt] < 0:
                        return exhausted, 0
                    if self.tail < 0:
                        if self.tail_on == 2:
                            self.tail_on = 3
                            self.tail = 999999
                        if self.tail_on == 1:
                            self.tail_on = 2
                            self.tail = TAIL3
                        if self.tail_on == 0:
                            self.tail_on = 1
                            self.tail = TAIL2
                    self.coef = LTAB[self.lt]
                    self.lw = self.spos = LTAB[self.lt + 1]
                    self.lh = 0
                    self.mode = LTAB[self.lt + 2]

            y = planes[self.coef].rows[self.lh][self.lw]

            if self.coef or self.lh or self.lw > 7:
                if self.mode < 0:
                    if y > -self.mode or y < self.mode:
                        ok = self.get_code_bit(0)
                        ok = ok << 1
                        ok |= self.get_code_bit(0)
                    else:
                        ok = 0
                else:
                    if self.mode == 3:
                        ok = self.get_code_bit(0)
                    else:
                        ok = 1
                    if ok:
                        if y > 1 or y < -1:
                            ok = 0
                        else:
                            ok = self.get_code_bit(0)
                            if self.mode:
                                ok = ok << 1
                                ok |= self.get_code_bit(0)
                        if ok:
                            ok = 0
                        else:
                            if self.mode > 1:
                                ok = self.get_code_bit(0)
                            else:
                                ok = 1
            else:
                ok = 0

            if ok and self.tail_on > 0:
                ok = self.get_code_bit(2)
            if ok and self.tail_on > 1:
                ok = self.get_code_bit(2)
            if ok and self.tail_on > 2:
                ok = self.get_code_bit(2)

            if ok:
                return 0, y

    def put_word(self, value: int) -> None:
        self.planes[self.coef].rows[self.lh][self.lw] = value

    def merge_word(self, word: int, bit: int) -> int:
        y = word
        if self.mode < 0:
            z = bit << 1
            if y > 0:
                y &= ~2
                y |= z
            else:
                y = 0 - y
                y &= ~2
                y |= z
                y = 0 - y
        else:
            if y == 0:
                self.d = 0 - self.d
                y = self.d * bit
            elif y == -1 or y == 1:
                self.d = y
                y = bit * y
            elif y > 0:
                self.d = 1
                y &= ~1
                y |= bit
            else:
                self.d = -1
                y = 0 - y
                y &= ~1
                y |= bit
                y = 0 - y
        return y

    def demerge_word(self, word: int) -> int:
        z = 0 - word if word < 0 else word
        if self.mode < 0:
            return (z & 2) >> 1
        return z & 1

    # -- payload source (hider) -----------------------------------------

    def next_payload_bit(self, payload: bytes) -> int:
        if self.okfile:
            if (self.data_pos & 7) == 0:
                index = self.data_pos >> 3
                if index < len(payload):
                    self.data_char = payload[index]
                else:
                    self.okfile = False
        if self.okfile:
            z = (self.data_char & 128) >> 7
            z ^= self.get_code_bit(1)
            self.data_char = (self.data_char << 1) & 0xFF
            self.data_pos += 1
            self.tail -= 1
        else:
            z = self.get_code_bit(2)
        return z

    # -- payload source (seeker) ----------------------------------------

    def next_recovered_bit(self) -> int:
        status, y = self.get_word(True, 1)
        if status:
            return -1
        return self.demerge_word(y)


def hide(image: JpegImage, payload: bytes, passphrase: bytes) -> bytes:
    """Embed *payload* in *image* and return the output JPEG bytes."""
    planes = image.components
    if len(planes) != 3:
        raise StegoError(
            f"Unsuitable input jpeg file: No of components = {len(planes)}"
        )

    walker = _Walker(planes, passphrase)
    length = len(payload)
    walker.tail = length * 8 - TAIL1
    walker.tail_on = 0

    header = bytearray(walker.lendata)
    header[0] = (length >> 16) & 0xFF
    header[1] = (length >> 8) & 0xFF
    header[2] = length & 0xFF
    walker.lendata = walker.bkey.encrypt_block(bytes(header))

    for i in range(8):
        for j in range(8):
            status, y = walker.get_word(True, -1)
            if status:
                raise NotEnoughSpaceError("File not completely stored")
            bit = (walker.lendata[i] >> j) & 1
            walker.put_word(walker.merge_word(y, bit))

    while True:
        status, y = walker.get_word(walker.okfile, -1)
        if status == 0:
            walker.put_word(walker.merge_word(y, walker.next_payload_bit(payload)))
        elif status == 1:
            break
        else:
            raise NotEnoughSpaceError("File not completely stored")

    return encode_jpeg(image)


def seek(image: JpegImage, passphrase: bytes) -> bytes:
    """Recover the payload embedded in *image*."""
    planes = image.components
    if len(planes) != 3:
        raise StegoError(
            f"Unsuitable input jpeg file: No of components = {len(planes)}"
        )

    walker = _Walker(planes, passphrase)

    header = bytearray(8)
    for i in range(8):
        v = 0
        for j in range(8):
            b = walker.next_recovered_bit()
            if b < 0:
                raise RecoveryError("File not completely recovered")
            v |= b << j
        header[i] = v

    decoded = walker.bkey.decrypt_block(bytes(header))
    length = (decoded[0] << 16) | (decoded[1] << 8) | decoded[2]
    walker.tail = length * 8 - TAIL1
    walker.tail_on = 0

    out = bytearray()
    v = 0
    for _ in range(length):
        for _ in range(8):
            b = walker.next_recovered_bit()
            if b < 0:
                raise RecoveryError("File not completely recovered")
            b ^= walker.get_code_bit(1)
            v = ((v << 1) | b) & 0xFF
            walker.tail -= 1
        out.append(v)
    return bytes(out)
