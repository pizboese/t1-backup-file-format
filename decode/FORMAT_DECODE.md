# Complete-decode scoreboard + notes

Live working doc for the campaign (branch `completeDecode`). The canonical, stable reference stays
`FORMAT.md` at the repo root — a finding moves there only once confirmed (sample rebuilds
byte-for-byte in `decode/test_decode.py` **and** parser reports the programmed ladder).

Status: ✅ DECODED (located + synthesized) · 🟡 PARTIAL (located, gaps) · ❌ UNDECODED.
Offsets are relative to the `steps` field unless noted. `(B1)` = decoded in backup-1
(`samples/20_backup1_params`, already canonical in `FORMAT.md`).

## Scoreboard — drives the work order (import-critical → Shape → Groove/Tonal → Modes/Routing)

### Shape
| Feature | Range | Status / location |
|---|---|---|
| Steps | 1–64, def 16 | ✅ `steps+0x00`; 64-B gate @ `run+0x0c` |
| Pulses (count) | 1–steps | ❌ value-byte (gate resolved; count unlocated) |
| Rotate | directional | ❌ |
| Cycles | 1–16, def 4 | ✅ `steps+0x14d`; per-cycle engine decoded |
| Division | note values; Free | ✅ `steps+0x2a` u16 + free-flag `steps+0x299` (B1) |
| Repeats | 0–48 (+∞) | ❌ |
| Ramp | directional | ❌ |
| Time (repeat spacing) | note values | ❌ |
| Pace | bipolar | ❌ |
| Voicing (amount) | continuous | ❌ |
| Style | poly 0–4 / mono 8–12 | ✅ `steps+0x13d` |
| Range | amount | ❌ |
| Phrase (shape+length) | 8 shapes; 1–64 bars | ❌ |

### Groove
| Feature | Range | Status |
|---|---|---|
| Velocity (track+step) | 0–127, 1:1 | ✅ `steps+0x7b`; lock id `0x0a` |
| Probability | bipolar | ✅ `steps+0x79` s8 (B1) |
| Sustain (track+step) | 0–127, def 64 | ✅ `steps+0xa5`; lock id `0x0e`; log law |
| Timing (swing) | bipolar, x1/x2/x4 | ✅ amount `steps+0xba` s8; sub `+0x146` (B1) |
| Delay | bipolar | ✅ `steps+0x13e` s8 (B1) |
| Accent (amount) | bipolar | ❌ |
| Groove (pattern+length) | 8 patterns; 1–64 bars | ❌ |

### Tonal
| Feature | Range | Status |
|---|---|---|
| Pitch (track+step+cycle) | absolute, C3=60 | ✅ header + locks + cycle overrides |
| Harmony | hysteretic | ❌ |
| Scale | presets + user | 🟡 `steps+0x40` (0–6 known); full table + user scales ❌ |
| Root | C–B (0–11) | ✅ `steps+0x13f` |

### Setup / Global
| Feature | Range | Status |
|---|---|---|
| Length (track loop) | 1/64–16 bar, ∞ | ✅ `steps+0x14b` enum 0–15 (B1) |
| Quantize (per-pattern) | bar divisions | ✅ pattern-trailer 4th byte (B1) |
| Channel | 1–16 | ✅ out-mask `steps+0xe4` |
| Output (internal routing) | per-track | 🟡 mask=ch; internal routing ❌ |
| Tempo (per-bank) | 24–280, def 120 | ✅ bank summary bytes 0–1 u16 LE (B1) |
| Random (amount/param) | variance | ❌ amount-byte unlocated (buffers cloned) |
| Rate | advance speed | ❌ |

### Tracks / Modes
| Feature | Status |
|---|---|
| Track Mode Note/CC/FX | ❌ mode flag + CC#/value + FX config |
| Mute / enable | ❌ |

### Zone-A random runs (16 sequenced params, one 17-B run each — bounds the decode)
Located: steps`+0x00`, pitch`+0x55`, velocity`+0x7b`, sustain`+0xa5`, div`+0x2a`,
scale`+0x40`, channel`+0xe4`, root`+0x13f`.
**Unidentified runs** ↔ the 8 ❌ sequenced params:
`+0x16, +0x68, +0x91, +0xbb, +0xd0, +0xfa, +0x110, +0x126`.

## Campaign backups (fill as acquired → `decode/samples/NN_*`)
| # | Theme | Params targeted | Sample | Status |
|---|---|---|---|---|
| 1 | import-critical timing/feel | Timing/Delay/Length/Quantize/FreeDiv/Probability + per-bank Tempo | `samples/20_backup1_params` (root) | ✅ done (canonical) |
| 2 | Shape + Repeater | Pulses, Rotate, Repeats, Ramp, Time, Pace, Range, Phrase, Voicing-amt | — | pending backup |
| 3 | Groove + Tonal | Accent, Groove, Harmony, full Scale table + user scale | — | pending backup |
| 4 | Modes + Routing + Global | Note/CC/FX mode, CC#/value, FX, Output routing, Mute, Random amt/Rate | — | pending backup |

## Per-field decode log
(Append a dated entry per field as it flips to ✅: offset, kind, how isolated, sample, rebuild proof.)
