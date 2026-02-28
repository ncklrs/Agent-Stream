#!/usr/bin/env python3
"""Entry point for AgentStream.app macOS bundle.

This is the script py2app uses to create the application.
It launches the menu bar toolbar with the watch stream.
"""

import os
import sys


def main():
    # When running as a .app bundle, ensure the bundled Python
    # can find the agentstream package (py2app handles this, but
    # belt-and-suspenders for edge cases).
    if getattr(sys, "frozen", False):
        bundle_dir = os.path.dirname(os.path.abspath(sys.executable))
        resources = os.path.join(bundle_dir, "..", "Resources")
        if resources not in sys.path:
            sys.path.insert(0, resources)

    from agentstream.toolbar import main as toolbar_main

    toolbar_main(demo="AGENTSTREAM_DEMO" in os.environ)


if __name__ == "__main__":
    main()
