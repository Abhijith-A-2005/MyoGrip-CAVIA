# Evaluation Requirements Traceability

| Requirement | Implementation | Status |
|---|---|---|
| Trial segmentation and metrics | `src/cavia/eval/trials.py` | Implemented |
| Aggregation and participant-condition summaries | `aggregate.py` | Implemented |
| Questionnaire scoring | `questionnaires.py` | Implemented; real responses needed |
| Statistical analysis | `stats.py` | Implemented where data permit |
| Figures F1–F8 | `figures.py` | Implemented |
| Input validation | `loader.py` | Implemented |
| Evaluation tests | `tests/eval/test_evaluation.py` | Run tests before merging |
| Dashboard integration | Separate dashboard work | Handled separately |
| Live EMG false-activation validation | Verified device events | Pending |
| C1/C2 comparisons | Runtime and study data | Not currently supported |
| Research conclusions | Real participant study | Not established |

Synthetic tests verify software behavior, not research hypotheses.
