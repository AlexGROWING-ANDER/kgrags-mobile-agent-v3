import os
import uuid
import json
import time
import argparse
import ast
import re
from PIL import Image
from datetime import datetime

from utils.mobile_agent_e import (
    InfoPool, 
    Manager, 
    Executor, 
    Notetaker, 
    ActionReflector,
    INPUT_KNOW
)
import utils.controller as controller
from utils.call_mobile_agent_e import GUIOwlWrapper
from communication_permissions import authorized_communication


def sanitize_path_component(value, max_length=40):
    """Return a Windows-safe, non-empty directory-name component."""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value))
    value = re.sub(r"\s+", "_", value).strip(" ._")
    value = value[:max_length].rstrip(" .")
    return value or "task"


def prepare_action_coordinates(action_object, coor_type, width, height):
    """Convert normalized coordinates when requested and reject off-screen points."""
    converted = dict(action_object)
    for key in ("coordinate", "coordinate2"):
        if key not in converted:
            continue
        point = converted[key]
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError(f"{key} must contain exactly two numbers")
        x, y = float(point[0]), float(point[1])
        if coor_type != "abs":
            if not (0 <= x <= 1000 and 0 <= y <= 1000):
                raise ValueError(f"normalized {key} is outside 0..1000: {point}")
            x, y = x / 1000 * width, y / 1000 * height
        x, y = int(x), int(y)
        if not (0 <= x < width and 0 <= y < height):
            raise ValueError(
                f"{key} is outside screenshot bounds {width}x{height}: {[x, y]}"
            )
        converted[key] = [x, y]
    return converted


CONSEQUENTIAL_CONFIRMATION_PATTERNS = (
    r"点击.{0,12}(?:发送|发布|发表评论|确认关注|提交订单|确认下单|立即购买|立即支付|确认支付)",
    r"(?:确认发送|发送邮件|发送按钮|发布按钮|评论按钮|点赞按钮|关注按钮|提交订单)",
)


def is_consequential_confirmation(action_object, action_description, allow_communications=False):
    """Return True when a click would create an external side effect."""
    if action_object.get("action") != "click":
        return False
    description = str(action_description or "")
    if allow_communications and authorized_communication(description):
        return False
    return any(re.search(pattern, description) for pattern in CONSEQUENTIAL_CONFIRMATION_PATTERNS)


def capture_screenshot_or_raise(controller, save_path, attempts=5, retry_delay=5):
    """Capture a fully validated screenshot or fail the current task clearly."""
    for attempt in range(1, attempts + 1):
        if controller.get_screenshot(save_path):
            return
        print(f"Get screenshot failed ({attempt}/{attempts}), retry.")
        if attempt < attempts:
            time.sleep(retry_delay)
    raise RuntimeError(
        f"Failed to capture a valid screenshot after {attempts} attempts: {save_path}"
    )

