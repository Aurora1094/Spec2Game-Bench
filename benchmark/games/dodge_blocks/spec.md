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
  "game_name": "Dodge Blocks",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      600,
      800
    ]
  },
  "schema_version": 1
}
---
# Game Specification

## Game Name
Dodge Blocks

---



# 1. Game Overview
Dodge Blocks is a single-player real-time reaction game. The player controls a block near the bottom of the main gameplay area and can move only horizontally while avoiding obstacle blocks that continuously fall from the top of the screen.
The player's goal is to survive for as long as possible and achieve the highest possible score. The game has no fixed victory score, completion condition, level transition, or victory state.

Score starts at 0 and increases by 1 for every complete second the player remains alive.
A custom mechanic in this game is the horizontal dash. While holding either the left or right arrow key, the player can press Space to instantly move 80 px in the corresponding horizontal direction.

After a successful dash, the ability enters a 2-second cooldown. Pressing Space while Dash is cooling down or while no horizontal direction key is held has no effect and does not start or restart the cooldown.

---



# 2. Game Scene & Interface
The game window is 600 × 800 px and uses a vertical layout. From top to bottom, the window is divided into three areas:
1. Top information area: 600 × 100 px
2. Main gameplay area: 600 × 600 px
3. Bottom instruction area: 600 × 100 px

## 2.1 Top Information Area
The top information area displays the current score on the left using the fixed format `Score: X`, where X is the current score.
At the start of the game, it displays `Score: 0`. The score text uses a font size of 40 px.

The Dash status is displayed on the right using:
- `Dash: Ready`
- `Dash: Cooling`

`Dash: Ready` indicates that Dash is available. `Dash: Cooling` indicates that the 2-second cooldown is active.
The Dash status uses a font size of 32 px. The score and Dash status must have sufficient spacing and must not overlap.

## 2.2 Main Gameplay Area
The main gameplay area is located below the top information area and has a size of 600 × 600 px.
Its window-coordinate range is:
- Top-left: `(0, 100)`
- Bottom-right: `(600, 700)`

The area uses continuous pixel coordinates and does not require a visible grid. The player and all obstacles are represented by rectangles.

The player block has the following properties:
- Size: 40 × 40 px
- Color: blue or cyan
- Initial top-left position: `(280, 640)`

At initialization, the player's horizontal center is x = 300, its bottom edge is y = 680, and a 20 px gap remains between the player and the bottom boundary at y = 700.

Each obstacle:
- Has a fixed size of 40 × 40 px.
- Uses red or dark red.
- Spawns with top-left y-coordinate y = 100.
- Uses a random integer top-left x-coordinate from 0 to 560 inclusive.

Obstacle positions do not need to align with a grid.

## 2.3 Bottom Instruction Area
While the game is in the `playing` state, the bottom instruction area displays:
`Move: ← / →`
`Dash: Space    Restart: R`

Both lines use a font size of 28 px and should be centered within the bottom instruction area.

After the game enters `game_over`, the bottom instruction area displays:
`Game Over`
`Press R to Restart`

`Game Over` uses a font size of 40 px, and `Press R to Restart` uses a font size of 28 px. Both lines should be centered.

The top information area and bottom instruction area use a light-gray background, while the main gameplay area uses a white or light-colored background. Text should use a dark or otherwise high-contrast color.
At the start of the game, the player is positioned at `(280, 640)`, no obstacle is present, the top information area displays `Score: 0` and `Dash: Ready`, and the bottom instruction area displays the normal gameplay instructions.

---



# 3. Game Objects & States
The main game objects and state variables include the player block, obstacle blocks, score, Dash state, and game state.

## 3.1 Player Block
The player block has the following properties:
- Size: 40 × 40 px
- Initial top-left position: `(280, 640)`
- Movement speed: 300 px/s
- Movement axis: horizontal only

The player cannot move vertically or jump. Its y-coordinate remains fixed during normal movement and dashing.
The player's top-left x-coordinate must remain within `0 ≤ x ≤ 560`, ensuring that the entire block stays inside the gameplay area.

