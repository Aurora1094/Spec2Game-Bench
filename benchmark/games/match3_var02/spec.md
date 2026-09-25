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
  "difficulty": "medium",
  "evaluation": {
    "d2": {
      "checkpoint_jsonl": "checkpoints.jsonl"
    },
    "protocol_version": 4,
    "seed": 17
  },
  "game_name": "Match-3",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      600,
      800
    ]
  },
  "schema_version": 1,
  "family_slug": "match3",
  "variant_id": "var02",
  "instance_id": "match3_var02"
}
---

# Game Specification

## Game Name
Match-3

---

# 1. Game Overview
Match-3 is a two-dimensional grid-based logic puzzle game. The player uses the mouse to select and swap two adjacent gems.

If the resulting board contains at least one horizontal or vertical sequence of 3 or more gems of the same type, the swap is valid and remains in place.

After a valid swap:
- Moves increases by 1.
- All current matches are detected.
- All matched gems are cleared simultaneously.
- Score increases according to the number of distinct gems cleared.
- Gems fall downward within their columns.
- New gems are generated at the top.
- Any newly created matches are resolved automatically.

The game uses a fixed 8 × 8 board. Each stable cell contains exactly one gem.

The six fixed gem types are Red, Blue, Green, Yellow, Purple, and Orange, each with a distinct visual appearance.

At the start of the game, the board is randomly generated as a full 8 × 8 board with no horizontal or vertical match of 3 or more identical gems.

A custom mechanic is automatic chain clearing. After a valid player swap, clearing, falling, and refilling repeat automatically until the board contains no match.

Automatic chains increase Score but do not increase Moves and do not use a chain multiplier.

The game has no victory, failure, Game Over, move limit, countdown, Lives, or automatic terminal condition.

A session continues indefinitely until the player presses R to restart.

---

# 2. Game Scene & Interface
The game window is 600 × 800 px and uses a vertical layout. From top to bottom, the window is divided into:
1. Top information area: 600 × 100 px
2. Main gameplay area: 600 × 600 px
3. Bottom instruction area: 600 × 100 px

## 2.1 Top Information Area
The top information area displays:
- Left: `Score: X`
- Right: `Moves: X`

At the start of the game:
`Score: 0`
`Moves: 0`

Both text elements use a font size of 40 px and must have sufficient horizontal spacing so that they do not overlap.

## 2.2 Main Gameplay Area
The main gameplay area has a size of 600 × 600 px.

The 8 × 8 board is centered within this area:
- Top-left coordinate: `(60, 160)`
- Size: 480 × 480 px
- Bottom-right coordinate: `(540, 640)`
- Cell size: 60 × 60 px

The board uses grid coordinates `(row, col)`:
- Top-left cell: `(0, 0)`
- Bottom-right cell: `(7, 7)`

For a cell at `(row, col)`, its top-left window coordinate is:
`x = 60 + col × 60`
`y = 160 + row × 60`

The remaining space in the main gameplay area is used as background.

## 2.3 Gem Appearance
Each gem is centered within its cell and occupies approximately a 44 × 44 px visual bounding area, leaving about 8 px of margin on each side.

The six gem types use:

| Type | Color | Shape |
|---|---|---|
| Red | `#E74C3C` | Circle |
| Blue | `#3498DB` | Diamond |
| Green | `#2ECC71` | Square |
| Yellow | `#F1C40F` | Regular hexagon |
| Purple | `#9B59B6` | Five-pointed star |
| Orange | `#E67E22` | Triangle |

Color and shape are visual identifiers only. Logical match detection uses gem type.

## 2.4 Selection Highlight
When a gem is selected, a white 4 px highlight border is drawn inside its cell.

The highlight indicates only the current selection and does not modify gem type, position, or size.

No selection highlight is displayed while the game is in `resolving`.

