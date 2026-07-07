# Runner examples

## Standard experiment

```bash
scripts/run_full_cycle.sh \
  --auto-setup \
  --tag mar11 \
  --category normalization \
  --description "pre-attention RMSNorm" \
  --hypothesis "Moving normalization before attention will improve stability and BPB" \
  --diff-summary "apply RMSNorm before attention blocks"
```

## Forced GPU index

```bash
scripts/run_full_cycle.sh \
  --tag mar11 \
  --category attention \
  --description "smaller local window" \
  --hypothesis "A smaller local window may improve throughput without hurting BPB" \
  --diff-summary "WINDOW_PATTERN SSSL -> L" \
  --cuda-visible-devices 1
```

## Keep/reset manually

```bash
scripts/run_full_cycle.sh \
  --tag mar11 \
  --category simplification \
  --description "remove value embeddings" \
  --hypothesis "Removing value embeddings may simplify the model with no loss" \
  --diff-summary "disable value embedding path" \
  --no-auto-git-action
```
