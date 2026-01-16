# Scripts Directory

This directory contains benchmarking and debugging scripts for the DMAF project.

## Benchmarking Scripts

These scripts are **NOT part of the unit test suite** - they perform slow, comprehensive analysis for system tuning and validation.

### `benchmark_backends.py`

Compare face recognition backends (face_recognition vs insightface).

**What it tests:**
- **TPR (True Positive Rate)**: LOOCV accuracy on known people
- **FPR (False Positive Rate)**: Unknown people rejection rate
- **Performance**: Model load time, encoding speed

**Usage:**
```bash
# Benchmark both backends (comprehensive)
python scripts/benchmark_backends.py

# Benchmark single backend
python scripts/benchmark_backends.py --backends insightface

# Skip slow LOOCV test
python scripts/benchmark_backends.py --skip-loocv

# Custom paths
python scripts/benchmark_backends.py \
    --known-people data/known_people \
    --unknown-people data/unknown_people
```

**Runtime:** 2-5 minutes per backend (depends on dataset size)

**Expected Results:**
- **insightface**: ~77% TPR, 0% FPR, ~3s load, ~50ms encode
- **face_recognition**: ~82% TPR, ~11% FPR, ~2s load, ~600ms encode

### `benchmark_augmentation.py`

Compare image augmentation strategies for recognition accuracy.

**What it tests:**
- **Baseline (none)**: No augmentation
- **flip_only**: Horizontal flip only
- **brightness**: Brightness variations
- **rotation**: Small angle rotations
- **conservative**: Flip + slight brightness
- **aggressive**: All augmentations combined

**Usage:**
```bash
# Benchmark all strategies
python scripts/benchmark_augmentation.py

# Benchmark specific strategies
python scripts/benchmark_augmentation.py --strategies none flip_only

# Custom parameters
python scripts/benchmark_augmentation.py \
    --tolerance 0.35 \
    --det-thresh 0.3 \
    --min-face-size 60
```

**Runtime:** 1-3 minutes per strategy

**Expected Results:**
- Augmentation typically improves TPR by 5-10% absolute
- Best strategy varies by dataset (usually flip_only or conservative)

## Debugging Scripts

### `debug_missed_detections.py`

Analyze missed face detections and false positives using production settings.

**What it does:**
- **Phase 1**: Visualizes all detected faces in known_people images
- **Phase 2**: Runs LOOCV and identifies all missed detections
- **Phase 3**: Tests unknown people for false positives (FPR)

**Usage:**
```bash
# Full analysis with visualizations
python scripts/debug_missed_detections.py --config config.yaml --output-dir debug_factory

# Custom detection thresholds (lower = detect more faces)
python scripts/debug_missed_detections.py --det-thresh-known 0.3 --det-thresh-test 0.35

# Skip Phase 3 FPR testing
python scripts/debug_missed_detections.py --unknown-people-dir /dev/null
```

**Note:** The script uses separate detection thresholds:
- `--det-thresh-known`: For loading known_people images (default: 0.3, more permissive)
- `--det-thresh-test`: For test images during LOOCV and FPR testing (default: from config)

**Runtime:** 30-60 seconds (with caching)

**Output:**
- `debug_factory/1_detection/`: Detection phase visualizations (all faces with scores)
- `debug_factory/2_recognition/`: Recognition phase visualizations (matches + scores)
- `debug_factory/3_false_positives/`: False positive visualizations (only errors)

**Typical Issues:**
- **No face detected**: Face too small, bad angle, or detection threshold too high (try lowering det_thresh_known or det_thresh_test)
- **Wrong match**: Insufficient training data, tolerance too high
- **False positive**: Unknown person matched - tolerance too high or insufficient diversity

## When to Use Each Script

| Task | Script | Runtime |
|------|--------|---------|
| Choose backend (insightface vs face_recognition) | `benchmark_backends.py` | 5-10 min |
| Tune augmentation strategy | `benchmark_augmentation.py` | 5-15 min |
| Debug specific missed detections | `debug_missed_detections.py` | <1 min |
| Optimize detection/tolerance thresholds | `debug_missed_detections.py` with params | <1 min |
| Measure production FPR | `debug_missed_detections.py` with unknown_people | <1 min |

## Why Not in Test Suite?

These scripts are **benchmarks**, not **unit tests**:

- **Unit tests** verify functionality (fast, run every commit)
- **Benchmarks** measure performance (slow, run periodically for tuning)

Running benchmarks on every commit would:
- Slow down development (5-15 minutes vs 10 seconds)
- Cause CI timeouts
- Waste compute resources
- Mix testing concerns (correctness vs performance)

## Tips

1. **Run benchmarks before major releases** to validate no regression
2. **Use debug script iteratively** when tuning detection parameters
3. **Save benchmark results** in IMPLEMENTATION_STATUS.md for comparison
4. **Test with real data** - synthetic test data doesn't reveal real-world issues

## See Also

- `tests/` - Unit test suite (fast, runs on every commit)
- `IMPLEMENTATION_STATUS.md` - Development progress tracking
- `deploy/README.md` - Cloud deployment guide
