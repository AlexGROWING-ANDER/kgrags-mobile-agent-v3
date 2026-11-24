# Mobile-Agent-v3 Architecture Document

## Overview

Mobile-Agent-v3 is a **multi-agent GUI automation system** for Android and HarmonyOS mobile devices. It employs a manager-operator-reflector architecture where multiple LLM-based agents coordinate through a shared state pool to execute complex user instructions on mobile devices.

**Core Philosophy**: Separate planning from execution, with continuous reflection and memory management.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Main Loop Controller                          │
│                  (run_mobileagentv3.py)                              │
└────────────────────┬────────────────────────────────────────────────┘
                     │
        ┌────────────┼────────────┬────────────┬────────────┐
        │            │            │            │            │
        ▼            ▼            ▼            ▼            ▼
   ┌─────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐  ┌──────────┐
   │ Manager │→ │ Executor │→ │Controller│→ │Reflector│→ │Notetaker │
   └────┬────┘  └────┬─────┘  └──────────┘  └────┬────┘  └──────────┘
        │            │                            │
        └────────────┴──────────┬─────────────────┘
                                │
                                ▼
                        ┌──────────────┐
                        │   InfoPool   │
                        │ (shared state)│
                        └──────────────┘
```

---

## Module Breakdown

### 1. **InfoPool** (Shared State Memory)
**File**: `utils/mobile_agent_e.py` (lines 6-44)

**Responsibility**: Central repository for all cross-agent information. Tracks:
- User instruction and additional knowledge
- UI element lists (before/after action)
- Action history, outcomes, and error descriptions
- Planning state (plan, completed subgoals, progress)
- Important notes (from Notetaker)
- Error flags for stuck detection

**Key Fields**:
- `action_history`: List of executed actions
- `action_outcomes`: List of outcome codes (A/B/C)
- `error_flag_plan`: Boolean flag when errors exceed threshold (default: 2 consecutive failures)
- `plan` / `completed_plan`: Current high-level plan and completed subgoals
- `important_notes`: Accumulated observations from Notetaker

**Cognitive Stage Mapping**: 
- **Memory/History** component (supports all cognitive stages)
- **Context** management (provides historical context to Manager/Executor)

---

### 2. **Manager** (High-Level Planner)
**File**: `utils/mobile_agent_e.py` (lines 56-154)

**Responsibility**: 
- Break down user instruction into subgoals
- Track progress and revise plan when stuck
- Detect task completion
- Handle error recovery at planning level

**Input**: 
- Screenshot (current page state)
- InfoPool (instruction, history, error flags)
- Additional knowledge (task-specific guidelines)

**Output**:
- `thought`: Reasoning for plan decision
- `plan`: Ordered list of subgoals
- `completed_subgoal`: Recently completed subgoal (if any)

**Key Logic**:
- **First-time planning**: Breaks instruction into subgoals with guidelines
- **Plan revision**: Checks if plan needs update based on progress and errors
- **Stuck detection**: When `error_flag_plan=True` (2+ consecutive errors), prompts for plan revision
- **Completion detection**: If plan contains "Finished", terminates task

**Cognitive Stage Mapping**:
- **Goal Decision**: Decides what to do next (subgoal selection)
- **Layout Understanding**: Understands page structure to plan appropriately
- **History Forgetting Prevention**: Tracks completed subgoals to avoid repetition
- **Recovery Planning**: Revises plan when stuck

**Failure Modes**:
- Wrong Goal: Misinterprets user instruction or plans inappropriate subgoal
- Premature Termination: Incorrectly marks task as "Finished"
- Failure to Terminate: Continues operating after task is complete
- History Forgetting: Repeats completed subgoals

---

### 3. **Executor** (Action Decider)
**File**: `utils/mobile_agent_e.py` (lines 187-272)

**Responsibility**:
- Decide the next concrete action based on current plan and page state
- Choose from atomic actions: click, swipe, type, system_button, answer
- Handle coordinate calculation and text input

**Input**:
- Screenshot (current page state)
- InfoPool (plan, progress status, action history, guidelines)
- Atomic action signatures (available actions with descriptions)

**Output**:
- `thought`: Reasoning for action choice
- `action`: JSON object specifying action type and parameters (e.g., `{"action": "click", "coordinate": [x, y]}`)
- `description`: Brief description of the action

**Key Logic**:
- Examines current subgoal and progress status
- Reviews last 5 actions and their outcomes
- Selects one atomic action from available options
- Avoids repeating failed actions

**Atomic Actions** (defined in `new_json_action.py`):
- `click(coordinate)`: Tap at (x, y)
- `long_press(coordinate)`: Long press at (x, y)
- `swipe(coordinate, coordinate2)`: Swipe from (x1,y1) to (x2,y2)
- `type(text)`: Input text into active field
- `system_button(button)`: Press Back/Home/Enter
- `answer(text)`: Output final answer (terminates task)

**Cognitive Stage Mapping**:
- **Observation (Widget Level)**: Perceives UI elements in screenshot
- **Target Selection**: Decides which element to interact with
- **Parameter Decision**: Determines action parameters (coordinates, text, direction)
- **Goal Execution**: Aligns action with current subgoal

**Failure Modes**:
- Observation Error: Misidentifies UI element or its state
- Target Error: Chooses wrong element to interact with
- Parameter Error: Wrong coordinates, text, or swipe direction
- Goal Deviation: Action doesn't serve current subgoal

---

### 4. **ActionReflector** (Outcome Verifier)
**File**: `utils/mobile_agent_e.py` (lines 274-315)

**Responsibility**:
- Verify whether the last action produced expected behavior
- Classify outcome as A (success), B (wrong page), or C (no change)
- Provide error description for failed actions
- Update progress status

**Input**:
- Two screenshots: before and after the action
- InfoPool (last action, last summary, completed subgoals)

**Output**:
- `outcome`: A (successful), B (wrong page, need to return), C (no change)
- `error_description`: Detailed error analysis (or "None" if successful)

**Key Logic**:
- Compares before/after screenshots
- Checks if action result matches expectation (from Executor's description)
- For swipe actions: checks if content actually scrolled (same content = C)
- Provides reasoning for failure mode

**Cognitive Stage Mapping**:
- **Observation (Page Level)**: Compares page states before/after
- **Recovery Detection**: Identifies when action failed and suggests return
- **Progress Tracking**: Updates what has been achieved

**Failure Modes**:
- False Positive: Marks failed action as successful (A when should be B/C)
- False Negative: Marks successful action as failed
- Misclassification: Wrong outcome code (B vs C)
- Poor Error Description: Vague or incorrect error analysis

---

### 5. **Notetaker** (Memory Manager) - Optional
**File**: `utils/mobile_agent_e.py` (lines 317-350)

**Responsibility**:
- Record important observations relevant to user request
- Accumulate notes across steps
- Filter out low-level action details

**Input**:
- Screenshot (current page state after successful action)
- InfoPool (instruction, progress status, existing notes)

**Output**:
- `important_notes`: Updated notes combining old and new observations

**Key Logic**:
- Only activated when action outcome is A (successful)
- Focuses on significant textual/visual information
- Avoids recording low-level actions or repeating progress status
- Task-specific guidelines (e.g., only record DCIM transactions)

**Cognitive Stage Mapping**:
- **Memory Management**: Selectively stores relevant information
- **Observation Filtering**: Identifies what's worth remembering

**Failure Modes**:
- Over-recording: Captures irrelevant details
- Under-recording: Misses important information
- Hallucination: Records information not present in screenshot

---

### 6. **GUIOwlWrapper** (LLM Interface)
**File**: `utils/call_mobile_agent_e.py` (lines 62-140)

**Responsibility**:
- Wrap OpenAI-compatible LLM API (e.g., GUIOwl, vLLM)
- Handle multimodal inputs (text + images)
- Manage retries and error handling
- Convert image paths to base64

**Input**:
- Text prompt
- List of image paths

**Output**:
- Text response from LLM
- Message payload (for debugging)
- Raw API response

**Key Features**:
- Automatic image resizing (using `qwen_vl_utils.smart_resize`)
- Retry logic (max 10 retries, 20s wait)
- Base64 encoding for images
- OpenAI-compatible API format

**Cognitive Stage Mapping**: 
- **Infrastructure**: Not a cognitive module, just LLM access layer

---

### 7. **Controller** (Device Interface)
**File**: `utils/controller.py` (abstract), `android_controller.py`, `harmonyos_controller.py`

**Responsibility**:
- Abstract interface for device control
- Platform-specific implementations (Android via adb, HarmonyOS via hdc)
- Execute physical actions on device

**Methods**:
- `get_screenshot(save_path)`: Capture and pull screenshot
- `tap(x, y)`: Click at coordinates
- `slide(x1, y1, x2, y2)`: Swipe gesture
- `type(text)`: Input text (character-by-character for special chars)
- `back()`: Press back button
- `home()`: Return to home screen

**Key Implementation Details**:
- **Android**: Uses `adb shell` commands (input tap, input swipe, screencap)
- **HarmonyOS**: Uses `hdc shell uitest` commands
- **Text Input**: Handles special characters via ADB broadcast or keyEvent
- **Screenshot**: Saves to device storage, then pulls to local path

**Cognitive Stage Mapping**:
- **Execution Layer**: Physical action execution (no cognition)
- **Parameter Translation**: Converts logical coordinates to device commands

---

### 8. **Main Loop** (Orchestrator)
**File**: `run_mobileagentv3.py` (lines 21-323)

**Responsibility**:
- Orchestrate the multi-agent workflow
- Manage step-by-step execution
- Handle device initialization and screenshot capture
- Log all agent interactions to disk

**Workflow** (per step):
1. **Capture Screenshot** (Controller)
2. **Manager Planning** (or skip if last action was invalid)
3. **Executor Action Decision**
4. **Controller Execute Action**
5. **Wait** (2s normally, 8s for first step to handle pop-ups)
6. **Capture New Screenshot**
7. **ActionReflector Verification**
8. **Notetaker** (if outcome=A and enabled)
9. **Update InfoPool** with action history and outcomes
10. **Check Termination** (plan="Finished" or action="answer")

**Key Logic**:
- **Stuck Detection**: If last `err_to_manager_thresh` (default 2) actions are B/C, sets `error_flag_plan=True`
- **Skip Manager**: If last action was "invalid", skip Manager and retry Executor
- **Coordinate Scaling**: Converts relative coordinates (0-1000) to absolute pixels if `coor_type != "abs"`
- **Error Handling**: Catches JSON parse errors, marks action as "invalid" and continues

**Termination Conditions**:
- Manager outputs plan containing "Finished"
- Executor outputs action="answer"
- Max steps reached (default 25)

---

## Data Flow Diagram

```
Step N:
─────────────────────────────────────────────────────────────────────

