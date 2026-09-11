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
  "game_name": "Simple Shop Management",
  "params": {
    "player_color": "#3D7EFF",
    "round_time_sec": 60,
    "window_size": [
      600,
      800
    ]
  },
  "schema_version": 1,
  "family_slug": "simple_shop",
  "variant_id": "var06",
  "instance_id": "simple_shop_var06"
}
---

# Game Specification

## Game Name
Simple Shop Management

---

# 1. Game Overview
Simple Shop Management is a simplified resource-management and shop-operation game. The player runs a small shop and manages Money, Time, Missed customers, and the inventory of three products: Apple, Bread, and Milk.

During business hours, customers enter the shop one at a time. Each customer randomly requests exactly one product and moves toward the checkout counter.

When the customer reaches the counter:
- If the requested product is in stock, one unit is sold, inventory decreases by 1, and Money increases by the product's selling price.
- If the requested product is out of stock, no sale occurs, Money remains unchanged, and Missed increases by 1.

The player manages inventory by clicking product-specific restock buttons. Each successful restock adds exactly 3 units of the selected product and deducts a fixed restocking cost.

Each product has a maximum Stock of 12.

The game lasts for 60 seconds. When Time reaches 0, the shop immediately enters the `closed` state. Customer activity stops, restocking becomes unavailable, and the final Money and Missed values are displayed.

The game uses a single-customer system. At most one customer can exist in the shop at any time. After a customer leaves, the game waits for a random duration before spawning the next customer.

The game does not include employees, decoration, multi-day operation, price adjustment, customer queues, multiple simultaneous customers, customer patience, satisfaction, advertising, random events, upgrades, loans, debt, discounts, promotions, or complex management mechanics.

---

# 2. Game Scene & Interface
The game window is 600 × 800 px and uses a vertical layout. From top to bottom, the window is divided into:
1. Top information area: 600 × 100 px
2. Main gameplay area: 600 × 500 px
3. Bottom control area: 600 × 200 px

## 2.1 Top Information Area
The top information area displays:
- `Money: X` at `(30, 35)`
- `Time: X` at `(235, 35)`
- `Missed: X` at `(430, 35)`

At the start of the game:
`Money: 30`
`Time: 60`
`Missed: 0`

All three text elements use a font size of 32 px and must remain clearly readable without overlapping.

Time is displayed as a non-negative whole number only.

## 2.2 Main Gameplay Area
The main gameplay area occupies y = 100–600.

It displays:
- Three product shelves
- Product icons and names
- Inventory quantities
- Current customer
- Customer request bubble
- Checkout counter

The main gameplay background uses a light color such as `#F7F7F7`.

## 2.3 Product Shelves
The three shelves are fixed:

| Shelf | Top-Left Coordinate | Size | Content |
|---|---|---|---|
| Apple Shelf | `(60, 140)` | `140 × 120 px` | Apple icon, `Apple`, `Stock: X` |
| Bread Shelf | `(230, 140)` | `140 × 120 px` | Bread icon, `Bread`, `Stock: X` |
| Milk Shelf | `(400, 140)` | `140 × 120 px` | Milk icon, `Milk`, `Stock: X` |

Product icons must remain visually consistent across shelves, customer request bubbles, and restock buttons.

Each product must be represented using both an icon and a text label.

Product icons are visual identifiers only. Logical operations use product type.

The product appearances are:
- Apple: red apple with a brown stem and green leaf.
- Bread: light-brown loaf with 2–3 darker diagonal cuts.
- Milk: white or light blue-and-white carton or bottle with a blue element near the top.

Shelf icons use an approximate 40 × 40 px bounding area.

## 2.4 Counter & Customer
The checkout counter has:
- Top-left coordinate: `(410, 390)`
- Size: 120 × 80 px
- Label: `Counter`

The customer uses a simple person icon with an approximate size of 50 × 70 px.

Customer movement:
- Spawn center: `(50, 430)`
- Checkout center: `(430, 430)`
- Path: horizontal straight line
- Movement duration: 3 seconds

The customer automatically checks out when its center reaches `(430, 430)`.

