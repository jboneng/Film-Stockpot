# Ilford Delta 3200 JSON Research Notes

## What can be stated confidently

For a preset in your schema, the most solidly supported facts about **Ilford Delta 3200 Professional** are these: it is a **modern panchromatic black-and-white professional negative film**, it uses **core-shell crystal technology**, it is intended for **fast action and low-light photography**, and it is sold in **135-36 and 120** formats. The current film-listing summary available through Wikipedia’s sourced product index describes Delta 3200 exactly that way, and the same source cites an upstream Ilford technical-download URL for this stock. citeturn36view0turn36view2

The most important technical distinction is speed. Delta 3200 is widely marketed as “3200,” but the accessible source trail points back to Ilford’s own technical information stating that its **ISO speed is 1000/31°**, while the film is designed to be used at higher **exposure indexes such as EI 3200** and pushed further when needed. That ISO-versus-EI distinction appears consistently in the Delta 3200 summaries and in a film-speed reference that lists Delta 3200 at **1000/31°** rather than 3200/36°. citeturn4view0turn26search1turn41search2

Historically, Delta 3200 was introduced in **1998** and replaced Ilford’s older **HPS** high-speed film line. That matters for your metadata because it helps place the stock aesthetically: Delta 3200 belongs to Ilford’s newer Delta family rather than the older HP/HPS look. citeturn4view0turn26search3

I also used your uploaded **Fujifilm 400** preset as the house-style example for optional fields such as `exact_variant`, `preset_family`, `film`, `notes`, `confidence`, and `source`, so the draft below follows that shape rather than only the minimum renderer-required schema. fileciteturn0file0

## What is still missing from the accessible public record

There is good evidence that an **official Ilford technical sheet** for Delta 3200 exists or existed as a downloadable Ilford file. In the accessible source trail, Wikipedia’s film list points citation 107 to an Ilford `amfile` download URL specifically for Delta 3200, and attempting to follow that link through the browser tool resolves only to a cache-miss error rather than the document itself. In other words, the upstream technical PDF is identifiable, but I could not directly read it here. citeturn36view2turn37view0

That limitation matters because it means I could **not independently verify** fine-grained datasheet numbers such as **RMS granularity, resolving power, characteristic-curve coordinates, reciprocity tables, or spectral-sensitivity graphs** from a primary source in this session. Given your format, that means the metadata fields for those items should either be **omitted**, set conservatively, or explicitly marked as **inferred** rather than “specified.” citeturn36view2turn37view0

So the right way to think about the JSON below is: **metadata where the source trail is strong, render settings where the source trail supports the direction but not the exact numbers**. That is especially true for `tone_curve_8bit`, `scanner_adjustments`, `look`, and `grain_extraction`, because Ilford publishes film behavior, not a scanner-to-output transform for your Frontier-style rendering pipeline. The official information tells us what kind of film Delta 3200 is and how it is intended to be exposed; it does not directly provide your renderer’s control values. citeturn36view0turn4view0

## How that translates into your render model

Because Delta 3200 is a **black-and-white panchromatic negative film**, the preset should definitely use `monochrome: true`, a `null` `color_matrix`, and a valid `mono_mixer`. The safest starting point for `mono_mixer` is still close to a standard panchromatic luminance mix rather than an aggressively stylized channel weighting, because the accessible sources clearly identify the stock as panchromatic but do not expose the underlying spectral curve here. citeturn36view0turn41search1

The hardest choice is the target “look,” because Delta 3200 is not a single-look film in practice. The official summary trail says it is a real **ISO 1000** stock that is **suitable for EI 3200 or higher**, which means a preset anchored to EI 1000 will not look like the scans most photographers mean when they say “Delta 3200,” while a preset anchored to EI 3200 will usually be grainier, denser, and a bit more forceful in the mids. For that reason, I recommend building the main preset around the **common EI 3200 scan look**, not the flatter EI 1000 one. citeturn4view0turn36view0turn26search1

That leads to a sensible renderer translation: a **moderate-contrast monochrome curve**, slight **highlight compression** to keep push-processed highlights from going chalky, slightly **deeper shadows** to avoid washed-out scans, and **stronger grain extraction** than you would use on a slower stock. None of those numeric values are directly published by Ilford in the accessible sources, but they are the most defensible translation of a documented high-speed, low-light, push-oriented panchromatic stock into the controls your renderer actually uses. citeturn36view0turn4view0

## Ready-to-use JSON draft

The JSON below is the version I would start testing first. It is intentionally conservative about unsupported metadata and explicit about confidence.

