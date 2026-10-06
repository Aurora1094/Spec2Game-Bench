# Current Stage: Rendering

Generate `rendering.py`.

The module must define:

```python
class GameRenderer:
    def render(self, state: GameState) -> pygame.Surface: ...
    def close(self) -> None: ...
```

- Import `GameState` through `.state`; do not import `.game` or `.main`.
- `render()` is read-only and returns a pygame Surface with exactly
  `{window_size}` pixel dimensions. Do not call `pygame.display.set_mode()`.
- Create reusable fonts and resources outside the per-frame drawing path.
- Every visible object, value, message, terminal state, and feedback element
  derives from the supplied state.
- Do not implement gameplay rules, input processing, an adapter, or a main
  loop.

# Locked Previous Module: state.py

SHA256: `{state_sha256}`

```python
{state_source}
```

# Public Scene and Interface Specification

{rendering_spec_sections}

# Public Visual Quality Requirements

- Use a clear visual hierarchy and keep players, goals, obstacles, status, and
  controls identifiable.
- Use coherent colors and shapes with sufficient contrast. Keep text readable,
  unclipped, and inside intended regions.
- Render complete, state-faithful feedback required by the public specification
  for movement, collisions, score, health, progression, victory, failure, and
  restart.
- Keep animation stable and coherent.