1. Screenshot Capture
   Controller.get_screenshot() → screenshot_N.png
                                    ↓
2. Manager Planning
   Manager.get_prompt(InfoPool) + screenshot_N.png
   → LLM → {thought, plan, completed_subgoal}
   → Update InfoPool.plan, InfoPool.completed_plan
                                    ↓
3. Executor Action Decision
   Executor.get_prompt(InfoPool) + screenshot_N.png
   → LLM → {thought, action, description}
   → Update InfoPool.last_action, InfoPool.last_summary
                                    ↓
4. Controller Execute Action
   Parse action JSON → Controller.tap/swipe/type/etc.
                                    ↓
5. Wait (2s or 8s for first step)
                                    ↓
6. New Screenshot Capture
   Controller.get_screenshot() → screenshot_N+1.png
                                    ↓
7. ActionReflector Verification
   ActionReflector.get_prompt(InfoPool) + [screenshot_N, screenshot_N+1]
   → LLM → {outcome, error_description}
   → Update InfoPool.action_outcomes, InfoPool.error_descriptions
                                    ↓
8. Notetaker (if outcome=A and enabled)
   Notetaker.get_prompt(InfoPool) + screenshot_N+1.png
   → LLM → {important_notes}
   → Update InfoPool.important_notes
                                    ↓
