from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # re-exec as an IPython kernel; used by the bundled kernelspec
    if argv and argv[0] == "--kernel-launcher":
        from ipykernel.kernelapp import launch_new_instance

        sys.argv = [sys.argv[0]] + argv[1:]
        launch_new_instance()
        return 0

    parser = argparse.ArgumentParser(
        prog="jnvim",
        description="Edit and run Jupyter notebooks in the terminal with vim motions.",
    )
    parser.add_argument("notebook", nargs="?", help="path to a .ipynb file (created if missing)")
    parser.add_argument("-k", "--kernel", help="kernel name (default: the notebook's, else python3)")
    parser.add_argument("--list-kernels", action="store_true", help="list installed kernels and exit")
    parser.add_argument("--version", action="store_true", help="print version and exit")
    args = parser.parse_args(argv)

    if args.version:
        from . import __version__

        print("jnvim %s" % __version__)
        return 0

    if args.list_kernels:
        from .kernel import install_bundled_kernelspec, list_kernels, resolve_kernel

        install_bundled_kernelspec()
        specs = list_kernels()
        if not specs:
            print("no kernels found (is jupyter_client installed?)", file=sys.stderr)
            return 1
        chosen = resolve_kernel(args.kernel or "python3")
        for name, display in sorted(specs.items()):
            print("%s %-24s %s" % ("*" if name == chosen else " ", name, display))
        return 0

    if os.name == "nt":
        print("jnvim needs a unix terminal (curses); run it under WSL or Linux.", file=sys.stderr)
        return 1

    path = args.notebook
    if path and not path.endswith(".ipynb"):
        path += ".ipynb"

    from .app import start

    try:
        start(path, args.kernel)
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
