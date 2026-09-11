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
  "difficulty": "easy",
  "evaluation": {
    "d2": {
      "checkpoint_jsonl": "checkpoints.jsonl"
    },
    "protocol_version": 4,
    "seed": 17
  },
  "game_name": "Snake",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      600,
      800
    ]
  },
  "schema_version": 1,
  "family_slug": "snake",
  "variant_id": "var04",
  "instance_id": "snake_var04"
}
---

# Game Specification

## Game Name
Snake

---



# 1. Game Overview
Snake is a single-player grid-based game. The player uses W, A, S, and D to control the snake's direction while it continuously moves through the main gameplay area.
The objective is to collect randomly spawned food while avoiding self-collision and the lethal left and right boundaries.

Two food items are present simultaneously during normal gameplay. Each time the snake collects one food item, its length increases by 1, the score increases by 1, the collected food is removed, and one new food item is randomly spawned on an unoccupied grid cell so that the total number of food items returns to 2.
The game has no fixed victory score, completion condition, or victory state. The player's objective is to survive for as long as possible and achieve the highest possible score.

Unlike conventional Snake games, this game uses asymmetric boundary behavior: crossing the top or bottom boundary wraps the snake to the opposite side, while crossing the left or right boundary immediately ends the game.

---



# 2. Game Scene & Interface
The game window is 600 × 800 px and uses a vertical layout. From top to bottom, the window is divided into three areas:
1. Top information area: 600 × 100 px
2. Main gameplay area: 600 × 600 px
3. Bottom instruction area: 600 × 100 px

## 2.1 Top Information Area
The top information area displays the current score in the fixed format `Score: X`, where X is the current score.
At the start of the game, it displays `Score: 0`.

The score text uses a font size of 40 px and should be clearly visible. It may be horizontally centered or left-aligned within the top information area.

## 2.2 Main Gameplay Area
The main gameplay area is located directly below the top information area and has a size of 600 × 600 px. It is divided into a 30 × 30 grid, with each grid cell measuring 20 × 20 px.
Both the snake and food must remain aligned with the grid.

The main gameplay area uses a light-colored background with moderately visible grid lines so that individual cells can be clearly distinguished.
The snake is drawn using orange blocks, and food items are drawn using brown blocks.

At the start of the game:
- Snake length: 3
- Initial movement direction: right
- Food: exactly two items randomly spawned on two distinct grid cells not occupied by the snake

## 2.3 Bottom Instruction Area
While the game is in the `playing` state, the bottom instruction area displays:
`Move: WASD`
`Top/bottom wrap, left/right walls kill`

After the game enters the `game_over` state, it displays:
`Game Over`
`Press R to Restart`

Both lines use a font size of 28 px and should be centered within the bottom instruction area.
The top information area and bottom instruction area should be visually distinct from the main gameplay area and may use light or neutral background colors. All text should use a dark or otherwise high-contrast color for readability.

---



# 3. Game Objects & States
The main game objects and state variables include the snake, food, gameplay grid, score, and game state.

## 3.1 Snake
The snake is the primary player-controlled object and consists of contiguous grid cells.
Its initial properties are:
- Length: 3
- Movement direction: right

The snake state includes the head position, ordered body-cell positions, current movement direction, and alive/dead state.
During each movement update, the head moves exactly one grid cell in the current direction and the body positions are updated accordingly.

If food is collected, the snake's length increases by 1.
If the snake crosses the left or right boundary or collides with a body cell that remains occupied after the current movement update, it dies and the game enters `game_over`.

## 3.2 Food
Each food item occupies exactly one grid cell, and exactly two food items must exist simultaneously while the game is in the `playing` state.

Two food items are spawned during game initialization.
Whenever one food item is collected, that food item is removed and exactly one replacement food item is spawned so that the total number of food items returns to 2.

Every newly spawned food item must:
- Be inside the 30 × 30 gameplay grid.
- Occupy a grid cell not occupied by the snake after the current movement update.
- Occupy a grid cell not occupied by the other existing food item.

The game does not include special food, timed food, bonus food, or other food types.

## 3.3 Gameplay Grid
The gameplay grid contains 30 columns × 30 rows, with each cell measuring 20 × 20 px.
Both the snake and food must always remain aligned with grid cells, and each movement step advances the snake head exactly one cell.

## 3.4 Score
Score records the number of food items collected.
The initial score is 0. Each valid food collection increases the score by 1 and immediately updates the top information display to `Score: X`.

## 3.5 Game State
The game contains two states:
- `playing`
- `game_over`

The initial state is `playing`.
The game enters `game_over` if the snake crosses the left or right boundary or collides with its own body according to the self-collision rule in Section 5.4.

After entering `game_over`, the snake stops moving, movement input no longer affects gameplay, and only R is accepted to restart.

---



# 4. Player Interaction
The player uses W, A, S, D, and R.

## 4.1 Direction Control
The movement controls are:
- W: up
- S: down
- A: left
- D: right

The snake continuously moves in its current direction, so the player does not need to press a movement key for every step.
After a valid directional input is received, the new direction takes effect on the next movement update.

## 4.2 Opposite-Direction Input
The snake cannot directly reverse its movement direction.
An input opposite to the current movement direction is ignored:
- While moving right, A is ignored.
- While moving left, D is ignored.
- While moving up, S is ignored.
- While moving down, W is ignored.

