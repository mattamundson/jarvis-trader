"""
JARVIS TRADER — Strategy Discovery Package
===========================================

This package provides two orthogonal paths to strategy candidate generation.
Both paths produce StrategyHypothesis objects that feed gate v2 for validation
before any paper-trading routing occurs.

Paths:

1. LLM-driven (ResearchAgent) — `engine/agents/research_agent.py`
   Enabled via ENABLE_RESEARCH_AGENT=1. Uses Anthropic Claude Haiku to generate
   human-readable strategy hypotheses from market context and feature signals.

2. RL-driven (PPO training loop) — `engine/strategies/rl_train.py`
   Enabled via ENABLE_RL_STRATEGY_DISCOVERY=1 (default: 0, OFF).
   Runs a gymnasium-compatible trading environment through stable-baselines3 PPO,
   converting the learned policy into a StrategyHypothesis via policy_to_hypothesis().

The RL path is a TRAINING-TIME tool only. It does not route orders, does not
touch engine/risk/, and is completely decoupled from the live pipeline. Policies
are saved to engine/data/rl_policies/ and hypotheses to
engine/data/research_hypotheses/<date>/.

Both hypothesis types are structurally identical (StrategyHypothesis schema) so
gate v2 evaluates them with the same PF / p_edge / MC / DSR thresholds regardless
of origin.

Submodules:
    rl_config       -- Constants, hyperparameters, action space, reward config
    rl_environment  -- TradingEnvironment (gymnasium.Env subclass, 23 features)
    rl_agent        -- RLTradingAgent (PPO wrapper, safety contract on predict())
    rl_trainer      -- RLTrainer (async orchestrator, walk-forward support)
    rl_train        -- train_ppo() and policy_to_hypothesis() (synchronous entry points)
    rl_env          -- TradingEnvMES alias + minimal factory for the RL discovery loop
    registry        -- Strategy registry (builtin + generated + RL-discovered)
    discovery_loop  -- Automated discovery loop driver

Gate v2 thresholds (from engine/config.py and GATE_V2_ENFORCE_ROUTING):
    pf_ci_lower >= 1.10
    p_edge      >= 0.95
    mc_95th_dd  <= 5% (7% for ALT routing on $50K+)
    dsr         >= 0.10

Safe default: ENABLE_RL_STRATEGY_DISCOVERY=0.  Set to 1 and install
stable-baselines3 before running training.  See
docs/runbooks/RL_STRATEGY_DISCOVERY_RUNBOOK.md for the full procedure.
"""
