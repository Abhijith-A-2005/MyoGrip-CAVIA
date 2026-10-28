# CAVIA Evaluation Pipeline

## Purpose

The evaluation pipeline analyzes CAVIA session logs and produces trial-level metrics, participant-condition summaries, questionnaire scores, statistical summaries, quality reports, and figures.

It reads JSONL session logs without modifying the original files. Outputs are written to a separate directory.

## Installation

Run these commands from the repository root:

```bash
python -m pip install -e ".[eval,dev]"
python -m pytest -q tests/eval