## 2.5 Customer Request Bubble
A request bubble is displayed above the current customer.

Approximate properties:
- Size: 130 × 40 px
- White background
- Black border
- Font size: 18–20 px
- Product icon size: approximately 24 × 24 px

The bubble displays both the product icon and one of:
- `Wants: Apple`
- `Wants: Bread`
- `Wants: Milk`

The bubble moves together with the customer and remains positioned above the customer's head.

## 2.6 Bottom Control Area
The bottom control area occupies y = 600–800 and uses a light-gray background such as `#EDEDED`.

During `open`, it displays three clickable restock buttons:

| Button | Top-Left Coordinate | Size | Content |
|---|---|---|---|
| Restock Apple | `(40, 630)` | `160 × 60 px` | Apple icon, `Restock Apple`, `Cost: 6` |
| Restock Bread | `(220, 630)` | `160 × 60 px` | Bread icon, `Restock Bread`, `Cost: 9` |
| Restock Milk | `(400, 630)` | `160 × 60 px` | Milk icon, `Restock Milk`, `Cost: 12` |

Each button uses a product icon on the left and two text lines on the right.

`Restart: R` is displayed below the buttons, near y = 720, using a font size of 28 px.

## 2.7 Closed-State Interface
When the game enters `closed`, shelves and final inventory may remain visible, but restock buttons are no longer interactive.

The bottom control area prioritizes final results and displays:
`Shop Closed`
`Final Money: X`
`Missed: X`
`Press R to Restart`

The result text should be centered and clearly visible.

---

# 3. Game Objects & States
The main game objects and state variables include products, inventory, Money, Time, Missed, restock buttons, current customer, customer request, customer spawn timer, counter, and game state.

## 3.1 Products
The game contains exactly three products:

| Product | Initial Stock | Maximum Stock | Restock Amount | Restock Cost | Selling Price |
|---|---:|---:|---:|---:|---:|
| Apple | 3 | 12 | +3 | 6 | 4 |
| Bread | 3 | 12 | +3 | 9 | 6 |
| Milk | 3 | 12 | +3 | 12 | 8 |

## 3.2 Inventory
Each product maintains an independent Stock value.

Initial Stock:
- Apple: 3
- Bread: 3
- Milk: 3

For every product:
`0 ≤ Stock ≤ 12`

Successful restock:
`Stock += 3`

Successful customer purchase:
`Stock -= 1`

## 3.3 Money
Money starts at:
`Money = 30`

Money changes only through successful restocking and successful sales.

Successful restock:
`Money -= Restock Cost`

Successful sale:
`Money += Selling Price`

Money cannot become negative.

## 3.4 Time
Time starts at:
`Time = 60`

Time decreases only while the game is `open`.

The displayed value uses whole seconds, never becomes negative, and has a minimum value of 0.

When Time reaches 0, the game immediately enters `closed`.

## 3.5 Missed
Missed starts at:
`Missed = 0`

If a customer reaches checkout while the requested product has Stock = 0:
- No sale occurs.
- Money remains unchanged.
- `Missed += 1`
- The customer disappears.

Missed increases only because of an out-of-stock checkout during `open`.

## 3.6 Restock Buttons
Each product has one corresponding restock button.

A restock succeeds only if:
1. Money is at least the product's Restock Cost.
2. Current Stock is at most 9.

If both conditions are satisfied:
- Stock increases by 3.
- Money decreases by the Restock Cost.

If either condition fails:
- Money remains unchanged.
- Stock remains unchanged.

Restock buttons have no effect in `closed`.

## 3.7 Customer
At most one customer may exist at any time.

A customer stores:
- Current position
- Requested product
- Movement progress

The customer moves from `(50, 430)` to `(430, 430)` over exactly 3 seconds.

Checkout occurs immediately when the customer's center reaches the checkout position.

## 3.8 Customer Request
When a customer spawns, exactly one product is selected:
- Apple: 1/3
- Bread: 1/3
- Milk: 1/3

The request remains fixed throughout the customer's lifetime.

