MyoGrip CAVIA — Evaluation Handover
Included
- Session-log loading and validation.
- Trial metrics and participant-condition summaries.
- Questionnaire scoring, statistics, figures, and quality reports.
- results.json output for future dashboard integration.
- Automated evaluation tests and documentation.
Run
python -m pip install -e ".[eval,dev]"
python -m pytest -q tests/eval
python -m cavia.eval data/arbitration/sessions/ --out data/results/


For questionnaire scoring, add --questionnaires questionnaires.csv.
Limitations
The available runtime supports C3 only. C1/C2 comparisons require additional support and observations. Verified live-device EMG events are needed to measure false activations. Real participant logs and questionnaires are required for research conclusions. Dashboard integration is handled separately.

Synthetic data verifies software behavior, not research hypotheses. Keep participant data out of Git.
