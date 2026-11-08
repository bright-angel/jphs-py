#!/usr/bin/env python3
"""Run a program under a pty and answer getpass() prompts.

Usage: pty_run.py <command> [args...]
Env:
  JPHS_PASSES     pipe-separated replies for "Passphrase: " prompts
  JPHS_REENTERS   pipe-separated replies for "Re-enter  : " prompts
"""
import os
import pty
import select
import sys


def replies(name, default):
    raw = os.environ.get(name)
    if raw is None:
        return [default]
    return raw.split("|")


def main():
    if len(sys.argv) < 2:
        raise SystemExit("usage: pty_run.py command [args...]")
    passes = replies("JPHS_PASSES", os.environ.get("JPHS_PASS", ""))
    reenters = replies("JPHS_REENTERS", os.environ.get("JPHS_PASS", ""))

    pid, fd = pty.fork()
    if pid == 0:
        os.execvp(sys.argv[1], sys.argv[1:])

    seen = bytearray()
    pass_count = 0
    reenter_count = 0
    status = 0
    while True:
        try:
            ready, _, _ = select.select([fd], [], [], 0.05)
        except OSError:
            break
        if fd in ready:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                chunk = b""
            if not chunk:
                break
            seen += chunk
            sys.stdout.buffer.write(chunk)
            sys.stdout.flush()
            text = seen.decode("utf-8", "replace")
            while text.count("Passphrase: ") > pass_count:
                reply = passes[min(pass_count, len(passes) - 1)]
                os.write(fd, (reply + "\n").encode())
                pass_count += 1
            while text.count("Re-enter  : ") > reenter_count:
                reply = reenters[min(reenter_count, len(reenters) - 1)]
                os.write(fd, (reply + "\n").encode())
                reenter_count += 1
    _, status = os.waitpid(pid, 0)
    if os.WIFEXITED(status):
        raise SystemExit(os.WEXITSTATUS(status))
    raise SystemExit(128 + os.WTERMSIG(status))


if __name__ == "__main__":
    main()
