# Current Stage: State Model

Generate `state.py`.

The module must define:

```python
class GameState:
    ...

def create_initial_state(seed: int = 0) -> GameState:
    ...

def state_to_dict(state: GameState) -> dict:
    ...
```

- Use only the Python standard library. Do not import pygame or another project
  module.
- Define all shared constants, enums, data classes, entity state, timers,
  counters, lifecycle fields, and configuration needed by later modules.
- `create_initial_state(seed)` constructs the exact deterministic initial game
  state.
- `state_to_dict(state)` returns a detached, complete, JSON-serializable
  representation without mutating `state`.
- Do not implement input processing, gameplay transitions, rendering, an
  adapter, or an interactive loop.

# Relevant Public Game Specification

{state_spec_sections}

# Public Game Objects and State Requirements

{d2_1_requirements}
