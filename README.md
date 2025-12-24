# File Sorter XX

A local desktop utility for macOS that helps you organize media fast.
Drop a batch of files or scan a folder, and it will **copy** them into a clean output structure, apply consistent naming, and detect duplicates using **SHA-256**.

## Features

- **Drag and drop** files into the app to process them
- **Scan a source folder** and process everything inside it
- **Copies originals** into an output folder (does not delete or move your originals)
- Sorts into:
  - `PICS`
  - `VIDS`
  - `GIFS`
  - `DUPES`
  - `NEW CONTENT` (reserved, available if you want to use it later)
- **Duplicate detection** (SHA-256) with duplicates routed to `DUPES`
- Simple UI:
  - Choose Source folder
  - Choose Output folder
  - Open Output folder
  - Process Source
  - Output log + progress bar

## Output structure

Inside your selected **Output** folder, the app creates:

```
PICS/
VIDS/
GIFS/
DUPES/
NEW CONTENT/
.ghost_media_index.json
```

Notes:
- `.ghost_media_index.json` stores the dedupe index and counters.
- `DUPES/` contains any file whose SHA-256 matches something already processed.

## Naming convention

Files are renamed using a consistent format:

- Pictures: `PIC_<id>.<ext>`
- Videos: `VID_<id>.<ext>`
- GIFs: `GIF_<id>.<ext>`

IDs are zero-padded (example: `000042`).

If a duplicate is found, it is copied into `DUPES/` with a name like:

- `DUPE_<existingKey>_<originalStem>.<ext>`

## How duplicate detection works

- Each processed file is hashed with **SHA-256**
- If the hash already exists in the index:
  - The file is treated as a duplicate
  - It is copied into `DUPES/`
- When scanning a folder, the app also tracks source file paths so re-running a scan does not re-copy the exact same file path endlessly

## Requirements

- macOS
- Python 3 (recommended: Homebrew or python.org install)

## Install and run

### Option A: Double click (recommended)

1. Clone or download this repository
2. Double click `Run.command`

If macOS blocks it:
- Right click `Run.command`
- Click **Open**
- Click **Open** again

### Option B: Terminal

From the project folder:

```bash
chmod +x Run.command
./Run.command
```

## Using the app

### Set folders

- Click **Choose source** to select the folder you want to scan
- Click **Choose output** to select where the sorted results should be copied

### Process files

- Drag and drop files into the app window  
  or
- Click **Process source** to scan the entire Source folder

### Find your results

- Click **Open output** to open the output folder in Finder

## Safety notes

- This tool copies files to the output folder. It does not delete originals.
- Always test on a small folder first if you are running it against a large archive.

## What gets stored locally

- `.file_sorter_config.json` (your last-used Source/Output paths)
- `.ghost_media_index.json` (hash index, counters, metadata)

If you are publishing or sharing the code, do not commit these files.

## Roadmap ideas

- Custom folder labels and naming templates
- Optional keyword tagging (disabled in public version)
- Exportable CSV report of processed files
- Optional copy vs move toggle (default: copy)
