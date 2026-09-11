---
{
  "checkpoints": [
    {
      "desc": "Dimension D2.1 functional requirements",
      "id": "d2_1",
      "weight": 1
    },
    {
      "desc": "Dimension D2.2 functional requirements",
      "id": "d2_2",
      "weight": 1
    },
    {
      "desc": "Dimension D2.3 functional requirements",
      "id": "d2_3",
      "weight": 1
    },
    {
      "desc": "Dimension D2.4 functional requirements",
      "id": "d2_4",
      "weight": 1
    },
    {
      "desc": "Dimension D2.5 functional requirements",
      "id": "d2_5",
      "weight": 1
    }
  ],
  "difficulty": "hard",
  "evaluation": {
    "d2": {
      "checkpoint_jsonl": "checkpoints.jsonl"
    },
    "protocol_version": 4,
    "seed": 17
  },
  "game_name": "Pipe Connection Puzzle",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      600,
      800
    ]
  },
  "schema_version": 1,
  "family_slug": "pipe_connection",
  "variant_id": "var05",
  "instance_id": "pipe_connection_var05"
}
---

# Game Specification

## Game Name

Pipe Connection Puzzle

---

# 1. Game Overview

Pipe Connection Puzzle is a logic puzzle and spatial connection game. The player rotates different pipe types within a fixed 6 × 6 grid so that water from a fixed Source reaches both Sinks through valid pipe connections.

A successful solution must satisfy all of the following:

- Both Sinks are reached from the Source.
- Water does not enter the fixed Leak cell.
- No Source-reachable outlet points outside the board.
- No Source-reachable outlet points toward a Block.
- No Source-reachable outlet points toward an adjacent pipe without the required reverse connection.

The fixed Leak is located at `(2,0)`.

The player may perform at most 30 successful pipe rotations. Each valid rotation increases Moves by 1.

When the player is satisfied with the configuration, pressing Space submits the current solution and runs a complete water-flow check from the Source.

Reaching 30 Moves does not automatically cause Failure. It only prevents further pipe rotation. The player may still press Space to submit the current configuration.

A custom rule is that reaching both Sinks is not sufficient by itself. Every outlet actually reached by water from the Source must also form a valid connection.

Each independent invalid reachable outlet contributes exactly 1 Leak and displays a red X at that outlet.

The game uses one fixed map and has no countdown.

It does not include random maps, multiple levels, Score, Lives, items, hints, automatic solving, pipe dragging, pipe swapping, adding or deleting pipes, undo, or increasing difficulty.

---

# 2. Game Scene & Interface

The game window is 600 × 800 px and uses a vertical layout. From top to bottom, it is divided into:

1. Top information area: 600 × 100 px
2. Main gameplay area: 600 × 600 px
3. Bottom instruction area: 600 × 100 px

## 2.1 Top Information Area

The top information area displays:

- `Moves: X/30` at `(30, 35)`
- `Water: Off` or `Water: On` at `(230, 35)`
- `Leaks: X` at `(430, 35)`

All three use a font size of 32 px and must remain clearly readable without overlapping.

At the start of the game:

`Moves: 0/30`

`Water: Off`

`Leaks: 0`

Leaks is not calculated continuously during editing. It is calculated only after Space is pressed and the submitted configuration is evaluated.

## 2.2 Main Gameplay Area

The main gameplay area contains the fixed 6 × 6 pipe board.

Board properties:

- Cell size: 80 × 80 px
- Board size: 480 × 480 px
- Top-left coordinate: `(60, 160)`
- Bottom-right coordinate: `(540, 640)`
- Rows: 0–5
- Columns: 0–5

The board uses a light-gray background.

Ordinary pipe cells use dark-gray backgrounds with lighter borders.

Pipe channels:

- Width: 24 px
- Drawn from the cell center toward the midpoint of each connected edge

For example:

- `SH`: center → E and W
- `SV`: center → N and S
- `CNE`: center → N and E
- `TNES`: center → N, E, and S

## 2.3 Special Cells

The Source:

- Position: `(0,0)`
- Type: `SRC-E`
- Main color: green
- Center label: black `S`
- Fixed visible outlet: E
- Cannot rotate

Both Sinks:

- Positions: `(0,5)` and `(5,5)`
- Type: `SNK-W`
- Main color: yellow
- Center label: black `T`
- Fixed visible interface: W
- Cannot rotate

The Leak:

- Position: `(2,0)`
- Red background
- Black `!`
- No ordinary pipe channel
- Cannot rotate