A customer never changes its request or purchases more than one product.

## 3.9 Game State
The game contains two states:
- `open`
- `closed`

During `open`:
- Time decreases.
- Customer spawn timing is active.
- Customers may spawn and move.
- Checkout may occur.
- Restock buttons are active.

During `closed`:
- Time remains 0.
- No new customer spawns.
- Any current customer is removed.
- No customer moves.
- No checkout occurs.
- Restock buttons have no effect.
- Only R is used to restart.

---

# 4. Player Interaction
The player uses the left mouse button and R.

## 4.1 Restocking
The left mouse button is used to click the three restock buttons.

A successful restock requires:
`Money ≥ Restock Cost`

and:
`Stock ≤ 9`

If both conditions are satisfied:
- Stock increases by 3.
- Money decreases by the corresponding cost.

If either condition is not satisfied:
- Restocking fails.
- Money remains unchanged.
- Stock remains unchanged.

An optional `Cannot restock` message may be shown, but this feedback does not affect gameplay state.

## 4.2 Automatic Sales
The player does not click customers or shelves to perform sales.

Checkout is automatic and depends only on:
- The customer's requested product.
- The current Stock of that product.

## 4.3 Time-Expiration Priority
If Time reaches 0 during the current frame, the game immediately enters `closed` before any new gameplay outcome from that frame is processed.

Therefore:
- A same-frame restock click is ignored.
- A same-frame customer checkout does not occur.
- Money does not change.
- Stock does not change.
- Missed does not change because of that unfinished customer.

## 4.4 Restart
R is effective in both `open` and `closed`.

After R is pressed:
- Money = 30
- Time = 60
- Missed = 0
- Apple Stock = 3
- Bread Stock = 3
- Milk Stock = 3
- Current customer is cleared
- Customer spawn timer is randomly reset to 1.5–3.0 seconds
- Game state = `open`
- Restock buttons become active again

The game does not use arrow keys, Space, or other gameplay keys.

---

# 5. Core Rules & Mechanics

## 5.1 Business Duration
The game uses a fixed business duration of 60 seconds.

At the start:
- Game state = `open`
- Time = 60

Time decreases continuously while `open`.

When Time reaches 0, immediately enter `closed`.

Time expiration has priority over:
- Customer checkout
- Restocking
- Customer spawning

## 5.2 Restocking Rules
Each successful restock adds exactly:
`+3 Stock`

Fixed restocking costs:
- Apple: 6
- Bread: 9
- Milk: 12

A restock succeeds only if:
`Money ≥ Cost`

and:
`Stock ≤ 9`

After a successful restock:
- Stock += 3
- Money -= Cost

Stock never exceeds 12.

Restocking has no waiting period or cooldown.

## 5.3 Customer Spawn Cycle
At initialization:
- No customer is present.
- A random waiting duration between 1.5 and 3.0 seconds is selected.

While no customer exists and the game remains `open`, the spawn timer advances.

When the timer expires:
1. Spawn one customer at `(50, 430)`.
2. Randomly assign one requested product.
3. Stop customer spawning while that customer exists.

After the customer leaves:
- Select a new random waiting duration of 1.5–3.0 seconds.
- Spawn the next customer only after that wait completes.

At most one customer may exist at any time.

The game does not use a customer queue.

## 5.4 Customer Movement
Each customer moves:
- From `(50, 430)`
- To `(430, 430)`
- Along a horizontal straight line
- Over exactly 3 seconds

The request bubble follows the customer during movement.

If the shop remains `open`, checkout occurs when the customer center reaches `(430, 430)`.

## 5.5 Customer Checkout
Each customer purchases at most one unit of the requested product.

If requested Stock > 0:
- Stock decreases by 1.
- Money increases by the selling price.
- The customer disappears.

Selling prices:
- Apple: 4
- Bread: 6
- Milk: 8

If requested Stock = 0:
- Money remains unchanged.
- Missed increases by 1.
- The customer disappears.

No player confirmation is required.

