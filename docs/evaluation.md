# Reproducible Evaluation

Evaluation date: 2026-08-14. Reproduce with `uv run sti-evaluate --output artifacts/evaluation`.

The command writes `comparison.csv`, `trajectories.csv`, and `metadata.json`. Existing files with
those names in the output directory are replaced. Runs are deterministic for the same code, learner
count, and seed.

## Learner-policy simulation

The fixed seed is `20260814`, with 200 simulated learners and a maximum of 80 attempts per learner.
The simulation is a research harness, not evidence of classroom learning outcomes.

| Policy | Mean attempts to modeled mastery | Hints per solved problem | Accuracy |
|---|---:|---:|---:|
| Uniform random + sequential hints | 41.09 | 2.457 | 0.579 |
| BKT adaptive + mastery-driven hints | 24.27 | 5.735 | 0.462 |

The adaptive policy reaches the modeled threshold sooner while deliberately concentrating on weak
skills. Its higher hint consumption and lower within-session accuracy are visible tradeoffs, not
hidden by a single success metric. `comparison.csv`, `trajectories.csv`, and `metadata.json` contain
the exact generated data. An anonymized attempt-table CSV can be replayed with `--attempt-export`.

The replay CSV must contain `model_version`, `correct`, and `hint_count` columns. It produces grouped
descriptive statistics in `attempt_replay.csv`; it does not reconstruct BKT state or establish a
causal comparison.

## llama.cpp explanation evaluation

The live OpenAI-compatible endpoint ran `gpt-oss-20b-UD-Q8_K_XL.gguf` through llama.cpp on
`0.0.0.0:8081`. Five difficulty-spaced catalog equations were checked against authoritative SymPy
solutions with a 384-token generation cap.

- Valid explanations: 4/5 (80%)
- Mean latency: 22.243 seconds
- Provider errors: one malformed/truncated response

This result supports the architectural decision that model explanations must remain optional. A
provider failure falls back to deterministic native hints and never affects correctness or scoring.

## Interpretation limits

- Simulated learners follow assumptions encoded in the harness and are not substitutes for student
  observations.
- “Mastery” means crossing the configured BKT threshold, not independently measured knowledge.
- Accuracy and hint use are policy-dependent intermediate measures; lower accuracy can reflect
  intentional selection of weaker skills.
- The five-case explanation run is a smoke evaluation, not a broad quality benchmark.
- No identifiable learner data is included. A classroom study requires an approved consent,
  retention, and LGPD-compliance process.