```json
{
  "schema_version": "1.0",
  "id": "ilford_delta_3200",
  "name": "Ilford Delta 3200",
  "manufacturer": "Ilford Photo",
  "exact_variant": "DELTA 3200 PROFESSIONAL",
  "type": "black_and_white_negative",
  "category": "professional",
  "preset_family": "ilford_professional",
  "monochrome": true,
  "film": {
    "base_iso": 1000,
    "practical_ei_range": [1000, 6400],
    "recommended_ei": 3200,
    "color_bias": "neutral monochrome",
    "grain": {
      "metric": "qualitative",
      "value": "pronounced"
    }
  },
  "pipeline": {
    "tone_curve_8bit": [[0, 0], [24, 14], [64, 58], [128, 132], [192, 212], [255, 248]],
    "scanner_adjustments": {
      "highlights": -8,
      "shadows": -4,
      "gamma": 1.03
    },
    "look": {
      "contrast_pct": 8,
      "lift": -0.012,
      "gain": 1.0,
      "color_matrix": null,
      "mono_mixer": [0.31, 0.58, 0.11]
    },
    "grain_extraction": {
      "strength": 0.55,
      "radius": 1
    }
  },
  "notes": "Modern panchromatic high-speed professional B&W film using core-shell crystal technology. Official ISO speed is 1000/31°, but the stock is commonly used at EI 3200 and above. This preset targets the common EI 3200 scan look rather than a flatter EI 1000 proofing look.",
  "confidence": {
    "base_iso": "specified",
    "practical_ei_range": "partly_inferred",
    "recommended_ei": "inferred_from_official_positioning",
    "grain": "inferred",
    "tone_curve_8bit": "inferred",
    "scanner_adjustments": "inferred",
    "look": "inferred",
    "grain_extraction": "inferred"
  },
  "source": "Research synthesis from Ilford-linked Delta 3200 references and the uploaded Fujifilm 400 schema example"
}
```

In that draft, the **source-backed parts** are the stock identity, its monochrome/panchromatic nature, the fact that it belongs in the professional Ilford/Delta family, its **ISO 1000** base speed, and the fact that a typical working target is **EI 3200 or higher**. The **inferred parts** are all renderer-facing numeric controls: the tone curve, mono mixer bias, scanner highlight/shadow treatment, and grain-extraction strength. citeturn36view0turn4view0turn41search1turn26search1

## Why these numbers are a good first pass

The tone curve is shaped to keep the stock from becoming either too flat or too brittle. Delta 3200 is documented as a high-speed modern panchromatic film intended for low light and push use, so a pure neutral curve would usually understate the way photographers actually scan and print it, while an aggressive S-curve would over-crush the shadows and blow the bright tones. The curve above therefore keeps a **firm black point**, a **moderately energetic midsection**, and a **softened shoulder**. That is an interpretation of the stock’s documented use-case rather than a direct copy of an official characteristic curve. citeturn36view0turn4view0

The `mono_mixer` is only slightly red-leaning compared with the canonical luma mix. That small shift is deliberate. Since the accessible sources confirm **panchromatic** behavior but do not expose the exact spectral-sensitivity graph here, a subtle move is safer than trying to simulate a strong red-sensitive or blue-sensitive bias that may not be warranted. citeturn36view0turn41search1

The `grain_extraction` setting is intentionally stronger than what you would use for a slower Ilford stock. Even though I could not verify an official granularity number from the upstream PDF in this session, the stock’s identity as a **very high-speed** film meant for **EI 3200 and beyond** strongly supports preserving more scan-carried grain texture rather than suppressing it. citeturn4view0turn36view0turn41search2

If you want a **truer ISO 1000** version rather than the common “Delta 3200 look,” the first edits I would make are simple: lower `contrast_pct` from **8** to about **4**, reduce `gamma` from **1.03** to **1.00**, ease `highlights` from **-8** to about **-4**, and lower `grain_extraction.strength` from **0.55** to about **0.40**. That recommendation follows directly from the stock’s documented ISO-1000 base speed and its separate marketing/use position as an EI-3200-and-up film. citeturn4view0turn26search1turn41search2

## What I would leave blank until you recover the actual Ilford sheet

If you want this preset to be as rigorous as your Fujifilm-style metadata example, I would **not fake** `resolving_power_lp_mm`, `curve_gamma`, `d_min`, `d_max`, reciprocity tables, or a numeric granularity figure until you can recover the actual Ilford technical PDF or another primary datasheet mirror. The accessible source trail proves that an official Ilford Delta 3200 technical file existed at a downloadable Ilford URL, but it was not directly readable here, so those fields should remain absent or explicitly uncertain for now. citeturn36view2turn37view0

So, in practical terms, you now have enough to build a **useful, honest preset**: the stock identity is well established, the monochrome pipeline settings are constrained by the film’s panchromatic high-speed character, and the remaining numeric render controls can be marked as **inferred starting points**. The single biggest thing that would improve this preset from “strong first draft” to “high-confidence emulation” would be access to the original Ilford technical sheet behind the Delta 3200 `amfile` reference. citeturn36view0turn36view2