Blocks:

- Gray cells
- No pipe channel
- No text or symbol
- Cannot rotate

The cell `(3,2)`, which is the Leak position in the base map, is an ordinary rotatable `CSW` Corner Pipe in this version.

## 2.4 Water & Leak Visualization

After Space is pressed, pipe channels actually reached by water are highlighted in blue.

If a reached outlet is invalid:

- The pipe segment from the cell center to that outlet remains blue.
- A red X is overlaid near the corresponding cell edge.

The red X does not replace the blue water highlight.

Each independent invalid outlet displays its own red X.

Only Source-reachable pipe channels are highlighted. Isolated pipes that are not reached by water remain in their normal visual state.

## 2.5 Bottom Instruction Area

During `editing`, the bottom area displays:

`Click pipe to rotate Press Space to run water`

`Connect source to all sinks Restart: R`

Both lines use a font size of 22 px and should be centered.

During `won`:

`Puzzle Solved!`

`Press R to Restart`

During `failed`:

`Failed`

`Press R to Restart`

`Puzzle Solved!` and `Failed` use a font size of 40 px.

`Press R to Restart` uses a font size of 28 px.

---

# 3. Game Objects & States

The main game objects and state variables include the Source, Sinks, Straight Pipes, Corner Pipes, T Pipes, Cross Pipes, Leak, Blocks, Moves, Water, Leaks, Sink reached states, and game state.

Directions use:

- N: North
- E: East
- S: South
- W: West

## 3.1 Source & Sinks

There is exactly one Source:

- Position: `(0,0)`
- Type: `SRC-E`
- Connection: E only

There are exactly two Sinks:

- Sink 1: `(0,5)`
- Sink 2: `(5,5)`
- Type: `SNK-W`
- Valid interface: W only

When water enters a Sink through its valid W interface:

- Mark that Sink as `reached`.
- Stop water propagation at that Sink.

Water does not pass through a Sink.

## 3.2 Pipe Types

Straight Pipe:

- `SH`: E/W
- `SV`: N/S
- Rotatable

Corner Pipe:

- `CNE`: N/E
- `CES`: E/S
- `CSW`: S/W
- `CWN`: W/N
- Rotatable

T Pipe:

- `TNES`: N/E/S
- `TESW`: E/S/W
- `TSWN`: S/W/N
- `TWNE`: W/N/E
- Rotatable

Cross Pipe:

- Connects N/E/S/W
- Not rotatable

The fixed map does not currently contain a Cross Pipe, but the type remains part of the game rules.

## 3.3 Leak & Blocks

The fixed Leak is at:

`(2,0)`

If Source-reachable water flows directly into the Leak cell:

- That outgoing connection contributes exactly 1 Leak.
- Propagation stops for that connection.
- The Leak must not be counted again because the Leak cell lacks an ordinary reverse pipe connection.

The cell `(3,2)` is not a Leak in this version.

It contains a rotatable `CSW` Corner Pipe.

Blocks have no connection directions.

Water cannot enter or pass through them.

## 3.4 Moves

Moves starts at:

`0`

Each successful 90° clockwise rotation of a rotatable pipe:

`Moves += 1`

Maximum:

`Moves = 30`

When Moves reaches 30:

- Further rotations are disabled.
- The game remains in `editing`.
- Space may still be used to submit.

## 3.5 Water & Leaks

Water starts as:

`Off`

After Space is pressed during `editing`:

`Water = On`

Leaks starts at:

`0`

Leaks is calculated only during the submitted water-flow check.

Each independent invalid Source-reachable outlet contributes exactly 1.

## 3.6 Game State

The game contains three states:

- `editing`
- `won`
- `failed`

During `editing`, the player may rotate eligible pipes while Moves < 30 and may press Space to submit.

The game enters `won` when:

- Sink 1 is reached.
- Sink 2 is reached.
- Leaks = 0.

The game enters `failed` when:

- At least one Sink is not reached, or
- Leaks > 0.

Both `won` and `failed` are terminal for the current run.

---

# 4. Player Interaction

The player uses the left mouse button, Space, and R.

## 4.1 Pipe Rotation

While the game is `editing` and Moves < 30, left-clicking a Straight Pipe, Corner Pipe, or T Pipe rotates it 90° clockwise.

Each successful rotation:

- Immediately updates the pipe orientation.
- Increases Moves by 1.

The `CSW` Corner Pipe at `(3,2)` is an ordinary rotatable pipe.

Clicking Source, Sink, Leak at `(2,0)`, Block, or Cross Pipe:

- Does not rotate anything.
- Does not change Moves.

All rotatable pipes may be rotated, including pipes that are not part of the final correct water route.

## 4.2 Rotation Cycles

Straight Pipe:

`SH ↔ SV`

Corner Pipe:

`CNE → CES → CSW → CWN → CNE`

T Pipe:

`TNES → TESW → TSWN → TWNE → TNES`

When Moves reaches 30, clicking rotatable pipes has no effect and Moves remains `30/30`.

## 4.3 Submission

Space is effective only in `editing`.

When Space is pressed:

1. Set Water to On.
2. Stop further editing.
3. Run the complete Source-based water-flow check.
4. Calculate Leaks.
5. Record both Sink `reached` states.
6. Enter either `won` or `failed`.

A failed submission cannot be edited and resubmitted within the same run.

The player must press R to restart.

## 4.4 Restart

R is effective in `editing`, `won`, and `failed`.

Restart:

- Restores the V6 fixed map and all pipe initial orientations.
- Restores the Leak to `(2,0)`.
- Restores the `CSW` Corner Pipe to `(3,2)`.
- Resets Moves to 0.
- Resets Water to Off.
- Resets Leaks to 0.
- Clears both Sink `reached` states.
- Clears blue water highlights.
- Clears all red X marks.
- Returns the game state to `editing`.

---

# 5. Core Rules & Mechanics

## 5.1 Fixed Map

The game uses this fixed 6 × 6 initial map:

```text
Row 0: SRC-E | SV | SV | TNES | SV | SNK-W
Row 1: BLK | CNE | TESW | SH | BLK | CES
Row 2: LEK | BLK | CNE | SH | TWNE | BLK
Row 3: BLK | SV | CSW | SH | CNE | SV
Row 4: TESW | BLK | CES | CES | CWN | BLK
Row 5: SH | CNE | BLK | BLK | CES | SNK-W
```

Fixed special positions:

- Source: `(0,0)`
- Sink 1: `(0,5)`
- Sink 2: `(5,5)`
- Leak: `(2,0)`

Blocks:

```text
(1,0)
(1,4)
(2,1)
(2,5)
(3,0)
(4,1)
(4,5)
(5,2)
(5,3)
```

Compared with the base map:

- `(2,0)` is the fixed Leak instead of `CSW`.
- `(3,2)` is a rotatable `CSW` Corner Pipe instead of the Leak.

All Straight, Corner, and T Pipes are rotatable.

## 5.2 Bidirectional Connection Rule

Water propagation begins from the Source's E outlet.

For two adjacent ordinary pipe cells to connect, both sides must agree:

- N ↔ S
- E ↔ W
- S ↔ N
- W ↔ E

For example, if the current pipe has an E outlet, the cell to its right must have a W connection for water to enter it.

After water enters an ordinary pipe, all of that pipe's actual connected directions must be evaluated.

The direction from which water just entered is a valid return connection and is not itself treated as a Leak.

## 5.3 Source-Reachable Traversal

Only connections actually reachable from the Source participate in water evaluation.

An isolated pipe that is never reached by Source water contributes no Leak, even if one of its outlets visually points toward an invalid location.

Water may:

- Branch.
- Rejoin.
- Form loops.

To prevent infinite traversal without incorrectly suppressing valid branches, propagation must track processed directed traversal connections rather than treating an entire pipe cell as permanently exhausted after its first visit.

The same directed connection must not be processed repeatedly.

## 5.4 Invalid Outlet Evaluation

For each outgoing direction of a Source-reached pipe, evaluate the adjacent position once for that traversal.

An outlet is invalid if it points:

- Outside the board.
- Into a Block.
- Into the fixed Leak at `(2,0)`.
- Into an ordinary adjacent pipe without the required reverse connection.

Each independent invalid outlet:

- Increases Leaks by 1.
- Displays one red X at that outlet.
- Stops propagation through that outlet.

The ordinary pipe at `(3,2)` is evaluated using normal bidirectional pipe-connection rules.

## 5.5 Leak-Cell Rule

If an outlet points directly into the fixed Leak cell at `(2,0)`:

- Count exactly 1 Leak.
- Display one red X at the outgoing pipe's corresponding edge.
- Do not additionally count a missing reverse connection.
- Do not continue propagation through the Leak cell.

A single outlet entering the Leak therefore contributes at most 1 to Leaks.

The cell `(3,2)` has no special Leak behavior.

## 5.6 Sink Rule