## 3.2 Obstacle Blocks
Each obstacle is a hazardous 40 × 40 px block that spawns at a random horizontal position and moves vertically downward at a fixed speed.
Obstacles do not:
- Move horizontally.
- Track the player.
- Accelerate.
- Change their falling speed.

An obstacle is removed when its top edge moves below the bottom boundary of the main gameplay area:
`obstacle_y > 700`

Removing an obstacle does not directly increase the score.

## 3.3 Score
Score represents the player's survival time.
The initial value is:
`Score = 0`

For every complete second the player remains alive:
`Score += 1`

Score is updated only while the game state is `playing`. After entering `game_over`, Score stops increasing and remains at its final value.
The game does not record a separate high score.

## 3.4 Dash State
Dash has two internal states:
- `ready`
- `cooling`

The initial state is `ready`, displayed as `Dash: Ready`.
After a successful dash, Dash becomes `cooling`, a 2-second cooldown begins, and the UI displays `Dash: Cooling`.

When the cooldown ends, Dash returns to `ready` and the UI displays `Dash: Ready`.
An invalid Space input does not start or restart the cooldown.

## 3.5 Game State
The game contains two states:
- `playing`
- `game_over`

The initial state is `playing`.
The game immediately enters `game_over` when the player's rectangular collision area overlaps with any obstacle rectangle.

After entering `game_over`, movement and Dash inputs no longer affect gameplay. Only R is accepted to restart.

---



# 4. Player Interaction
The player uses the left arrow key, right arrow key, Space, and R.

## 4.1 Horizontal Movement
While the left arrow key is held, the player moves left. While the right arrow key is held, the player moves right.
The movement speed is fixed at 300 px/s.

The player can move only horizontally, and its top-left x-coordinate must remain within:
`0 ≤ x ≤ 560`

If the player reaches either horizontal boundary and continues holding the corresponding direction key, it remains at that boundary.

## 4.2 Dash
Space triggers a horizontal dash.
A successful dash requires:
1. The left or right arrow key is currently held.
2. Dash state is `ready`.

If the left arrow key is held, pressing Space instantly moves the player 80 px to the left.
If the right arrow key is held, pressing Space instantly moves the player 80 px to the right.

The dash cannot move the player outside the gameplay area. The final top-left x-coordinate is clamped to `0–560`.
Therefore:
- A leftward dash near the left boundary stops at x = 0.
- A rightward dash near the right boundary stops at x = 560.

After a successful dash, Dash becomes `cooling` and a 2-second cooldown begins.
Pressing Space has no effect if neither horizontal direction key is held or if Dash is already `cooling`. An ineffective Space input does not start or restart the cooldown.

## 4.3 Restart
After the game enters `game_over`, the arrow keys and Space have no effect.
Pressing R restarts the game and fully resets the player, obstacles, score, timers, Dash state, interface state, and game state.

---



# 5. Core Rules & Mechanics

## 5.1 Player Movement
The player's normal horizontal movement speed is fixed at 300 px/s. Movement does not accelerate or decelerate over time.
The player cannot:
- Move vertically.
- Jump.
- Leave the left or right boundaries of the gameplay area.

## 5.2 Obstacle Spawning
Exactly one new obstacle is spawned every 1 second while the game state is `playing`.
At spawn time:
- Width: 40 px
- Height: 40 px
- Top-left y-coordinate: 100
- Top-left x-coordinate: random integer from 0 to 560 inclusive

No obstacle is present when the game begins.
The 1-second spawn interval remains fixed and does not change according to elapsed time, score, or survival duration.

## 5.3 Obstacle Movement
Each obstacle moves vertically downward at a fixed speed of 200 px/s.
Obstacles do not move horizontally, track the player, accelerate, or change speed.

When an obstacle's top edge moves below y = 700, it is removed from the game.
The game does not include differently sized obstacles, special obstacles, obstacle acceleration, or increasing difficulty.

