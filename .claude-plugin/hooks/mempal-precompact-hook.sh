#!/bin/bash
# SwampCastle PreCompact Hook — thin wrapper calling Python CLI
# All logic lives in swampcastle.hooks_cli for cross-harness extensibility
INPUT=$(cat)
echo "$INPUT" | SWAMPCASTLE_INTERNAL=1 python3 -m swampcastle hook run --hook precompact --harness claude-code
