"""PyInstaller の入口（docs/design.md §9.3）。toolkeeper.exe / toolkeeperw.exe <サブコマンド> として動く"""
import sys

from toolkeeper.cli import main

sys.exit(main())