9. Update InfoPool History
   Append to InfoPool.action_history, InfoPool.summary_history
                                    ↓
10. Check Termination
    If plan="Finished" or action="answer" → STOP
    Else → Go to Step N+1
```

---

## Cognitive Pipeline Mapping

This section maps Mobile-Agent-v3 modules to the **Cognitive Pipeline Taxonomy** used in failure attribution:

| Cognitive Stage | Primary Module | Secondary Module | Description |
|-----------------|----------------|------------------|-------------|
| **Observation (Page Level)** | Executor | ActionReflector | Executor perceives current page state; Reflector compares before/after |
| **Observation (Widget Level)** | Executor | — | Executor identifies specific UI elements to interact with |
| **Layout Understanding** | Manager | Executor | Manager understands page structure for planning; Executor for action selection |
| **Goal Decision** | Manager | — | Manager decides next subgoal and overall plan |
| **Target Selection** | Executor | — | Executor chooses which element to click/swipe/type |
| **Execution (Parameter)** | Executor | Controller | Executor determines coordinates/text; Controller executes |
| **Memory/History** | InfoPool | Notetaker | InfoPool stores all history; Notetaker selectively records important info |
| **Recovery Planning** | Manager | ActionReflector | Manager revises plan when stuck; Reflector identifies failure mode |

---

## Failure Attribution Guide

When attributing failures in Mobile-Agent-v3, use this mapping to identify the responsible module:

### Model Issue Failures

| L2 Category | L3 Example | Responsible Module | Typical Root Cause |
|-------------|------------|-------------------|-------------------|
| **Observation (Page)** | Page Misidentification | Executor | Executor misidentifies current page type |
| **Observation (Page)** | Page State Not Perceived | Executor / ActionReflector | Executor doesn't notice loading state; Reflector doesn't catch it |
| **Observation (Widget)** | Target Widget Missing | Executor | Executor fails to detect required UI element |
| **Observation (Widget)** | Semantic Recognition Error | Executor | Executor misidentifies element's function (e.g., confuses share icon with bookmark) |
| **Layout Understanding** | Wrong Container Assignment | Executor | Executor misattributes element to wrong container |
| **Goal** | Wrong Goal | Manager | Manager plans inappropriate subgoal |
| **Goal** | Premature Termination | Manager | Manager incorrectly marks task as "Finished" |
| **Goal** | History Forgetting | Manager | Manager repeats completed subgoal |
| **Target** | Wrong Interaction Target | Executor | Executor chooses wrong element to interact with |
| **Execution** | Wrong Coordinate | Executor | Executor calculates wrong click coordinates |
| **Execution** | Wrong Text | Executor | Executor inputs incorrect text |
| **Execution** | Wrong Direction | Executor | Executor swipes in wrong direction |

### App Failure (Not Module Fault)

| L3 Category | Description | Note |
|-------------|-------------|------|
| Operation No Response | App doesn't respond to correct action | Controller executed correctly, but App ignored |
| Incorrect Navigation | App jumps to wrong page | Action was correct, but App navigated incorrectly |
| Unexpected Popup | Non-expected popup appears | External to agent control |
| Page Load Timeout | Page fails to load | Network or App issue |
| App Crash | App crashes or force-closes | External to agent control |
| State Reversal | Completed action is unexpectedly undone | App bug or timing issue |

---

## Key Design Patterns

### 1. **Separation of Concerns**
- **Manager**: High-level planning (what to do)
- **Executor**: Low-level execution (how to do it)
- **Reflector**: Verification (did it work?)
- **Notetaker**: Memory management (what to remember?)

### 2. **Shared State (InfoPool)**
- All agents read from and write to a central state pool
- Enables coordination without direct agent-to-agent communication
- Maintains consistency across the multi-agent system

### 3. **Error Recovery**
- **ActionReflector** detects failures (B/C outcomes)
- **Manager** revises plan when stuck (error_flag_plan)
- **Executor** avoids repeating failed actions
- **Threshold-based escalation**: 2+ consecutive failures trigger plan revision

### 4. **Progressive Planning**
- Manager creates initial plan
- Each step, Manager checks if plan needs revision
- Completed subgoals are tracked separately
- Plan is updated incrementally, not recreated from scratch

### 5. **Optional Memory Management**
- Notetaker is optional (controlled by `if_notetaker` flag)
- Only activated on successful actions
- Prevents information overload by filtering low-level details

---

## Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `max_step` | 25 | Maximum number of steps before termination |
| `err_to_manager_thresh` | 2 | Number of consecutive failures before triggering plan revision |
| `coor_type` | "abs" | Coordinate type: "abs" (absolute pixels) or relative (0-1000) |
| `if_notetaker` | False | Enable/disable Notetaker agent |
| `add_info` | "" | Additional task-specific knowledge for Manager |

---

## File Structure

```
mobile_v3/
├── run_mobileagentv3.py          # Main entry point and orchestration loop
└── utils/
    ├── mobile_agent_e.py         # Agent definitions (InfoPool, Manager, Executor, Reflector, Notetaker)
    ├── call_mobile_agent_e.py    # LLM API wrapper (GUIOwlWrapper)
    ├── controller.py             # Abstract Controller interface
    ├── android_controller.py     # Android implementation (adb)
    ├── harmonyos_controller.py   # HarmonyOS implementation (hdc)
    ├── new_json_action.py        # Atomic action definitions (click, swipe, type, etc.)
    ├── function_call_mobile_answer.py  # Function-call interface for mobile_use tool
    └── schema.py                 # Pydantic schemas for Message/ContentItem/FunctionCall