## 2.5 Bottom Instruction Area
While the game is active, the bottom instruction area displays:
`Click two adjacent gems to swap`
`Only valid matches stay    Restart: R`

Both lines use a font size of 26 px and should be centered.

Recommended colors are:
- Top information area: `#EDEDED`
- Bottom instruction area: `#EDEDED`
- Main gameplay background: `#F7F7F7`
- Board background: `#222222`
- Board grid lines: `#555555`
- Text: `#222222`

The board should also have a clearly visible outer border.

At initialization:
- Board: full 8 × 8
- Score: 0
- Moves: 0
- Selected cell: none
- Game state: `waiting`
- Initial matches: none

No automatic opening clear occurs.

---

# 3. Game Objects & States
The main game objects and state variables include the board, gems, selected cell, Score, Moves, and game state.

## 3.1 Board
The board contains:
`8 × 8 = 64`
cells.

In a stable state, every cell contains exactly one gem.

During clearing and falling, cells may temporarily be empty.

After all clearing, falling, refilling, and automatic chain processing are complete, the board must again be:
- Full.
- 8 × 8.
- Free of horizontal or vertical matches of 3 or more.

The board does not scroll, expand, or change size.

## 3.2 Gems
Each gem has:
- Gem type
- Color
- Shape
- Board position

The available types are:
- Red
- Blue
- Green
- Yellow
- Purple
- Orange

Match detection depends only on gem type.

## 3.3 Selected Cell
The selected cell stores the board position chosen by the player's first click.

The current selection is cleared when:
- The same cell is clicked again.
- The player clicks outside the board.
- A swap attempt is completed.
- The game enters `resolving`.
- R is pressed.

If another non-adjacent board cell is clicked, the previous selection is replaced by the newly clicked cell.

## 3.4 Score
Score starts at:
`0`

Every distinct gem cleared contributes:
`+10`

This rule applies to both:
- The initial clearing after a valid player swap.
- All subsequent automatic chain clearing.

If one gem belongs to both a horizontal and vertical match in the same clearing round, it is cleared once and contributes +10 once.

## 3.5 Moves
Moves starts at:
`0`

Moves increases by exactly 1 only when:
- The player swaps two adjacent gems.
- The resulting board contains at least one valid match.
- The swap is retained.

Moves does not increase for:
- Invalid swaps.
- Additional clearing rounds.
- Automatic chains.

## 3.6 Game State
The game contains two states:
- `waiting`
- `resolving`

During `waiting`, mouse selection and swap input are active.

During `resolving`, the game processes match detection, clearing, falling, refilling, automatic chains, and optional animations.

While `resolving`:
- Mouse clicks have no effect.
- No new swap can begin.
- R remains active.

The game has no victory, failure, or Game Over state.

A stable board with no valid swap does not trigger any automatic state change.

---

# 4. Player Interaction
The player uses the left mouse button and R.

## 4.1 Gem Selection
While in `waiting`, if no cell is selected, left-clicking a board cell selects that gem and displays the white 4 px highlight border.

If the selected cell is clicked again:
- Cancel the selection.
- Remain in `waiting`.

## 4.2 Clicking Outside the Board
Clicking outside the board clears the current selection.

This includes:
- Top information area.
- Bottom instruction area.
- Empty portions of the main gameplay area outside the board.

## 4.3 Non-Adjacent Reselection
If a cell is already selected and another non-adjacent board cell is clicked:
- Clear the previous selection.
- Select the newly clicked cell.

Two cells `(r1, c1)` and `(r2, c2)` are adjacent if and only if:
`|r1 - r2| + |c1 - c2| = 1`

Therefore, only up, down, left, and right adjacency is valid.

Diagonal adjacency is not valid.

## 4.4 Swap Attempt
When the second clicked cell is adjacent to the selected cell:
1. Swap the two gems.
2. Check the entire resulting board for horizontal or vertical matches of 3 or more.

