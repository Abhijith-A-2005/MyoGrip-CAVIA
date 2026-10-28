Evaluation Package
The evaluation package processes session logs and produces trial metrics, summaries, questionnaire scores, statistics, quality reports, and figures.

From the repository root:
python -m pip install -e ".[eval,dev]"
python -m cavia.eval data/arbitration/sessions/ --out data/results/


For questionnaire scoring:
python -m cavia.eval data/arbitration/sessions/ --out data/results/ --questionnaires questionnaires.csv


Run tests with python -m pytest -q tests/eval.

See the evaluation guide for details and limitations.
