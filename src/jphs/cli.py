"""Command line front end, mirroring the upstream ``jphide``/``jpseek``
programs: same prompts, messages, file ordering and exit codes.
"""

from __future__ import annotations

import getpass
import os
import sys
from pathlib import Path

from . import HS_MAJOR_VERSION, HS_MINOR_VERSION
from .jpeg import JpegError, parse_jpeg
from .stego import NotEnoughSpaceError, RecoveryError, StegoError, hide, seek

__all__ = ["jphide", "jpseek", "jphide_entry", "jpseek_entry"]

INTRO = (
    "\n{prog}, version {major}.{minor} (c) 1998 Allan Latham "
    "<alatham@flexsys-group.com>\n\n"
    "This is licenced software but no charge is made for its use.\n"
    "NO WARRANTY whatsoever is offered with this product.\n"
    "NO LIABILITY whatsoever is accepted for its use.\n"
    "You are using this entirely at your OWN RISK.\n"
    "See the GNU Public Licence for full details.\n\n"
)

USAGE = {
    "jphide": "Usage:\n\njphide input-jpg-file output-jpg-file hide-file\n\n",
    "jpseek": "Usage:\n\njpseek input-file seek-file\n\n",
}

MAX_PASSPHRASE = 120


def _intro(prog: str) -> None:
    sys.stdout.write(INTRO.format(prog=prog, major=HS_MAJOR_VERSION,
                                  minor=HS_MINOR_VERSION))
    sys.stdout.flush()


def _perror(message: str, exc: OSError) -> None:
    sys.stderr.write(f"{message}: {exc.strerror or exc}\n")


def _getpass(prompt: str) -> bytes:
    return os.fsencode(getpass.getpass(prompt))


def _hide_passphrase() -> bytes | None:
    while True:
        first = _getpass("Passphrase: ")
        if not first:
            sys.stderr.write("Nothing done\n")
            return None
        if len(first) > MAX_PASSPHRASE:
            sys.stderr.write("Truncated to 120 characters\n")
            first = first[:MAX_PASSPHRASE]
        second = _getpass("Re-enter  : ")
        if not second:
            sys.stderr.write("Nothing done\n")
            return None
        second = second[:MAX_PASSPHRASE]
        if first != second:
            sys.stderr.write("Passphrases are different - try again\n")
            continue
        return first


def _seek_passphrase() -> bytes | None:
    passphrase = _getpass("Passphrase: ")
    if not passphrase:
        sys.stderr.write("Nothing done\n")
        return None
    if len(passphrase) > MAX_PASSPHRASE:
        sys.stderr.write("Truncated to 120 characters\n")
        passphrase = passphrase[:MAX_PASSPHRASE]
    return passphrase


def _load(data: bytes, prog: str):
    try:
        return parse_jpeg(data)
    except JpegError as exc:
        sys.stderr.write(f"{exc}\n")
        return None


def _check_components(image) -> bool:
    if len(image.components) != 3:
        sys.stderr.write(
            "Unsuitable input jpeg file: No of components = "
            f"{len(image.components)}\n"
        )
        return False
    return True


def jphide(argv: list[str]) -> int:
    _intro("jphide")
    if len(argv) != 3:
        sys.stderr.write(USAGE["jphide"])
        return 1
    input_name, output_name, hide_name = argv

    try:
        payload = Path(hide_name).read_bytes()
    except OSError as exc:
        _perror("Can't open hide file", exc)
        return 1

    try:
        input_file = open(input_name, "rb")
    except OSError as exc:
        _perror("Can't open input file", exc)
        return 1
    try:
        output_file = open(output_name, "wb")
    except OSError as exc:
        input_file.close()
        _perror("Can't open output file", exc)
        return 1

    with input_file, output_file:
        image = _load(input_file.read(), "jphide")
        if image is None:
            return 1
        if not _check_components(image):
            return 1

        passphrase = _hide_passphrase()
        if passphrase is None:
            return 0

        try:
            encoded = hide(image, payload, passphrase)
        except NotEnoughSpaceError:
            sys.stderr.write("File not completely stored\n")
            return 1
        except StegoError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1
        output_file.write(encoded)
    return 0


def jpseek(argv: list[str]) -> int:
    _intro("jpseek")
    if len(argv) != 2:
        sys.stderr.write(USAGE["jpseek"])
        return 1
    input_name, seek_name = argv

    try:
        input_file = open(input_name, "rb")
    except OSError as exc:
        _perror("Can't open input file", exc)
        return 1
    try:
        output_file = open(seek_name, "wb")
    except OSError as exc:
        input_file.close()
        _perror("Can't open seek file", exc)
        return 1

    with input_file, output_file:
        image = _load(input_file.read(), "jpseek")
        if image is None:
            return 1
        if not _check_components(image):
            return 1

        passphrase = _seek_passphrase()
        if passphrase is None:
            return 0

        try:
            payload = seek(image, passphrase)
        except RecoveryError:
            sys.stderr.write("File not completely recovered\n")
            return 1
        except StegoError as exc:
            sys.stderr.write(f"{exc}\n")
            return 1
        output_file.write(payload)
    return 0


def jphide_entry() -> None:
    raise SystemExit(jphide(sys.argv[1:]))


def jpseek_entry() -> None:
    raise SystemExit(jpseek(sys.argv[1:]))