If at least one match exists anywhere on the board:
- The swap is valid.
- Keep the swapped positions.
- Moves increases by 1.
- Clear the current selection.
- Enter `resolving`.

If no match exists:
- The swap is invalid.
- Immediately swap the two gems back.
- Score remains unchanged.
- Moves remains unchanged.
- Clear the current selection.
- Remain in `waiting`.

Two adjacent gems of the same type may still be used in a swap attempt. The same whole-board validity rule applies.

## 4.5 Input During Resolving
While in `resolving`, mouse clicks have no effect.

The player must wait until the board becomes stable and returns to `waiting`.

## 4.6 Restart
R is effective in both `waiting` and `resolving`.

When R is pressed:
- Immediately terminate any current resolving process.
- Cancel pending clearing, falling, refilling, chain, or animation operations.
- Clear the current selection.
- Generate a new full 8 × 8 board with no initial match using the six fixed gem types.
- Reset Score to 0.
- Reset Moves to 0.
- Return to `waiting`.

No pending operation from the previous board may continue after Restart.

---

# 5. Core Rules & Mechanics

## 5.1 Initial Board Generation
The game uses a fixed 8 × 8 board.

Each cell contains one randomly selected gem type from:
- Red
- Blue
- Green
- Yellow
- Purple
- Orange

The initial board must contain no horizontal or vertical sequence of 3 or more identical gems.

The initial board is not required to contain at least one valid swap.

After generation:
- The board is full.
- No match exists.
- Game state becomes `waiting`.
- No automatic clearing occurs.

## 5.2 Match Definition
A horizontal match consists of 3 or more consecutive gems of the same type in one row.

A vertical match consists of 3 or more consecutive gems of the same type in one column.

Diagonal sequences do not count.

Sequences of 4 or 5 or more gems are ordinary matches and do not create special gems.

## 5.3 Match Detection
Each detection step checks the entire board.

All horizontal and vertical matches must be identified before clearing begins.

If one gem belongs to multiple matches, include it only once in the set of gems to clear.

## 5.4 Valid Swap
After two adjacent gems are swapped, the entire resulting board is checked.

If at least one match exists anywhere on the board:
- The swap is valid.
- Keep the swap.
- Moves += 1.
- Enter `resolving`.

If no match exists:
- Revert the swap immediately.
- Score remains unchanged.
- Moves remains unchanged.
- Return to `waiting`.

Because the board is stable before each player action, any match detected after the swap results from the new board configuration produced by that swap.

## 5.5 Resolving Order
While in `resolving`, the board follows this fixed logical order:
1. Detect all current matches across the board.
2. Deduplicate gems that belong to multiple matches.
3. Clear all matched gems simultaneously.
4. Increase Score by 10 for each distinct cleared gem.
5. Apply falling independently within each column.
6. Refill all empty cells from the top.
7. Detect matches again.
8. Repeat Steps 2–7 while matches remain.
9. When no match remains, return to `waiting`.

The same logical order applies whether or not animations are used.

## 5.6 Simultaneous Clearing
All gems identified during one match-detection step are cleared simultaneously.

The system must not:
- Clear one match group first.
- Recalculate the board.
- Then separately clear another match that belonged to the same detection step.

A gem belonging to multiple matches is removed and scored only once during that clearing round.

## 5.7 Falling
After clearing, each column is processed independently.

Within each column:
1. Move surviving gems downward to remove all internal empty gaps.
2. Preserve the original vertical relative order of surviving gems.
3. Leave all remaining empty cells at the top.

Gems never move horizontally during falling.

## 5.8 Refilling
After falling, every empty cell at the top of each column is filled with a new random gem.

Each new gem is independently selected from the six fixed gem types.

New gems are not required to avoid creating matches.

If refilling creates one or more matches, those matches are handled as automatic chains.

## 5.9 Automatic Chains
After each clearing → falling → refilling cycle, check the entire board again.