A `SNK-W` Sink accepts water only from the cell immediately to its left through that cell's E outlet.

When water enters through this valid interface:

- Mark the Sink as `reached`.
- Stop propagation at the Sink.

Water approaching the Sink from another direction does not mark it as reached.

## 5.7 Leak Counting

Each independent invalid Source-reachable outlet is counted separately.

For example, if one reached T Pipe has two different invalid outgoing directions:

- Leaks += 2
- Display 2 red X marks

One physical pipe may therefore contribute more than one Leak.

The same invalid outlet must not be counted repeatedly because of loop traversal.

## 5.8 Water Visualization

All Source-reachable pipe segments actually traversed by water are highlighted in blue.

When water reaches an ordinary pipe:

- The channel associated with the valid incoming connection is blue.
- Each actual outgoing branch evaluated from that reached pipe is also blue.

If an outgoing branch is invalid:

- Its channel remains blue up to the edge.
- A red X is overlaid at the invalid endpoint.

## 5.9 Submission Result

After all Source-reachable water propagation has been processed:

Victory:

- Sink 1 is `reached`.
- Sink 2 is `reached`.
- Leaks = 0.

Failure:

- At least one Sink is not `reached`, or
- Leaks > 0.

No additional criteria are used.

---

# 6. Game Flow & Progression

At initialization, the game creates the interface areas and the V6 fixed 6 × 6 board.

Initial state:

- Source: `(0,0)`
- Sink 1: `(0,5)`
- Sink 2: `(5,5)`
- Leak: `(2,0)`
- Moves: 0
- Water: Off
- Leaks: 0
- Sink 1 reached: false
- Sink 2 reached: false
- Game state: `editing`

During `editing`, the player may rotate any eligible pipe while Moves < 30.

The ordinary `CSW` Corner Pipe at `(3,2)` is rotatable.

The Leak at `(2,0)` is fixed and cannot rotate.

Each successful rotation updates the pipe immediately and increases Moves by 1.

If Moves reaches 30:

- Further rotations stop.
- The game remains in `editing`.
- Space can still submit the current configuration.
- R can still restart.

When Space is pressed:

1. Set Water to On.
2. Stop editing.
3. Begin propagation from the Source's E outlet.
4. Traverse all Source-reachable valid pipe connections.
5. Track processed directed connections to prevent infinite loop traversal.
6. Evaluate every actual outgoing direction of each reached pipe.
7. Count each independent invalid outlet exactly once.
8. Highlight reached pipe channels in blue.
9. Display a red X at every invalid outlet.
10. Record whether each Sink is reached.
11. Resolve the submitted result.

If both Sinks are reached and Leaks = 0:

- Enter `won`.
- Display `Puzzle Solved!`.
- Display `Press R to Restart`.

Otherwise:

- Enter `failed`.
- Display `Failed`.
- Display `Press R to Restart`.

In both terminal states:

- Final pipe orientations remain visible.
- Blue water highlights remain visible.
- Red X marks remain visible.
- Final Leaks value remains visible.
- Further rotation and resubmission are disabled.
- Only R can restart.

Restart restores the V6 fixed puzzle.

The game contains no additional level progression.

---

# 7. Goal, Feedback & Termination

The player's goal is to configure the fixed pipe network within at most 30 successful rotations so that Source water reaches both Sinks without producing any invalid Source-reachable outlet, including any outlet entering the Leak at `(2,0)`.

During editing:

- Each successful pipe rotation immediately updates its orientation.
- Moves increases by 1.
- Water remains Off.
- Leaks remains 0.

Clicking a non-rotatable object or attempting another rotation after Moves reaches 30 does not change the board or Moves.

After Space is pressed:

- Water changes to On.
- Source-reachable channels are highlighted in blue.
- Every independent invalid outlet displays a red X.
- Leaks displays the total number of invalid reachable outlets.

An outlet that enters the fixed Leak at `(2,0)` contributes exactly 1 Leak and is not double-counted as both Leak-cell entry and missing reverse connection.

Victory requires:

- Both Sinks reached.
- Leaks = 0.

Failure occurs if:

- At least one Sink is not reached, or
- Leaks > 0.

Moves reaching 30 is not itself a Failure condition.

After `won`:

`Puzzle Solved!`

`Press R to Restart`

After `failed`:

`Failed`

`Press R to Restart`

Both terminal states disable further editing and resubmission.

R restores the V6 initial map, clears all water-flow results, and returns the game to `editing`.

---

# 8. Functional Checkpoints
