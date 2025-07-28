#!/usr/bin/env python3

import asyncio
import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.cli import cli

def main():
    try:
        cli()
    except KeyboardInterrupt:
        print("\n⚡ t10 interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