def run_instruction(adb_path, hdc_path, api_key, base_url, model, instruction, add_info, coor_type, if_notetaker, app_package=None, max_step=30, log_path="./logs", step_interval=5, allow_communications=False):
    if adb_path and hdc_path:
        raise ValueError("adb_path and hdc_path cannot be provided at the same time. Please specify only one of them.")
    if adb_path:
        from utils.android_controller import AndroidController
        controller = AndroidController(adb_path)
    else:
        from utils.harmonyos_controller import HarmonyOSController
        controller = HarmonyOSController(hdc_path)

    if not os.path.exists(log_path):
        os.mkdir(log_path)
    
    now = datetime.now()
    time_str = now.strftime("%Y%m%d_%H%M%S")
    safe_instruction = sanitize_path_component(instruction[:30])
    save_path = os.path.join(log_path, f"{time_str}_{safe_instruction}")
    os.mkdir(save_path)
    image_save_path = os.path.join(save_path, "images")
    os.mkdir(image_save_path)

    info_pool = InfoPool(
        additional_knowledge_manager=add_info,
        additional_knowledge_executor=INPUT_KNOW,
        err_to_manager_thresh=2
    )
    
    vllm = GUIOwlWrapper(api_key, base_url, model)
    manager = Manager()
    executor = Executor()
    notetaker = Notetaker()
    action_reflector = ActionReflector()
    message_manager, message_operator, message_reflector, message_notekeeper = None, None, None, None
    info_pool.instruction = instruction

    if app_package:
        print(f"\n### Launching app: {app_package} ###\n")
        controller.stop_app(app_package)
        time.sleep(2)
        controller.home()
        time.sleep(1)
        controller.start_app(app_package)
        time.sleep(5)

    for step in range(max_step):
        if step == max_step:
            task_result_path = os.path.join(save_path, "task_result.json")
            current_time = datetime.now()
            formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S.%f")
            task_result_data = {"goal": instruction, "finish_dtime": formatted_time, "hit_step_limit": 1.0}
            with open(task_result_path, 'w', encoding='utf-8') as json_file:
                json.dump(task_result_data, json_file, ensure_ascii=False, indent=4)
            break
        
        if step == 0:
            current_time = datetime.now()
            formatted_time = current_time.strftime(f'%Y-%m-%d-{current_time.hour * 3600 + current_time.minute * 60 + current_time.second}-{str(uuid.uuid4().hex[:8])}')
            local_image_dir = os.path.join(image_save_path, f"screenshot_{formatted_time}.png")
        else:
            local_image_dir = local_image_dir2
        
        capture_screenshot_or_raise(controller, local_image_dir)
        
        width, height = Image.open(local_image_dir).size
        
        info_pool.error_flag_plan = False
        err_to_manager_thresh = info_pool.err_to_manager_thresh
        if len(info_pool.action_outcomes) >= err_to_manager_thresh:
            # check if the last err_to_manager_thresh actions are all errors
            latest_outcomes = info_pool.action_outcomes[-err_to_manager_thresh:]
            count = 0
            for outcome in latest_outcomes:
                if outcome in ["B", "C"]:
                    count += 1
            if count == err_to_manager_thresh:
                info_pool.error_flag_plan = True

        skip_manager = False
        ## if previous action is invalid, skip the manager and try again first ##
        if not info_pool.error_flag_plan and len(info_pool.action_history) > 0:
            if info_pool.action_history[-1]['action'] == 'invalid':
                skip_manager = True
        
        if not skip_manager:
            print("\n### Manager ... ###\n")
            prompt_planning = manager.get_prompt(info_pool)
            output_planning, message_manager, raw_response = vllm.predict_mm(
                prompt_planning,
                [local_image_dir]
            )
        
        message_save_path = os.path.join(save_path, f"step_{step+1}")
        os.mkdir(message_save_path)
        message_file = os.path.join(message_save_path, "manager.json")
        message_data = {"name": "manager", "messages": message_manager, "response": output_planning, "step_id": step+1}
        with open(message_file, 'w', encoding='utf-8') as json_file:
            json.dump(message_data, json_file, ensure_ascii=False, indent=4)

        parsed_result_planning = manager.parse_response(output_planning)
        info_pool.completed_plan = parsed_result_planning['completed_subgoal']
        info_pool.plan = parsed_result_planning['plan']
        if not raw_response:
            raise RuntimeError('Error calling vLLM in planning phase.')
        
        print('Completed subgoal: ' + info_pool.completed_plan)
        print('Planning thought: ' + parsed_result_planning['thought'])
        print('Plan: ' + info_pool.plan, "\n")
        
        if "Finished" in info_pool.plan.strip() and len(info_pool.plan.strip()) < 15:
            print("Instruction finished, stop the process.")
            task_result_path = os.path.join(save_path, "task_result.json")
            current_time = datetime.now()
            formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S.%f")
            task_result_data = {"goal": instruction, "finish_dtime": formatted_time, "hit_step_limit": 0.0}
            with open(task_result_path, 'w', encoding='utf-8') as json_file:
                json.dump(task_result_data, json_file, ensure_ascii=False, indent=4)
            break
        else:
            print("\n### Operator ... ###\n")

            prompt_action = executor.get_prompt(info_pool)
            output_action, message_operator, raw_response = vllm.predict_mm(
                prompt_action,
                [local_image_dir],
            )
            
            if not raw_response:
                raise RuntimeError('Error calling LLM in operator phase.')
            parsed_result_action = executor.parse_response(output_action)
            action_thought, action_object_str, action_description = parsed_result_action['thought'], parsed_result_action['action'], parsed_result_action['description']
            
            info_pool.last_action_thought = action_thought
            info_pool.last_summary = action_description
            
            if (not action_thought) or (not action_object_str):
                print('Action prompt output is not in the correct format.')
                info_pool.last_action = {"action": "invalid"}
                info_pool.action_history.append({"action": "invalid"})
                info_pool.summary_history.append(action_description)
                info_pool.action_outcomes.append("C")
                info_pool.error_descriptions.append("invalid action format, do nothing.")
                local_image_dir2 = local_image_dir
                continue
        
        action_object_str = action_object_str.replace("```", "").replace("json", "").strip()
        print('Thought: ' + action_thought)
        print('Action: ' + action_object_str)
        print('Action description: ' + action_description)

        try:
            # Some models return Python-dict style actions with single quotes.
            try:
                action_object = json.loads(action_object_str)
            except json.JSONDecodeError:
                action_object = ast.literal_eval(action_object_str)
                if not isinstance(action_object, dict):
                    raise ValueError("action_object must be a dict")
            operator_response = f'''### Thought ###
{action_thought}

### Action ###
{action_object}

### Description ###
{action_description}'''
            
            if action_object['action'] == "answer":
                message_file = os.path.join(message_save_path, "operator.json")
                message_data = {"name": "operator", "messages": message_operator, "response": operator_response, "step_id": step+1}
                with open(message_file, 'w', encoding='utf-8') as json_file:
                    json.dump(message_data, json_file, ensure_ascii=False, indent=4)

                answer_content = action_object['text']
                print(f"Instruction finished, answer: {answer_content}, stop the process.")
                task_result_path = os.path.join(save_path, "task_result.json")
                current_time = datetime.now()
                formatted_time = current_time.strftime("%Y-%m-%d %H:%M:%S.%f")
                task_result_data = {"goal": instruction, "finish_dtime": formatted_time, "hit_step_limit": 0.0}
                with open(task_result_path, 'w', encoding='utf-8') as json_file:
                    json.dump(task_result_data, json_file, ensure_ascii=False, indent=4)
                break

            if is_consequential_confirmation(action_object, action_description, allow_communications):
                message_file = os.path.join(message_save_path, "operator.json")
                message_data = {
                    "name": "operator",
                    "messages": message_operator,
                    "response": operator_response,
                    "step_id": step + 1,
                }
                with open(message_file, "w", encoding="utf-8") as json_file:
                    json.dump(message_data, json_file, ensure_ascii=False, indent=4)

                task_result_path = os.path.join(save_path, "task_result.json")
                task_result_data = {
                    "goal": instruction,
                    "finish_dtime": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "hit_step_limit": 0.0,
                    "requires_human_confirmation": True,
                    "blocked_action": action_object,
                    "blocked_description": action_description,
                }
                with open(task_result_path, "w", encoding="utf-8") as json_file:
                    json.dump(task_result_data, json_file, ensure_ascii=False, indent=4)
                print(
                    "[HUMAN CONFIRMATION REQUIRED] Consequential action was not executed: "
                    + action_description
                )
                break
            
            action_object = prepare_action_coordinates(
                action_object, coor_type, width, height
            )
            
            if action_object['action'] == "click":
                controller.tap(action_object['coordinate'][0], action_object['coordinate'][1])
            elif action_object['action'] == "swipe":
                controller.slide(action_object['coordinate'][0], action_object['coordinate'][1], action_object['coordinate2'][0], action_object['coordinate2'][1])
            elif action_object['action'] == "type":
                controller.type(action_object['text'])
            elif action_object['action'] == "system_button":
                if action_object['button'] == "Back":
                    controller.back()
                elif action_object['button'] == "Home":
                    controller.home()
            
        except:
            info_pool.last_action = {"action": "invalid"}
            info_pool.action_history.append({"action": "invalid"})
            info_pool.summary_history.append(action_description)
            info_pool.action_outcomes.append("C")
            info_pool.error_descriptions.append("invalid action format, do nothing.")
            local_image_dir2 = local_image_dir
            continue
        
        message_file = os.path.join(message_save_path, "operator.json")
        message_data = {"name": "operator", "messages": message_operator, "response": operator_response, "step_id": step+1}
        with open(message_file, 'w', encoding='utf-8') as json_file:
            json.dump(message_data, json_file, ensure_ascii=False, indent=4)

        info_pool.last_action = action_object
        
        if step == 0:
            time.sleep(8) # maybe a pop-up when first open an app
        time.sleep(2)
        
        current_time = datetime.now()
        formatted_time = current_time.strftime(f'%Y-%m-%d-{current_time.hour * 3600 + current_time.minute * 60 + current_time.second}-{str(uuid.uuid4().hex[:8])}')
        local_image_dir2 = os.path.join(image_save_path, f"screenshot_{formatted_time}.png")
        
        capture_screenshot_or_raise(controller, local_image_dir2)
        
        print("\n### Action Reflector ... ###\n")
        prompt_action_reflect = action_reflector.get_prompt(info_pool)
        output_action_reflect, message_reflector, raw_response = vllm.predict_mm(
            prompt_action_reflect,
            [
                local_image_dir,
                local_image_dir2,
            ],
        )
        
        message_file = os.path.join(message_save_path, "reflector.json")
        message_data = {"name": "reflector", "messages": message_reflector, "response": output_action_reflect, "step_id": step+1}
        with open(message_file, 'w', encoding='utf-8') as json_file:
            json.dump(message_data, json_file, ensure_ascii=False, indent=4)
        
        parsed_result_action_reflect = action_reflector.parse_response(output_action_reflect)
        outcome, error_description = (
            parsed_result_action_reflect['outcome'], 
            parsed_result_action_reflect['error_description']
        )
        progress_status = info_pool.completed_plan
        
        if "A" in outcome: # Successful. The result of the last action meets the expectation.
          action_outcome = "A"
        elif "B" in outcome: # Failed. The last action results in a wrong page. I need to return to the previous state.
            action_outcome = "B"
        elif "C" in outcome: # Failed. The last action produces no changes.
            action_outcome = "C"
        else:
            raise ValueError("Invalid outcome:", outcome)
        
        print('Action reflection outcome: ' + action_outcome)
        print('Action reflection error description: ' + error_description)
        print('Action reflection progress status: ' + progress_status, "\n")
        
        info_pool.action_history.append(action_object)
        info_pool.summary_history.append(action_description)
        info_pool.action_outcomes.append(action_outcome)
        info_pool.error_descriptions.append(error_description)
        info_pool.progress_status = progress_status
        
        if action_outcome == "A" and if_notetaker:
            print("\n### NoteKeeper ... ###\n")
            prompt_note = notetaker.get_prompt(info_pool)
            output_note, message_notekeeper, raw_response = vllm.predict_mm(
                prompt_note,
                [local_image_dir2],
            )
            
            message_file = os.path.join(message_save_path, "notekeeper.json")
            message_data = {"name": "notekeeper", "messages": message_notekeeper, "response": output_note, "step_id": step+1}
            with open(message_file, 'w', encoding='utf-8') as json_file:
                json.dump(message_data, json_file, ensure_ascii=False, indent=4)
            
            parsed_result_note = notetaker.parse_response(output_note)
            important_notes = parsed_result_note['important_notes']
            info_pool.important_notes = important_notes

            print('Important notes: ' + important_notes, "\n")

        if step_interval > 0:
            print(f"\n### Waiting {step_interval}s before next step... ###\n")
            time.sleep(step_interval)

    # Python's range(max_step) never yields step == max_step. Ensure a run that
    # exhausts every step still records a terminal result for batch accounting.
    task_result_path = os.path.join(save_path, "task_result.json")
    if not os.path.exists(task_result_path):
        current_time = datetime.now()
        task_result_data = {
            "goal": instruction,
            "finish_dtime": current_time.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "hit_step_limit": 1.0,
        }
        with open(task_result_path, "w", encoding="utf-8") as json_file:
            json.dump(task_result_data, json_file, ensure_ascii=False, indent=4)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Run Mobile-Agent-v3 with a given model and instruction"
    )
    parser.add_argument("--adb_path", type=str)
    parser.add_argument("--hdc_path", type=str)   
    parser.add_argument("--api_key", type=str)
    parser.add_argument("--base_url", type=str)
    parser.add_argument("--model", type=str)
    parser.add_argument("--instruction", type=str)
    parser.add_argument("--app_package", type=str, default=None, help="App package name to launch before running (e.g. com.android.settings)")
    parser.add_argument("--add_info", type=str, default="")
    parser.add_argument("--coor_type", type=str, default="abs")
    parser.add_argument(
        "--notetaker",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable or disable the optional NoteKeeper agent (default: disabled)",
    )
    parser.add_argument("--max_step", type=int, default=30, help="Maximum number of steps (default: 30)")
    parser.add_argument("--step_interval", type=int, default=5, help="Seconds to wait between each step (default: 5)")
    parser.add_argument('--allow-communications',action='store_true',help='Explicit consent for task-directed sending/publishing; does not permit payments')
    args = parser.parse_args()

    run_instruction(args.adb_path, args.hdc_path, args.api_key, args.base_url, args.model, args.instruction, args.add_info, args.coor_type, args.notetaker, args.app_package, args.max_step, "./logs", args.step_interval, args.allow_communications)
