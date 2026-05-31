# Batch 5A Review Report

> This report is machine-generated engineering review material. It is not human-approved.

## Artifact Summary

- Run ID: `lesson2`
- Method: `deterministic_content_map_skeleton_v1`
- Content units: `30`
- Topic groups: `9`
- Selected handout images: `15`
- Dropped handout-level candidates: `22`

## Input Artifact Health

- `status`: `success`
- `formal_non_smoke_inputs`: `True`
- `transcript_segment_count`: `1690`
- `visual_segment_count`: `27`
- `alignment_item_count`: `1690`
- `aligned_segment_count`: `1690`
- `unaligned_segment_count`: `0`
- `low_confidence_segment_count`: `0`
- `missing_keyframe_count`: `0`

## Source Hashes

- `raw_transcript`: `6f7f3360513ab9a78fc54cbe667a0db741118e73f5920c906dc928a72f1657d1`
- `visual_segments`: `3e2d0613dd1087ae98c4497141f1b72666b1deb163cbaa81d310b57c7be0cd8a`
- `frame_report`: `bb534eee2cec0878bb46824d7d0643a08f3967f591f2aab135fa4a2e81f1ce83`
- `alignment`: `8cfc5f5e5c9dc5fb3b4b3d20739f8dd01bed084aff8605743af5b0a39ae9b5c4`

## Time Coverage

- Start: `00:00:01`
- End: `01:19:27`

## Image Selection Summary

- Near-duplicate or density-control groups: `2`
- Units without a selected image: `15`
- Units with more than two candidate images: `1`

## Near-Duplicate Image Groups

- `image_group_001` `rapid_visual_burst`: keep `outputs\lesson2\assets\keyframes\keyframe_0017_t001360.000.jpg`; dropped `5` candidate(s).
- `image_group_002` `rapid_visual_burst`: keep `outputs\lesson2\assets\keyframes\keyframe_0025_t001960.000.jpg`; dropped `2` candidate(s).

## Dropped Candidate Keyframes

- `unit_002`: `outputs\lesson2\assets\keyframes\keyframe_0002_t000030.000.jpg` - `handout_image_density_limit`
- `unit_008`: `outputs\lesson2\assets\keyframes\keyframe_0009_t000630.000.jpg` - `handout_image_density_limit`
- `unit_011`: `outputs\lesson2\assets\keyframes\keyframe_0011_t000900.000.jpg` - `keyframe_already_selected_for_previous_unit`
- `unit_013`: `outputs\lesson2\assets\keyframes\keyframe_0015_t001340.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_013`: `outputs\lesson2\assets\keyframes\keyframe_0016_t001350.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_013`: `outputs\lesson2\assets\keyframes\keyframe_0018_t001370.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_013`: `outputs\lesson2\assets\keyframes\keyframe_0019_t001380.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_013`: `outputs\lesson2\assets\keyframes\keyframe_0020_t001390.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_016`: `outputs\lesson2\assets\keyframes\keyframe_0023_t001570.000.jpg` - `handout_image_density_limit`
- `unit_018`: `outputs\lesson2\assets\keyframes\keyframe_0026_t002000.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_019`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_020`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_021`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_022`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_023`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_024`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_025`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_026`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_027`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_028`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_029`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`
- `unit_030`: `outputs\lesson2\assets\keyframes\keyframe_0027_t002020.000.jpg` - `rapid_visual_burst_keep_one_representative`

## Automated Review Points

- Units without selected image: `unit_002, unit_008, unit_016, unit_019, unit_020, unit_021, unit_022, unit_023, unit_024, unit_025, unit_026, unit_027, unit_028, unit_029, unit_030`
- Units with too many image candidates: `unit_013`
- Long transcript with little visual change: `unit_006, unit_008, unit_009, unit_010, unit_014, unit_016, unit_017, unit_019, unit_020, unit_021, unit_022, unit_023, unit_024, unit_025, unit_026, unit_027, unit_028, unit_029`
- Visual change with little transcript: `none`

## Known Issues

- No operator-supplied known issues.

## Prompt Pack Summary

- Generated: `True`
- Path: `C:\Documents\GitHub-Projects\lecture-slide-transcript-agent\outputs\lesson2\audit\handout_prompt_pack.jsonl`
- Item count: `30`
- Schema: `handout_prompt_pack_v1`
- Purpose: manual review or future Batch 5B grounded generation. No model call was made.

## Human Review Checklist

- Check whether content units are too fragmented or too coarse.
- Check whether each selected screenshot supports the nearby transcript excerpts.
- Review near-duplicate groups and confirm that useful teaching states were not hidden.
- Review units without selected images and decide whether another representative is needed.
- Confirm that the handout skeleton is not mistaken for final polished notes.

## Next-Step Recommendation

Run an independent Validation Agent review and a human spot-check before proceeding to any LLM-backed generation stage.