When an opposite-direction input is ignored, the snake continues moving in its current direction.

## 4.3 Restart
After the game enters `game_over`, pressing R restarts the game.
Restart fully resets the snake, food, score, interface state, and game state to their initial conditions.

---



# 5. Core Rules & Mechanics

## 5.1 Movement
The snake moves at a fixed speed of 8 steps per second. Each movement step advances the snake head exactly one grid cell.
The movement speed remains constant throughout the game and does not change according to score, elapsed time, or snake length.

If the snake does not collect food during a movement step, the final tail cell is removed so that the snake's length remains unchanged.
If the snake collects food, the tail is retained, causing the snake's length to increase by 1.

## 5.2 Food Collection
Food is collected when the snake head enters a grid cell occupied by either food item.

When one food item is collected:
- Score increases by 1.
- Snake length increases by 1.
- The collected food item is removed.
- One new food item is randomly spawned on a valid unoccupied grid cell.

The other existing food item remains unchanged.

A valid replacement food spawn cell must not be occupied by:
- The snake after the current movement update.
- The other food item.

Exactly two normal food items must exist after replacement spawning is complete.

## 5.3 Boundary Rules
The game uses asymmetric boundary behavior:
- Top boundary: the snake re-enters from the bottom boundary in the same column.
- Bottom boundary: the snake re-enters from the top boundary in the same column.
- Left boundary: crossing it immediately causes `game_over`.
- Right boundary: crossing it immediately causes `game_over`.

Crossing the top or bottom boundary never causes Game Over.

## 5.4 Self-Collision
Self-collision is checked against the body cells that remain occupied after the current movement update.

If the current movement does not collect food, the final tail cell is removed during the same update. That cell is therefore excluded from self-collision detection, and the snake head may move into it without causing Game Over.

If the current movement collects food, the tail is retained. The current tail cell therefore remains occupied and is included in self-collision detection.

A self-collision occurs when the new head position overlaps any body cell that remains occupied after the movement update.

## 5.5 Movement-Step Evaluation Order
Each movement step follows this logical order:
1. Calculate the new head position from the current movement direction.
2. Apply top/bottom wrapping if necessary.
3. Check whether the head has crossed the left or right boundary. If so, immediately enter `game_over`.
4. Determine whether the new head position reaches either food item.
5. Determine which body cells remain occupied after the movement:
   - If food is collected, retain the tail.
   - Otherwise, treat the final tail cell as vacated.
6. Check the new head position against the body cells that remain occupied. If a self-collision occurs, enter `game_over`.
7. Update the snake body by adding the new head and retaining or removing the tail as determined above.
8. If food was collected, increase the score by 1, remove the collected food item, and spawn one new valid replacement food item.

If a terminal collision occurs during Step 3 or Step 6, no food collection, score increase, growth, or replacement food spawning is processed for that movement step.

---



# 6. Game Flow & Progression
At initialization, the game creates the window, interface areas, gameplay grid, snake, food, score, and game state.
The initial state is:
- Snake length: 3
- Snake direction: right
- Score: 0
- Food: two randomly spawned valid items on distinct grid cells
- Game state: `playing`

While `playing`, the program continuously processes directional input and updates the snake at a fixed rate of 8 movement steps per second.
Each movement update follows the boundary, food-collection, self-collision, and body-update rules defined in Section 5.

When the snake collects one food item, the score and snake length each increase by 1, the collected food item is removed, and one new food item is spawned so that two food items remain present.
When the snake crosses the top or bottom boundary, it wraps to the corresponding position on the opposite side.
When the snake crosses the left or right boundary or collides with a body cell that remains occupied after the movement update, the game enters `game_over`.

After entering `game_over`:
- The snake stops moving.
- The final score is preserved.
- Movement inputs no longer affect gameplay.
- The bottom instruction area displays `Game Over` and `Press R to Restart`.
- R remains available to restart.

The movement speed remains fixed throughout the game. The game does not include levels, increasing difficulty, acceleration, or progression stages.
Progression is represented only by increasing score and snake length as food is collected.

---



# 7. Goal, Feedback & Termination
The player's goal is to collect as much food as possible before the game ends and achieve the highest possible score.
The game has no fixed completion score, victory threshold, or victory state.

The top information area displays the current score in real time using `Score: X`, starting from `Score: 0`.
Each food collection immediately increases X by 1.

During `playing`, the bottom instruction area displays:
`Move: WASD`
`Top/bottom wrap, left/right walls kill`

After entering `game_over`, it displays:
`Game Over`
`Press R to Restart`

The game ends when:
- The snake head crosses the left or right boundary.
- The snake head moves into a body cell that remains occupied after the current movement update.

Moving into the current final tail cell does not cause Game Over when that tail cell is removed during the same update.
Crossing the top or bottom boundary does not end the game and instead wraps the snake to the corresponding position on the opposite side.

After `game_over`, pressing R restores the snake to its initial length and configuration, resets the direction to right and score to 0, generates two new valid food items on distinct unoccupied grid cells, restores the normal gameplay instructions, and returns the game state to `playing`.

---



# 8. Functional Checkpoints
