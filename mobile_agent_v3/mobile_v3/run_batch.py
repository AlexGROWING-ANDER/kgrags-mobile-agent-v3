import os
import json
import time
import argparse
import traceback
import shutil
from datetime import datetime
from pathlib import Path

from run_mobileagentv3 import run_instruction


DEFAULT_GUI_GUIDANCE = (
    "必须通过当前指定的手机应用实际完成任务并留下可核验的界面轨迹；"
    "不得在尚未操作应用时直接使用 answer 给出常识答案。"
    "只有在已完成必要的应用操作、且任务确实要求向用户返回文本信息时，才可使用 answer。"
)


def load_local_env(env_path: Path) -> None:
    """Load simple KEY=VALUE pairs without overwriting existing environment variables."""
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_intents(intent_json_path):
    """Load intents from a JSON file. Returns list of (test_id, intention)."""
    with open(intent_json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    intents = []
    for key in sorted(data.keys(), key=lambda x: int(x.split("_")[1])):
        intents.append((key, data[key]["intention"]))
    return intents


def run_batch(
    config_path,
    adb_path,
    hdc_path,
    coor_type,
    if_notetaker,
    add_info,
    max_step,
    step_interval,
    log_base,
    resume_from=None,
    min_free_gb=2.0,
    max_tasks=None,
    max_consecutive_errors=None,
    allow_communications=False,
):
    load_local_env(Path(__file__).resolve().parent / ".env")

    # Load experiment config
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    model_cfg = config["model"]
    api_key = os.environ.get("MOBILE_AGENT_API_KEY", model_cfg.get("api_key", ""))
    base_url = os.environ.get("MOBILE_AGENT_BASE_URL", model_cfg["endpoint"])
    model = os.environ.get("MOBILE_AGENT_MODEL", model_cfg["model_name"])
    if not api_key:
        raise ValueError("Missing MOBILE_AGENT_API_KEY. Configure it in mobile_v3/.env.")
    apps = config["apps"]["all"]

    # Load completed intents from previous run
    completed_set = set()
    resume_paths = []
    if isinstance(resume_from, (str, os.PathLike)):
        resume_paths = [resume_from]
    elif resume_from:
        resume_paths = list(resume_from)

    for resume_path in resume_paths:
        if not os.path.exists(resume_path):
            raise FileNotFoundError(f"Resume summary not found: {resume_path}")
        with open(resume_path, "r", encoding="utf-8") as f:
            prev = json.load(f)
        for result in prev.get("results", []):
            if result.get("status") in {"error", "interrupted", "no_logs"}:
                continue
            completed_set.add((result["app_package"], result["test_id"]))
        print(f"Resume: loaded checkpoint entries from {resume_path}")
    if resume_paths:
        print(f"Resume: {len(completed_set)} unique completed/attempted intents")

    # Create batch log directory
    if not os.path.exists(log_base):
        os.makedirs(log_base)
    now = datetime.now()
    batch_dir = os.path.join(log_base, f"batch_{now.strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(batch_dir)

    results = []
    total_all = sum(len(load_intents(app["intent_json"])) for app in apps if os.path.exists(app["intent_json"]))
    total = total_all - len(completed_set)
    current = 0
    stopped_for_space = False
    stopped_for_errors = False
    consecutive_errors = 0

    print(f"{'='*70}")
    print(f"Batch Run | Model: {model} | Apps: {len(apps)} | Total intents: {total_all} | To run: {total}")
    print(f"Log dir: {batch_dir}")
    print(f"{'='*70}\n")

    for app in apps:
        app_package = app["app_package"]
        app_name = app["app_name"]
        intent_json_path = app["intent_json"]

        if not os.path.exists(intent_json_path):
            print(f"[SKIP] {app_name} ({app_package}): intent file not found: {intent_json_path}")
            continue

        intents = load_intents(intent_json_path)
        app_log_dir = os.path.join(batch_dir, app_package)
        os.makedirs(app_log_dir, exist_ok=True)
        status = "skipped"

        for test_id, intention in intents:
            if (app_package, test_id) in completed_set:
                print(f"[SKIP] {app_name}/{test_id} (already completed in previous run)")
                continue
            if max_tasks is not None and current >= max_tasks:
                print(f"[STOP] Reached the requested task limit: {max_tasks}.")
                break
            free_gb = shutil.disk_usage(log_base).free / (1024 ** 3)
            if free_gb < min_free_gb:
                stopped_for_space = True
                print(
                    f"[STOP] Free space at {log_base} is {free_gb:.2f} GB, "
                    f"below the safety threshold of {min_free_gb:.2f} GB."
                )
                break
            current += 1
            safe_prefix = "".join(c for c in intention[:15] if c.isalnum() or c in (" ", "-", "_")).strip()
            intent_log_dir = os.path.join(app_log_dir, f"{test_id}_{safe_prefix}")

            print(f"\n{'='*70}")
            print(f"[{current}/{total}] {app_name} | {test_id}")
            print(f"  Intent: {intention}")
            print(f"  Package: {app_package}")
            print(f"  Log: {intent_log_dir}")
            print(f"{'='*70}\n")

            start_time = time.time()
            status = "unknown"
            error_msg = ""

            try:
                run_instruction(
                    adb_path=adb_path,
                    hdc_path=hdc_path,
                    api_key=api_key,
                    base_url=base_url,
                    model=model,
                    instruction=intention,
                    add_info=add_info,
                    coor_type=coor_type,
                    if_notetaker=if_notetaker,
                    app_package=app_package,
                    max_step=max_step,
                    log_path=app_log_dir,
                    step_interval=step_interval,
                    allow_communications=allow_communications,
                )

                # Check if task_result.json was written
                # Find the latest log subdir for this intent
                subdirs = sorted(
                    [d for d in os.listdir(app_log_dir) if os.path.isdir(os.path.join(app_log_dir, d)) and d.startswith("20")],
                    reverse=True
                )
                if subdirs:
                    result_file = os.path.join(app_log_dir, subdirs[0], "task_result.json")
                    if os.path.exists(result_file):
                        with open(result_file, "r", encoding="utf-8") as f:
                            task_result = json.load(f)
                        if task_result.get("requires_human_confirmation"):
                            status = "human_confirmation"
                        elif task_result.get("hit_step_limit") == 0.0:
                            status = "success"
                        else:
                            status = "step_limit"
                    else:
                        status = "step_limit"  # ran all steps without writing result
                else:
                    status = "no_logs"

            except KeyboardInterrupt:
                status = "interrupted"
                error_msg = "User interrupted"
                print("\n⚠️  User interrupted. Saving progress and exiting.")
                break
            except Exception as e:
                status = "error"
                error_msg = str(e)
                print(f"\n❌ Error: {e}")
                traceback.print_exc()

            elapsed = time.time() - start_time

            result_entry = {
                "app_name": app_name,
                "app_package": app_package,
                "test_id": test_id,
                "intention": intention,
                "status": status,
                "error": error_msg,
                "elapsed_sec": round(elapsed, 1),
            }
            results.append(result_entry)

            if status == "error":
                consecutive_errors += 1
            else:
                consecutive_errors = 0

            print(f"\n📊 [{current}/{total}] {app_name}/{test_id} => {status} ({elapsed:.1f}s)")

            # Save incremental summary after each intent
            summary_path = os.path.join(batch_dir, "summary.json")
            with open(summary_path, "w", encoding="utf-8") as f:
                json.dump({
                    "model": model,
                    "total": total,
                    "completed": len(results),
                    "success": sum(1 for r in results if r["status"] == "success"),
                    "human_confirmation": sum(1 for r in results if r["status"] == "human_confirmation"),
                    "step_limit": sum(1 for r in results if r["status"] == "step_limit"),
                    "error": sum(1 for r in results if r["status"] == "error"),
                    "results": results,
                }, f, ensure_ascii=False, indent=2)

            if (
                max_consecutive_errors is not None
                and consecutive_errors >= max_consecutive_errors
            ):
                stopped_for_errors = True
                print(
                    f"[STOP] Reached {consecutive_errors} consecutive errors; "
                    "stopping to avoid producing a run of invalid trajectories."
                )
                break

        if (
            status == "interrupted"
            or stopped_for_space
            or stopped_for_errors
            or (max_tasks is not None and current >= max_tasks)
        ):
            break

    # Final summary
    success_count = sum(1 for r in results if r["status"] == "success")
    human_confirmation_count = sum(1 for r in results if r["status"] == "human_confirmation")
    step_limit_count = sum(1 for r in results if r["status"] == "step_limit")
    error_count = sum(1 for r in results if r["status"] == "error")

    print(f"\n{'='*70}")
    print(f"BATCH COMPLETE")
    print(f"  Total:      {len(results)}/{total}")
    print(f"  Success:    {success_count}")
    print(f"  Confirm:    {human_confirmation_count}")
    print(f"  Step Limit: {step_limit_count}")
    print(f"  Error:      {error_count}")
    print(f"  Disk Stop:  {stopped_for_space}")
    print(f"  Error Stop: {stopped_for_errors}")
    print(f"  Summary:    {os.path.join(batch_dir, 'summary.json')}")
    print(f"{'='*70}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Batch run all intents from experiment config")
    parser.add_argument("--config", type=str, required=True, help="Path to experiments config JSON")
    parser.add_argument("--adb_path", type=str, default=None)
    parser.add_argument("--hdc_path", type=str, default=None)
    parser.add_argument(
        "--coor_type",
        type=str,
        default="abs",
        choices=("abs", "qwen-vl"),
        help="Coordinate convention: GPT/OpenLux uses abs; qwen-vl uses 0..1000 normalized coordinates",
    )
    parser.add_argument(
        "--notetaker",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Enable or disable the optional NoteKeeper agent (default: disabled)",
    )
    parser.add_argument("--add_info", type=str, default=DEFAULT_GUI_GUIDANCE)
    parser.add_argument("--max_step", type=int, default=30)
    parser.add_argument('--allow-communications',action='store_true')
    parser.add_argument("--step_interval", type=int, default=5, help="Seconds to wait between each step (default: 5)")
    parser.add_argument(
        "--resume_from",
        type=str,
        action="append",
        default=None,
        help="Checkpoint summary to skip; repeat this option to merge multiple summaries",
    )
    parser.add_argument(
        "--max_tasks",
        type=int,
        default=None,
        help="Maximum number of new intents to run in this batch",
    )
    parser.add_argument(
        "--min_free_gb",
        type=float,
        default=2.0,
        help="Stop safely before a new intent when log volume has less free space than this (default: 2 GB)",
    )
    parser.add_argument(
        "--max_consecutive_errors",
        type=int,
        default=None,
        help="Stop after this many consecutive task errors (default: disabled)",
    )
    parser.add_argument(
        "--log_base",
        type=str,
        default=os.environ.get("MOBILE_AGENT_LOG_BASE", "E:/GUI_AGENT_runs/mobile_agent_v3/logs"),
    )
    args = parser.parse_args()

    run_batch(
        config_path=args.config,
        adb_path=args.adb_path,
        hdc_path=args.hdc_path,
        coor_type=args.coor_type,
        if_notetaker=args.notetaker,
        add_info=args.add_info,
        max_step=args.max_step,
        step_interval=args.step_interval,
        log_base=args.log_base,
        resume_from=args.resume_from,
        min_free_gb=args.min_free_gb,
        max_tasks=args.max_tasks,
        max_consecutive_errors=args.max_consecutive_errors,
        allow_communications=args.allow_communications,
    )
