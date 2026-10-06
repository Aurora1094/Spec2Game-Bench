# Current Stage: Adapter and Interactive Entry Point

Generate `main.py`.

The module must define:

```python
class GameBenchAdapter:
    def init(self, seed: int = 0) -> dict: ...
    def action(self, command: dict) -> dict: ...
    def snapshot(self) -> dict: ...
    def render(self) -> pygame.Surface: ...
    def close(self) -> None: ...

def create_gamebench_adapter(seed: int = 0) -> GameBenchAdapter:
    ...

def main() -> None:
    ...

if __name__ == "__main__":
    main()
```

- Use `GameEngine` as the only gameplay authority and `GameRenderer` as the
  only drawing implementation. Do not duplicate state, rules, collisions, or
  drawing logic.
- `init`, `action`, and `snapshot` delegate to the engine. `render()` passes the
  real engine state to the renderer. `close()` releases pygame resources
  without terminating the evaluator process.
- `create_gamebench_adapter(seed)` returns an initialized adapter.
- The interactive loop initializes pygame, creates the `{window_size}` display,
  translates pygame events into the generic action command, uses the same
  adapter action/render paths as evaluation, refreshes at a fixed rate, handles
  window close cleanly, and starts only under the required `__main__` guard.

# Locked Public APIs

{project_api_summary}

# Public Player Interaction Specification

{interaction_spec_section}
