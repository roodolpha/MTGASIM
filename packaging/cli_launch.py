"""PyInstaller entry point for the command-line tool."""
import sys

from brewbench.cli import main

sys.exit(main())
