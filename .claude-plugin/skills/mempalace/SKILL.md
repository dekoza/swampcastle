---
name: swampcastle
description: SwampCastle — mine projects and conversations into a searchable memory palace. Use when asked about swampcastle, memory palace, mining memories, searching memories, or palace setup.
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
---

# SwampCastle

A searchable memory palace for AI — mine projects and conversations, then search them semantically.

## Prerequisites

Ensure `swampcastle` is installed:

```bash
swampcastle --version
```

If not installed:

```bash
pip install swampcastle
```

## Usage

SwampCastle provides dynamic instructions via the CLI. To get instructions for any operation:

```bash
swampcastle instructions <command>
```

Where `<command>` is one of: `help`, `init`, `mine`, `search`, `status`.

Run the appropriate instructions command, then follow the returned instructions step by step.
