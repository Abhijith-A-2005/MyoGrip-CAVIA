# Evaluation Verification

The evaluation test suite previously passed 20 tests. Re-run with:

```powershell
python -m pytest -q tests/eval
A synthetic session was processed successfully: 7 records, 1 valid trial, 0 malformed records, and 0 rest windows. Synthetic trial metrics included 2 seconds vision-lock time, 4 seconds selection time, and 10 seconds task time. These are software checks, not study results.

An offline EMG recording contained 71,000 samples with Counter, Channel1, and Channel2 columns and no missing values. This does not verify live-device acquisition or false-activation detection.

A previous full-suite run had 237 passed, 1 skipped, and 2 runtime child-process socket timeout failures in tests/runtime/test_detection_pause.py and tests/runtime/test_live.py.

Real participant logs, completed questionnaires, verified live-device EMG events, and C1/C2 support remain outstanding.