If any match exists:
- Clear all current matches simultaneously.
- Increase Score normally.
- Apply falling.
- Refill.
- Check again.

This process continues until no match remains.

Automatic chains:
- Increase Score.
- Do not increase Moves.
- Do not use a chain multiplier.

## 5.10 Stable Board
A board is stable when:
- All 64 cells contain gems.
- No horizontal match of 3 or more exists.
- No vertical match of 3 or more exists.

When the board becomes stable:
- End `resolving`.
- Set the game state to `waiting`.
- Allow new player input.

The stable board is not required to contain a valid swap.

## 5.11 Dead Board Behavior
If the current stable board contains no swap capable of producing a match:
- Do not reshuffle.
- Do not enter Failure.
- Do not enter Game Over.
- Do not automatically restart.

The player may continue attempting swaps or press R manually.

## 5.12 Excluded Mechanics
The game does not include:
- Special gems
- Bomb gems
- Striped gems
- Rainbow gems
- Level objectives
- Move limit
- Countdown
- Lives
- Victory
- Failure
- Game Over
- Automatic reshuffling
- Dead-board detection
- Chain multiplier
- Items
- Mandatory animation

---

# 6. Game Flow & Progression
At initialization, the game creates the interface and 8 × 8 board, generates a full board with no initial matches using the six fixed gem types, sets Score and Moves to 0, clears the selection, and enters `waiting`.

No automatic opening clear occurs.

While `waiting`, the player may select a gem, cancel a selection, replace a selection with another non-adjacent gem, or attempt an adjacent swap.

For an adjacent swap:
1. Exchange the two gems.
2. Check the entire board.
3. If no match exists, revert the swap, keep Score and Moves unchanged, clear selection, and remain in `waiting`.
4. If at least one match exists, retain the swap, increase Moves by 1, clear selection, and enter `resolving`.

While `resolving`:
1. Detect all horizontal and vertical matches.
2. Deduplicate overlapping matched gems.
3. Clear all matched gems simultaneously.
4. Increase Score by 10 per distinct cleared gem.
5. Apply falling independently to each column.
6. Preserve the vertical order of surviving gems.
7. Refill empty cells from the top using the six fixed gem types.
8. Check the entire board again.
9. Repeat the resolving cycle if matches remain.
10. Return to `waiting` once the board is full and stable.

During automatic chains, Score continues to increase while Moves remains unchanged.

R may be pressed in either state.

If R is pressed during `resolving`, all pending operations are canceled immediately and cannot continue on the new board.

The game has no automatic terminal state and does not end or reshuffle when the board has no valid swap.

---

# 7. Goal, Feedback & Termination
The player's goal is to create horizontal or vertical matches of 3 or more identical gems by swapping adjacent gems, clear as many gems as possible, and achieve a higher Score.

The game has no fixed victory endpoint and does not require clearing the entire board.

The top information area displays:
`Score: X`
`Moves: X`

Score starts at 0 and increases by 10 for every distinct gem cleared.

Moves starts at 0 and increases by exactly 1 after each valid player-initiated swap.

For a valid swap:
- The swapped positions remain.
- Moves increases by 1.
- The game enters `resolving`.

For an invalid swap:
- The gems return immediately to their original positions.
- Score remains unchanged.
- Moves remains unchanged.
- The game remains in `waiting`.

During each clearing round, all currently matched gems disappear simultaneously.

After clearing, remaining gems fall within their columns, new gems selected from the six fixed gem types refill the top, and any newly created matches are resolved automatically.

R is effective in both `waiting` and `resolving`.

Restart immediately cancels any active resolving process, generates a new initial board without matches using the six fixed gem types, resets Score and Moves, clears the selection, and returns the game to `waiting`.

The game has no Victory, Failure, Game Over, or other automatic terminal state.

A dead board does not automatically end or reshuffle the game. The session continues until the player chooses to press R and restart.

---

# 8. Functional Checkpoints