## 5.6 Time Expiration During Customer Activity
If Time reaches 0 before or in the same frame that the current customer would complete checkout:
- Immediately enter `closed`.
- Remove the customer.
- Do not complete the sale.
- Do not change inventory.
- Do not increase Money.
- Do not increase Missed.

The unfinished customer is discarded when the shop closes.

## 5.7 Closed State
When entering `closed`:
- Set Time to 0.
- Remove any current customer.
- Stop the customer spawn timer.
- Prevent new customer spawning.
- Stop customer movement.
- Prevent checkout.
- Disable restocking.
- Freeze Money, Missed, and inventory against further gameplay changes.

The interface displays:
`Shop Closed`
`Final Money: X`
`Missed: X`
`Press R to Restart`

## 5.8 No Early Termination
The game does not end early if:
- Money reaches 0.
- One inventory reaches 0.
- All inventories reach 0.
- Missed becomes large.

The game always continues until Time reaches 0.

There is no Victory or Failure classification based on final Money or Missed.

## 5.9 Excluded Mechanics
The game does not include employees, decoration, multi-day operation, price adjustment, customer queues, multiple simultaneous customers, customer patience, satisfaction, advertising, random events, upgrades, loans, debt, discounts, promotions, complex routing, or additional products.

---

# 6. Game Flow & Progression
At initialization, the game creates the interface areas, shelves, product icons, restock buttons, counter, Money, Time, Missed, inventory, customer spawn timer, and game state.

The initial state is:
- Money: 30
- Time: 60
- Missed: 0
- Apple Stock: 3
- Bread Stock: 3
- Milk Stock: 3
- Current customer: none
- Customer spawn wait: random 1.5–3.0 seconds
- Game state: `open`

While `open`, each update:
1. Advance Time.
2. If Time reaches 0, immediately enter `closed` and do not process new gameplay outcomes for the frame.
3. Otherwise, process valid restock clicks.
4. If no customer exists, advance the customer spawn timer.
5. If the spawn timer expires, spawn one customer and assign one random request.
6. If a customer exists, move it toward `(430, 430)`.
7. If the customer reaches checkout while Time remains above 0, process the sale or Missed result.
8. Remove the customer after checkout and initialize a new random 1.5–3.0 second spawn wait.
9. Update Money, Time, Missed, and Stock displays.

When Time reaches 0:
- The game enters `closed`.
- Any unfinished customer is removed without checkout.
- Customer spawning stops.
- Restocking is disabled.
- Final results are displayed.

While `closed`, no gameplay values change and only R is active.

Pressing R fully restores the initial values and creates a new random customer spawn wait.

The following values remain fixed throughout the session:
- Product types
- Initial Stock
- Maximum Stock: 12 for all products
- Restock quantities
- Restock costs
- Selling prices
- Customer movement duration
- Customer request probabilities
- Customer spawn-wait range
- Business duration

---

# 7. Goal, Feedback & Termination
The player's goal is to manage inventory effectively during the 60-second business period, maximize final Money, and minimize Missed customers.

The game does not use a traditional Victory or Failure result.

The top information area displays:
`Money: X`
`Time: X`
`Missed: X`

Each shelf displays:
`Stock: X`

Each product may hold at most 12 units.

Successful restocking immediately increases the corresponding Stock by 3 and deducts its fixed cost from Money.

A restock is allowed only when the current Stock is at most 9.

Failed restocking changes neither Money nor Stock.

Each active customer enters from the left, moves toward the counter, and displays a fixed request bubble.

If the requested item is available at checkout, Stock decreases by 1 and Money increases by the corresponding selling price. If it is unavailable, Missed increases by 1.

The only automatic termination condition is:
`Time = 0`

When this occurs:
- Enter `closed`.
- Remove any unfinished customer.
- Do not process same-frame checkout or restocking.
- Stop customer spawning and movement.
- Disable restocking.
- Freeze Money, Missed, and inventory against further gameplay changes.

The bottom control area displays:
`Shop Closed`
`Final Money: X`
`Missed: X`
`Press R to Restart`

R is effective in both `open` and `closed` and fully restores the initial game state.

---

# 8. Functional Checkpoints
