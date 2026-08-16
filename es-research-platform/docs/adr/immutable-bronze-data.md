# ADR: Immutable bronze data

Bronze data will be treated as immutable source evidence. Later phases may create silver and gold derived datasets, but they must not mutate bronze inputs. Reproducibility manifests record source file hashes and row counts so derived data can be traced back to exact inputs.
