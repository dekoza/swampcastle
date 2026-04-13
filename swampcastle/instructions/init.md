# SwampCastle Init

Guide the user through a working v4 setup.

## Step 1: Check Python

Confirm Python 3.11+.

If it is older or missing, stop and say SwampCastle v4 requires Python 3.11 or newer.

## Step 2: Check installation

Run `pip show swampcastle`.

If not installed, install it:

```bash
pip install swampcastle
```

## Step 3: Ask for the source directory

Ask which directory they want to inspect / ingest.

## Step 4: Preview structure

Run:

```bash
swampcastle build <dir>
```

Explain that `build` previews room and entity detection. It is not the ingest step.

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