```

---

## Example Failure Scenarios

### Scenario 1: Wrong Coordinate (Execution Error)
- **What happens**: Executor decides to click search box, but coordinates land on empty space
- **Responsible Module**: Executor (Parameter decision)
- **L2/L3**: Execution / Wrong Coordinate
- **Detection**: ActionReflector sees no change (outcome=C)
- **Recovery**: Executor retries with different coordinates

### Scenario 2: Wrong Goal (Planning Error)
- **What happens**: Manager plans to "open settings" when instruction is to "open gallery"
- **Responsible Module**: Manager (Goal decision)
- **L2/L3**: Goal / Wrong Goal
- **Detection**: ActionReflector may not catch this (actions succeed, but wrong goal)
- **Recovery**: Manager revises plan when progress doesn't match instruction

### Scenario 3: Semantic Recognition Error (Observation Error)
- **What happens**: Executor sees a "share" icon but thinks it's a "bookmark" icon
- **Responsible Module**: Executor (Widget-level observation)
- **L2/L3**: Observation (Widget Level) / Semantic Recognition Error
- **Detection**: ActionReflector sees unexpected result (outcome=B)
- **Recovery**: Executor re-examines screenshot and corrects identification

### Scenario 4: App Failure (Not Agent Fault)
- **What happens**: Executor correctly clicks "submit" button, but App doesn't respond
- **Responsible Module**: None (App issue)
- **L1/L2/L3**: App Failure / Operation No Response
- **Detection**: ActionReflector sees no change (outcome=C)
- **Recovery**: Executor retries; Manager may revise plan if stuck

---

## Summary

Mobile-Agent-v3 is a well-structured multi-agent system that separates planning, execution, verification, and memory management into distinct modules. The architecture enables:

- **Modularity**: Each agent has a clear responsibility
- **Coordination**: Shared InfoPool enables seamless information flow
- **Recovery**: Multiple layers of error detection and correction
- **Flexibility**: Supports both Android and HarmonyOS platforms
- **Extensibility**: Easy to add new agents or modify existing ones

For failure attribution, the key is to identify which module's cognitive stage failed, then trace back to the specific decision point (Manager's goal, Executor's target/parameter, Reflector's verification).
