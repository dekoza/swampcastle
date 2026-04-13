# SwampCastle Project

Guide the user through preparing a project for SwampCastle v4 mining.

## Step 1: Check Python

Confirm Python 3.11+.

If it is older or missing, stop and say SwampCastle v4 requires Python 3.11 or newer.

## Step 2: Check installation

Run `pip show swampcastle`.

If not installed, install it:

```bash
pip install swampcastle
```

## Step 3: Ask for the project directory

Ask which project directory they want to prepare for mining.

## Step 4: Create project-local config

Run:

```bash
swampcastle project <dir>
```

If they want contributor tagging during ingest, include a shared team list:

```bash
swampcastle project <dir> --team dekoza sarah
```

Explain that this writes `.swampcastle.yaml` for that project.

## Step 5: Ingest data

Run:

```bash
swampcastle gather <dir>
```

If they want conversation exports instead:

```bash
swampcastle gather <dir> --mode convos
```

## Step 6: Verify the castle

Run:

```bash
swampcastle survey
```

## Step 7: MCP setup

Recommend:

```bash
claude mcp add swampcastle -- swampcastle-mcp
```

or:

```bash
swampcastle drawbridge
```

to print the setup command first.

## Step 8: Show next steps

Suggest:
- `swampcastle seek "query"`
- `swampcastle survey`
- `swampcastle gather <another-dir>`
- `swampcastle wizard` if they want to change global runtime backend or storage settings
