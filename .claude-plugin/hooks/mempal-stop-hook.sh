#!/bin/bash
# SwampCastle Stop Hook — thin wrapper calling Python CLI
# All logic lives in swampcastle.hooks_cli for cross-harness extensibility
INPUT=$(cat)
echo "$INPUT" | python3 -m swampcastle hook run --hook stop --harness claude-code
