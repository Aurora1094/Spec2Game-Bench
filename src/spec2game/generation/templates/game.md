# Current Stage: Game Rules

Generate `game.py`.

The module must define:

```python
class GameEngine:
    def __init__(self, seed: int = 0): ...
    def reset(self, seed: int = 0) -> dict: ...
    def action(self, command: dict) -> dict: ...
    def snapshot(self) -> dict: ...

    @property
    def state(self) -> GameState: ...
```

- Import project state only through `.state`; do not import pygame.
- Maintain one authoritative `GameState`.
- All input, time advancement, collisions, scoring, rule resolution, lifecycle
  changes, victory, failure, and restart pass through `action(command)`.
- `snapshot()` is read-only and uses the same complete state schema as
  `action()`; `reset(seed)` performs a complete deterministic reset.
- Do not implement drawing, pygame event polling, an adapter, or a main loop.

# Generic Action Command

`action(command)` accepts `keys_down`, `keys_up`, and `held_keys` as arrays of
lowercase key names; `mouse_position` as null or `[x, y]`;
`mouse_buttons_down` and `mouse_buttons_up` as arrays of positive integers; and
`dt` as nonnegative seconds. Edge events apply once. Held keys remain active
throughout `dt`. Empty input with positive `dt` advances time only.

# Locked Previous Module: state.py

SHA256: `{state_sha256}`

```python
{state_source}
```

# Relevant Public Game Specification

{game_spec_sections}

# Public Player Input and Controls

{d2_2_requirements}

# Public Core Rules and Mechanics

{d2_3_requirements}

# Public Game Flow and Progression

{d2_4_requirements}

# Public Goals, Feedback, and Termination

{d2_5_requirements}
