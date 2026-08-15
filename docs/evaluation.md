# Reproducible Evaluation

Evaluation date: 2026-08-14. Reproduce with `uv run sti-evaluate --output artifacts/evaluation`.

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

## llama.cpp explanation evaluation

The live OpenAI-compatible endpoint ran `gpt-oss-20b-UD-Q8_K_XL.gguf` through llama.cpp on
`0.0.0.0:8081`. Five difficulty-spaced catalog equations were checked against authoritative SymPy
solutions with a 384-token generation cap.

- Valid explanations: 4/5 (80%)
- Mean latency: 22.243 seconds
- Provider errors: one malformed/truncated response

This result supports the architectural decision that model explanations must remain optional. A
provider failure falls back to deterministic native hints and never affects correctness or scoring.
