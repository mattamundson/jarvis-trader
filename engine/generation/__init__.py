"""Strategy generation engine.

Closes the loop on the existing world-class validator (gate v2 + WFO + MC + DSR):
mines the corpus of past verdicts into a structured, append-only edge ledger, then
ranks the next experiments to run by their empirical prior -- biasing toward the
region of the (family x instrument x regime-conditioning) space where edges have
actually survived, and away from the graveyard.

Read-only with respect to the verdict corpus. Produces:
  engine/data/edge_ledger.jsonl      -- append-only structured verdict history
  engine/data/next_experiments.json  -- ranked candidate experiments
"""
