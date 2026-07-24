# ADR: Separation of screening from realistic simulation

Screening and realistic simulation are separate simulation levels. Screening can cheaply reject weak candidates, while realistic simulation will later account for execution assumptions, costs, and market microstructure. This separation prevents early research filters from being mistaken for tradable performance claims.