## 5.4 Survival-Time Scoring
Score is based exclusively on survival time.
The initial value is 0, and Score increases by 1 for every complete second the player remains alive.

Avoiding an individual obstacle does not directly increase Score. Removing an obstacle after it leaves the gameplay area also does not increase Score.
Score stops increasing immediately after the game enters `game_over`.

## 5.5 Dash Mechanics
A successful dash instantly moves the player 80 px in the currently held horizontal direction.
A dash succeeds only if:
- The left or right arrow key is currently held.
- Dash state is `ready`.

After a successful dash:
1. Apply the 80 px horizontal displacement.
2. Clamp the player's top-left x-coordinate to `0–560`.
3. Set Dash state to `cooling`.
4. Start a 2-second cooldown.

When the cooldown ends, Dash returns to `ready`.
If a Space input is invalid, no movement occurs and the cooldown timer remains unchanged.

## 5.6 Collision Detection
Collision between the player and obstacles uses rectangle-overlap detection. Pixel-perfect collision detection is not required.
If the player's rectangle overlaps any obstacle rectangle, the game immediately enters `game_over`.

A single valid collision is sufficient to end the game. The game does not include HP, shields, damage invulnerability, multiple-hit survival, or collision recovery.

---



# 6. Game Flow & Progression
At initialization, the game creates the window, interface areas, player, obstacle spawn timer, survival timer, score, Dash state, and game state.
The initial state is:
- Player position: `(280, 640)`
- Score: 0
- Dash state: `ready`
- Obstacle list: empty
- Game state: `playing`

While `playing`, the program continuously processes horizontal player input and valid Dash input. The player remains within x = 0–560.
The obstacle spawn timer advances continuously. Exactly one obstacle is created whenever the fixed 1-second spawn interval is reached, and each active obstacle moves downward at 200 px/s.

Obstacles whose top edge moves below y = 700 are removed.
The survival timer advances while the game remains active, and Score increases by 1 for every complete second survived. The Dash cooldown also advances after a successful dash until Dash becomes `ready` again.

The game continuously checks rectangle overlap between the player and active obstacles. If a collision occurs, the game immediately enters `game_over`.
After entering `game_over`:
- Player movement stops.
- Existing obstacles stop moving.
- No new obstacles are spawned.
- Score stops increasing.
- Dash no longer updates.
- Arrow keys and Space have no effect.
- The bottom instruction area displays `Game Over` and `Press R to Restart`.

Pressing R fully reinitializes the game. The player returns to `(280, 640)`, Score returns to 0, all obstacles are removed, the obstacle spawn and survival timers are reset, Dash returns to `ready`, the Dash cooldown is cleared, the normal gameplay instructions are restored, and the game state returns to `playing`.

The game contains no difficulty progression. The following values remain fixed throughout the game:
- Player movement speed: 300 px/s
- Obstacle size: 40 × 40 px
- Obstacle spawn interval: 1 second
- Obstacle falling speed: 200 px/s
- Dash distance: 80 px
- Dash cooldown: 2 seconds

---



# 7. Goal, Feedback & Termination
The player's goal is to avoid falling obstacle blocks for as long as possible and achieve the highest possible score.
The game has no fixed completion score, victory threshold, victory state, or level progression.

The top information area displays `Score: X`, beginning with `Score: 0`. X increases by 1 for every complete second of survival.
The Dash display shows either `Dash: Ready` or `Dash: Cooling`. Only a successful dash starts the 2-second cooldown.

During `playing`, the bottom instruction area displays:
`Move: ← / →`
`Dash: Space    Restart: R`

After a collision, the game immediately enters `game_over` and displays:
`Game Over`
`Press R to Restart`

The only termination condition is rectangle overlap between the player and any obstacle.
An obstacle leaving the bottom of the gameplay area does not end the game and simply causes that obstacle to be removed.

After entering `game_over`, pressing R restarts the game and restores all gameplay variables and interface elements to their initial states.

---



# 8. Functional Checkpoints
