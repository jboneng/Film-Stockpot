# Film Stockpot

Apply authentic film-stock looks to flat scans, Fuji Frontier–style.

Film Stockpot is a PyQt6 desktop application for film photographers who scan their
own negatives. It takes **flat / log 16-bit TIFF exports from
[NegPy](https://www.negpy.com/)** and grades them back to life: expanding the flat
scan to full range, applying a chosen film-stock emulation, and giving you a set of
familiar Frontier-style operator controls to fine-tune each frame. Edits are
non-destructive, saved per image, and can be batch-applied across a whole roll.

> **Input expectations:** Film Stockpot is designed around **flat exported images
> from NegPy in 16-bit TIFF format**. These are inverted, color-corrected but
> intentionally low-contrast ("flat" / "log") scans. The pipeline de-logs and
> normalizes them before applying the film look, so feeding it already-graded JPEGs
> or contrasty scans will not produce the intended result.

---

## Table of contents

- [Features](#features)
- [How it works](#how-it-works)
- [Requirements](#requirements)
- [Installation](#installation)
- [Usage](#usage)
- [Film stock presets](#film-stock-presets)
- [Creating and editing film presets](#creating-and-editing-film-presets)
- [Tuning the Frontier base profile](#tuning-the-frontier-base-profile)
- [Sidecar files](#sidecar-files)
- [Project layout](#project-layout)
- [Development](#development)
- [License](#license)

---

## Features

- **Flat-scan aware pipeline** — de-logs and auto-levels NegPy's flat 16-bit TIFF
  exports before grading, so images don't come out washed out.
- **Film-stock emulation** — a library of color and black & white stocks (Kodak
  Portra/Gold/Ektar/Tri-X/T-MAX, Fujicolor, Ilford HP5, HARMAN Phoenix II, and more).
- **Frontier-style operator controls** — density, gamma, CMY color balance, tone
  (Soft → All Hard), highlight/shadow, saturation, and sharpness, all with live
  preview.
- **Film-strip browser** — thumbnail strip of every TIFF in a folder, with badges
  for edited and excluded frames.
- **Non-destructive editing** — every adjustment is saved to a per-image JSON
  sidecar; your original TIFF is never modified.
- **Single and batch export** — export the current frame, or render the entire
  roll to 16-bit TIFF, honoring each image's own saved settings.
- **Self-contained sidecars** — sidecars embed the full preset and base profile,
  so a TIFF + sidecar renders identically on another machine even if that stock
  isn't installed there.

## How it works

The processing pipeline is intentionally stateless — it always grades from the
pristine original, so switching presets never stacks edits.

1. **Input transform (base profile)** — expands the flat/log scan to full range via
   auto-levels, a configurable de-log S-curve, and a brightness gamma.
2. **Film look** — applies the stock's color matrix (or mono mixer for B&W) and
   white balance.
3. **Tone & grade** — tone curve, contrast, lift/gain, gamma, and highlight/shadow
   shaping.
4. **Color & detail** — saturation and film grain.
5. **Operator adjustments** — your live Frontier-style slider tweaks are applied on
   top, mirroring how a lab operator fine-tunes a scan.

## Requirements

- **Python 3.12+**
- **[uv](https://docs.astral.sh/uv/getting-started/installation/)** for dependency
  management

Core dependencies (installed automatically): `numpy`, `pillow`, `tifffile`,
`imagecodecs`, and `pyqt6`.

## Installation

Clone the repository and sync the environment:

```bash
git clone https://github.com/<your-username>/FilmStockpot.git
cd FilmStockpot
uv sync
```

On first run, `uv` downloads the Python version pinned in `.python-version` if it
isn't already installed.

## Usage

Launch the application:

```bash
uv run film-stockpot
```

Or run it as a module:

```bash
uv run python -m film_stockpot
```

See [RUNNING.md](RUNNING.md) for activating the virtual environment directly and
other command-line details.

### Typical workflow

1. Export your negatives from **NegPy as flat 16-bit TIFFs** into a folder.
2. In Film Stockpot, click **Open Folder** and select that folder.
3. Pick a frame from the film strip on the left.
4. Choose a **Film Stock** from the dropdown.
5. Fine-tune with the **Frontier Controls** (density, color balance, tone, etc.).
   The preview updates live and your edits are saved automatically.
6. Switch to the **Export** tab and click **Export Image** for the current frame,
   or **Export All** to render the whole roll to 16-bit TIFF.

> Tip: right-click a thumbnail to clear its saved edits or exclude it from batch
> export.

## Film stock presets

Presets live in the [`FilmPresets/`](FilmPresets) folder as JSON files, organized
by the [`_index.json`](FilmPresets/_index.json) manifest. A shared
[`_frontier_base.json`](FilmPresets/_frontier_base.json) profile is applied beneath
every stock so the Frontier signature is added once rather than baked in twice.

Files beginning with an underscore (`_index.json`, `_frontier_base.json`) are
reserved; every other `.json` file is treated as a film stock. The next two
sections are a complete guide to authoring and tuning them.

## Creating and editing film presets

This section walks through building a new film stock from scratch and tweaking an
existing one. The fastest way to start is to **copy the preset closest to your
target** (e.g. [`kodak_portra_400.json`](FilmPresets/kodak_portra_400.json) for a
soft color stock, or [`kodak_tmax_100.json`](FilmPresets/kodak_tmax_100.json) for
black & white) and edit from there.

### 1. Add the file and register it

1. Create `FilmPresets/my_stock.json`.
2. Give it a unique `id` (used internally and in sidecars) and a display `name`.
3. Add an entry to the appropriate group in
   [`_index.json`](FilmPresets/_index.json):

```json
{
  "family": "kodak_consumer",
  "label": "Kodak consumer",
  "presets": [
    { "id": "my_stock", "name": "My Stock 400", "file": "my_stock.json" }
  ]
}
```

To create a brand-new group, add another object to the `groups` array with its own
`family`, `label`, and `presets` list. The dropdown shows groups in index order,
and presets in the order listed. If `_index.json` is missing entirely, the app
falls back to loading every non-underscore JSON file as one flat group.

> The `id` must be unique. Sidecars are matched back to installed stocks by `id`,
> so changing an `id` later will orphan any existing edits made with the old one.

### 2. Understand which fields actually render

A preset file contains two kinds of fields:

- **Render fields** — read by the processing pipeline and change the image.
- **Metadata fields** — documentation only (datasheet values, notes, confidence).
  They're useful for provenance but have **no effect on the output**.

Everything the renderer reads lives under the top-level `monochrome` flag and the
`pipeline` object. A minimal but complete color preset looks like this:

```json
{
  "schema_version": "1.0",
  "id": "my_stock",
  "name": "My Stock 400",
  "monochrome": false,
  "pipeline": {
    "tone_curve_8bit": [[0, 0], [32, 26], [96, 106], [192, 212], [255, 252]],
    "white_balance": { "rgb_gains": [1.01, 1.0, 0.99] },
    "scanner_adjustments": {
      "highlights": -10,
      "shadows": -2,
      "gamma": 0.98,
      "saturation_pct": 102
    },
    "look": {
      "contrast_pct": 5,
      "lift": -0.01,
      "gain": 1.0,
      "color_matrix": [[1.01, 0.0, -0.01], [0.0, 1.0, 0.0], [-0.01, 0.01, 1.01]],
      "mono_mixer": null
    },
    "grain": { "intensity": 0.4 }
  }
}
```

The other fields you'll see in the shipped presets — `manufacturer`, `type`,
`category`, `film`, `notes`, `confidence`, `native_scanner_profile`, `source`, and
`temp_k`/`tint`/`temp_k_bias`/`local_contrast_pct` — are metadata and are **not**
applied. Keep them for reference, but don't expect them to change the look.

### 3. Render field reference

Stages run in this order, on top of the [Frontier base](#tuning-the-frontier-base-profile)'s
input transform. Color and B&W differ where noted.

| Field | Type | Neutral | What it does |
|-------|------|---------|--------------|
| `monochrome` | bool | `false` | When `true`, converts to grayscale via `look.mono_mixer` and **skips** `color_matrix`, `white_balance`, and saturation. |
| `look.mono_mixer` | `[r, g, b]` | `[0.299, 0.587, 0.114]` | B&W only. RGB → luma weights. Higher G ≈ panchromatic; raise R to lighten skin, raise B to darken skies. |
| `look.color_matrix` | 3×3 | identity | Color only. Multiplies each output channel by a row of weights — the core color cross-talk / hue character. |
| `white_balance.rgb_gains` | `[r, g, b]` | `[1, 1, 1]` | Color only. Per-channel multiplier. `>1` warms/brightens that channel. |
| `tone_curve_8bit` | list of `[x, y]` | `[[0,0],[255,255]]` | Tone mapping in 0–255 space (interpolated). Lift the toe to fade shadows, pull the shoulder to roll off highlights. |
| `look.contrast_pct` | number (%) | `0` | S-contrast around mid-grey. `+` increases contrast, `-` flattens. |
| `look.lift` | number | `0.0` | Adds a constant (raises/lowers the black point). Small values, e.g. `-0.02`. |
| `look.gain` | number | `1.0` | Multiplies the whole image (overall exposure). |
| `scanner_adjustments.gamma` | number | `1.0` | Midtone gamma. `>1` brightens midtones, `<1` darkens. |
| `scanner_adjustments.highlights` | number (%) | `0` | `+` lifts highlights, `-` compresses them. |
| `scanner_adjustments.shadows` | number (%) | `0` | `+` lifts shadows, `-` deepens them. |
| `scanner_adjustments.saturation_pct` | number (%) | `100` | Color only. `100` = unchanged, `120` = +20% saturation, `0` = grayscale. |
| `grain.intensity` | number `0`–~`1` | `0.0` | Midtone-weighted film grain. `0.3`–`0.5` is typical; `0` disables. |

Notes:

- **Tone curve** points are `[input, output]` from 0 to 255 and are linearly
  interpolated, then normalized internally to 0–1. The first/last points set the
  black/white endpoints.
- **Color matrix** is applied as `out = image @ matrix.T`. Start from the identity
  matrix and nudge off-diagonal terms by `±0.01`–`0.03` to shift hues subtly.
- For **B&W presets**, set `monochrome: true`, provide a `mono_mixer`, set
  `color_matrix: null`, and `saturation_pct` is ignored (the image is already
  gray). See [`ilford_hp5_plus.json`](FilmPresets/ilford_hp5_plus.json).

### 4. Iterate

There's no build step. Edit the JSON, save, and **restart the app** (presets are
loaded once at startup). Pick your stock from the dropdown to see the result. Work
in small increments — a `±5` change to `contrast_pct` or `±0.02` to a matrix term
is usually visible.

If a preset fails to load (invalid JSON, wrong types), the app shows a "Presets
Unavailable" warning and the dropdown falls back to just **None**. Re-check the
file with a JSON validator if that happens.

## Tuning the Frontier base profile

[`_frontier_base.json`](FilmPresets/_frontier_base.json) is the shared layer applied
**beneath every film stock**. Its job is to take NegPy's flat/log 16-bit TIFF and
expand it back to a normal-looking, full-range image *before* any film look is
applied. Get this right once and every preset benefits; get it wrong and every
preset will look washed out or crushed.

> **Important:** only the `input_transform` block is read by the renderer. The
> other blocks in this file (`frontier_defaults`, `base_look`, `confidence`,
> `source`) are documentation and have **no effect** on the output. If you want to
> change the base look, change `input_transform`.

### The `input_transform` block

```json
"input_transform": {
  "auto_levels": true,
  "per_channel": false,
  "black_clip_pct": 0.1,
  "white_clip_pct": 0.1,
  "delog_strength": 0.25,
  "gamma": 1.25
}
```

Stages run top to bottom:

| Field | Type | What it does | Tuning guidance |
|-------|------|--------------|-----------------|
| `auto_levels` | bool | Stretches the real black/white points back to full range. | Leave `true` for flat scans; set `false` only if your scans are already full-range. |
| `per_channel` | bool | When `true`, auto-levels each RGB channel independently (removes color casts but can shift white balance). When `false`, uses a shared luma range (preserves color). | Keep `false` for NegPy exports unless you specifically want aggressive per-channel neutralization. |
| `black_clip_pct` | number (%) | Percentile of darkest pixels clipped to black. | Higher = deeper, contrastier blacks. Lower = lifted/brighter shadows. Typical `0.05`–`0.5`. |
| `white_clip_pct` | number (%) | Percentile of brightest pixels clipped to white. | Higher = brighter highlights (more pixels pushed to white). Typical `0.05`–`0.5`. |
| `delog_strength` | number `0`–`1` | Blends in an S-curve to restore contrast lost in the flat scan. | More = punchier but darker below mid-grey. If images come out too dark/contrasty, **lower this first**. |
| `gamma` | number | Main exposure/brightness dial applied after de-log. | `>1` brightens midtones, `<1` darkens. This is the knob to reach for if everything is too dark or too bright. |

### Recommended tuning order

1. **Brightness too dark/light overall?** Adjust `gamma` (e.g. `1.25` → `1.4` to
   brighten).
2. **Too flat or too contrasty?** Adjust `delog_strength` (lower to flatten/lighten
   shadows, raise for more punch).
3. **Blacks not black / highlights not white?** Nudge `black_clip_pct` and
   `white_clip_pct` (small steps — these clip real data).
4. **Color cast across the whole roll?** Consider `per_channel: true`, but re-check
   your stocks afterward since it changes the starting white balance.

Changes here affect **all** presets, so tune against a few representative frames
(a high-key shot, a low-key shot, and a neutral mid-tone one) and restart the app
to apply. If you only want to change one stock's look, edit that preset's
`scanner_adjustments`/`look` instead of the base.

## Sidecar files

Edits are stored next to each image as a sidecar:

```
my_scan.tiff            ← your original (never modified)
my_scan.tiff.stockpot.json   ← saved edit state
```

The sidecar embeds the schema version, the full film-stock preset, the full base
profile, and your operator adjustments. Deleting the sidecar (or clearing it from
the right-click menu) restores the image to its default flat state.

## Project layout

```
FilmStockpot/
├── FilmPresets/              # Film-stock preset JSON + index + base profile
├── src/film_stockpot/
│   ├── app.py                # Application entry point
│   ├── sidecar.py            # Per-image edit sidecar read/write
│   ├── image/
│   │   ├── io.py             # Load/save 16-bit TIFF ↔ float32 RGB
│   │   ├── tiff_loader.py    # TIFF → QImage for display
│   │   ├── pipeline.py       # Film-stock emulation pipeline
│   │   ├── scanner.py        # Frontier-style operator adjustments
│   │   └── folder.py         # TIFF discovery
│   ├── presets/loader.py     # Preset and base-profile loading
│   └── ui/                   # PyQt6 main window, panels, widgets, workers
└── tests/                    # Pytest suite
```

## Development

Install with development tools (pytest):

```bash
uv sync --dev
```

Run the test suite:

```bash
uv run pytest
```

Add a dependency:

```bash
uv add <package>          # runtime
uv add --dev <package>    # development
```

## License

No license has been specified for this project yet. Until one is added, all rights
are reserved by the author.
