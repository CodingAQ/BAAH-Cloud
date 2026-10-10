"""
云游戏平台支持：打开云平台APP并启动云游戏，以及云游戏中断后的自动恢复

流程基于集游社(com.jys)实测：
1. 打开云平台（竖屏首页）
2. OCR查找游戏名称，点击游戏入口（"玩过的游戏"列表里的图标在名称上方）
3. 在游戏详情页OCR查找并点击"开始游戏"
4. 等待前台切换为云平台的云游戏页（实测约30-40s），并等待屏幕转为横屏

云游戏中断恢复（recover_cloud_game）：
- 检测信号：前台activity不是云平台的云游戏页（如闪退回详情页/首页）
- 状态路由：详情页直达"开始游戏"；其他界面走完整流程
- 单轮重试 CLOUD_RECOVERY_MAX_TIMES 次后降级：先抛 EmulatorBlockError 重启模拟器一次，
  重启后仍失败则抛 CloudStreamInterruptError（主循环断点续跑，不关模拟器）
"""
import time

from modules.utils import (click, swipe, screenshot, config, ocr_area,
                           get_screenshot_cv_data, logging, istr, CN, EN,
                           OCR_LANG, sleep)
from modules.utils.adb_utils import (open_app, check_app_running,
                                     get_now_running_app, is_cloud_mode,
                                     is_cloud_streaming)
from modules.utils.baah_exceptions import EmulatorBlockError, CloudStreamInterruptError


def _ocr_full_screen():
    """OCR全屏，返回ocr_area的multi_lines结果"""
    cv_data = get_screenshot_cv_data()
    if cv_data is None:
        return []
    height, width = cv_data.shape[:2]
    return ocr_area((0, 0), (width, height), multi_lines=True, ocr_lang=OCR_LANG.ZHS)


def _ocr_find_text(target_text):
    """
    在全屏OCR结果里查找目标文本（忽略空格）

    返回 (中心x, 中心y) 或 None
    """
    for item in _ocr_full_screen():
        text, _, box = item[0], item[1], item[2]
        if target_text in text.replace(" ", ""):
            cx = (box[0][0] + box[1][0]) // 2
            cy = (box[0][1] + box[1][1]) // 2
            return (cx, cy)
    return None


def _get_foreground_activity() -> str:
    """获取当前前台activity（形如 包名/Activity），失败返回空串"""
    try:
        return get_now_running_app() or ""
    except Exception:
        return ""


def _open_cloud_platform() -> bool:
    """打开云平台APP，返回云平台是否成功打开"""
    platform_entry = config.userconfigdict["CLOUD_PLATFORM_ENTRY"]
    if not platform_entry:
        logging.error(istr({
            CN: "未配置云平台入口 CLOUD_PLATFORM_ENTRY",
            EN: "CLOUD_PLATFORM_ENTRY is not configured"
        }))
        return False
    for i in range(3):
        logging.info(istr({
            CN: f"打开云平台 {platform_entry} {i+1}/3",
            EN: f"Open cloud platform {platform_entry} {i+1}/3"
        }))
        open_app(platform_entry)
        sleep(6)
        if check_app_running(platform_entry, printit=False):
            return True
    return False


def _find_and_click_game(game_name) -> bool:
    """
    在云平台界面里OCR查找游戏名称并点击游戏入口

    集游社的布局里，"玩过的游戏"列表的游戏图标在名称文字正上方，
    因此点击名称上方的位置。最多尝试5轮（期间尝试滚动屏幕）
    """
    for i in range(5):
        screenshot()
        # 可能点击后直接开始云游戏了
        if is_cloud_streaming():
            return True
        pos = _ocr_find_text(game_name)
        if pos is not None:
            cx, cy = pos
            # 点击名称上方60像素的位置（游戏图标区域），如果太靠上则直接点击名称
            click_y = max(cy - 60, 30)
            logging.info(istr({
                CN: f"找到游戏 {game_name}，点击 ({cx}, {click_y})",
                EN: f"Found game {game_name}, click ({cx}, {click_y})"
            }))
            click((cx, click_y), sleeptime=3)
            return True
        logging.info(istr({
            CN: f"未找到游戏 {game_name}，尝试滑动页面 {i+1}/5",
            EN: f"Game {game_name} not found, try scrolling {i+1}/5"
        }))
        cv_data = get_screenshot_cv_data()
        if cv_data is not None:
            height, width = cv_data.shape[:2]
            # 上滑回到页面顶部（首页的历史游戏在上方）
            swipe((width // 2, height // 2), (width // 2, height // 5), durationtime=0.3)
        sleep(2)
    logging.warn(istr({
        CN: f"未能在云平台界面找到游戏：{game_name}，请确认已在云平台里手动启动过一次该游戏（出现在玩过的游戏列表中）",
        EN: f"Cannot find game {game_name} in the platform, please make sure you have manually launched it once (appears in the history list)"
    }))
    return False


def _click_start_game() -> bool:
    """在游戏详情页OCR查找并点击"开始游戏"按钮，返回云游戏是否已建立"""
    for i in range(10):
        screenshot()
        if is_cloud_streaming():
            return True
        pos = _ocr_find_text("开始游戏")
        if pos is not None:
            logging.info(istr({
                CN: f"点击开始游戏按钮 {pos}",
                EN: f"Click start game button {pos}"
            }))
            click(pos, sleeptime=5)
        else:
            # 有些游戏点击入口后直接开始云游戏，没有详情页
            logging.info(istr({
                CN: f"未找到开始游戏按钮，等待页面变化 {i+1}/10",
                EN: f"Start game button not found, wait for page change {i+1}/10"
            }))
        sleep(3)
    return False


def _wait_stream_ready() -> bool:
    """
    等待云游戏建立（前台变为云平台的云游戏页）并转为横屏

    返回是否成功
    """
    timeout = float(config.userconfigdict["CLOUD_STREAM_TIMEOUT"])
    start_time = time.time()
    logging.info(istr({
        CN: f"等待云游戏建立，超时时间 {timeout} 秒",
        EN: f"Waiting for cloud game, timeout {timeout} seconds"
    }))
    while time.time() - start_time < timeout:
        screenshot()
        if is_cloud_streaming():
            logging.info(istr({
                CN: "云游戏已建立，等待画面转为横屏",
                EN: "Cloud game established, waiting for landscape"
            }))
            # 等待云游戏画面转为横屏（云平台的云游戏页会自动旋转）
            while time.time() - start_time < timeout:
                screenshot()
                cv_data = get_screenshot_cv_data()
                if cv_data is not None and cv_data.shape[0] < cv_data.shape[1]:
                    return True
                sleep(3)
            logging.warn(istr({
                CN: "等待横屏超时，继续执行后续任务",
                EN: "Timeout waiting for landscape, continue tasks"
            }))
            return True
        sleep(3)
    logging.warn(istr({
        CN: f"等待云游戏建立超时({int(timeout)}秒)",
        EN: f"Timeout waiting for cloud game ({int(timeout)} seconds)"
    }))
    return False


def _claim_daily_duration() -> None:
    """
    启动云平台后OCR检查是否有"签到并领取时长"按钮（每日福利），有就点击领取

    点击后可能出现确认弹窗，尝试点掉常见确认按钮。
    检查/领取失败只记录警告，不影响后续进入游戏的流程。
    """
    # 按钮文案候选（主文案在前，兼容可能的变体）
    claim_texts = ["签到并领取时长", "签到领时长", "领取时长"]
    # 已领取状态文案，出现则直接跳过
    claimed_texts = ["已领取", "已签到"]
    try:
        for _ in range(3):
            screenshot()
            if any([_ocr_find_text(t) is not None for t in claimed_texts]):
                return
            pos = None
            for t in claim_texts:
                pos = _ocr_find_text(t)
                if pos is not None:
                    break
            if pos is None:
                return
            logging.info(istr({
                CN: f"检测到签到领取时长按钮，点击 {pos}",
                EN: f"Check-in duration claim button detected, click {pos}"
            }))
            click(pos, sleeptime=4)
            # 点击后可能出现确认弹窗（如"领取成功"），尝试点掉常见确认按钮
            for confirm_text in ["确定", "知道了", "确认"]:
                confirm_pos = _ocr_find_text(confirm_text)
                if confirm_pos is not None:
                    logging.info(istr({
                        CN: f"点击确认按钮 {confirm_text}",
                        EN: f"Click confirm button {confirm_text}"
                    }))
                    click(confirm_pos, sleeptime=2)
                    break
            sleep(2)
            # 按钮若仍在（如点击未生效），下一轮重试；最多3轮
    except Exception as e:
        logging.warn(istr({
            CN: f"签到领取时长检查出错（不影响后续流程）: {e}",
            EN: f"Error checking daily duration claim (does not affect the following flow): {e}"
        }))


def _recover_once(game_name) -> bool:
    """
    根据当前界面状态路由，尝试一轮进入云游戏：

    - 已在云游戏: 直接成功
    - 游戏详情页且页面有游戏名: 直达"开始游戏"（闪退通常退回详情页，此时完整流程会因
      OCR找不到列表里的游戏名而失败，必须直达）
    - 其他界面(首页/未知/无前台): 打开平台 → 找游戏 → 点开始游戏

    返回云游戏是否已建立
    """
    screenshot()
    if is_cloud_streaming():
        return True
    foreground = _get_foreground_activity()
    if "GameDetailActivity" in foreground and _ocr_find_text(game_name) is not None:
        logging.info(istr({
            CN: "当前在游戏详情页，直达开始游戏",
            EN: "Now on the game detail page, click start game directly"
        }))
        if not _click_start_game():
            return False
    else:
        if not _open_cloud_platform():
            return False
        # 每日福利：OCR检查"签到并领取时长"按钮，有则点击领取
        _claim_daily_duration()
        if not _find_and_click_game(game_name):
            return False
        if not _click_start_game():
            return False
    return _wait_stream_ready()


def recover_cloud_game() -> float:
    """
    云游戏中断后的自动恢复入口（登录循环/返回主页/任务运行中检测到中断时调用）

    单轮内最多重试 CLOUD_RECOVERY_MAX_TIMES 次（每次根据当前界面状态路由），
    全部失败后降级：
    - 首次降级：抛 EmulatorBlockError，主循环会重启模拟器并保留 CLOUD_RESTARTED_FLAG
    - 重启后再失败：抛 CloudStreamInterruptError，主循环不关模拟器、走断点续跑

    返回恢复耗时（秒）；云游戏本来就正常时返回 0.0
    """
    start_time = time.time()
    if is_cloud_streaming():
        return 0.0
    max_times = int(config.userconfigdict.get("CLOUD_RECOVERY_MAX_TIMES", 3))
    game_name = config.userconfigdict["CLOUD_GAME_NAME"]
    logging.warn(istr({
        CN: "检测到云游戏中断，开始自动恢复",
        EN: "Cloud game interruption detected, start auto recovery"
    }))
    for attempt in range(1, max_times + 1):
        logging.info(istr({
            CN: f"云游戏恢复尝试 {attempt}/{max_times}",
            EN: f"Cloud game recovery attempt {attempt}/{max_times}"
        }))
        try:
            if _recover_once(game_name):
                elapsed = time.time() - start_time
                logging.info(istr({
                    CN: f"云游戏恢复成功，耗时 {elapsed:.0f} 秒",
                    EN: f"Cloud game recovered in {elapsed:.0f} seconds"
                }))
                return elapsed
        except Exception as e:
            logging.warn(istr({
                CN: f"云游戏恢复过程出错: {e}",
                EN: f"Error during cloud game recovery: {e}"
            }))
        sleep(3)
    # 降级链：先重启模拟器一次；重启后仍失败则抛云游戏中断异常
    if not config.sessiondict.get("CLOUD_RESTARTED_FLAG", False):
        config.sessiondict["CLOUD_RESTARTED_FLAG"] = True
        raise EmulatorBlockError(istr({
            CN: f"云游戏连续{max_times}次恢复失败，重启模拟器后重试",
            EN: f"Cloud game recovery failed {max_times} times, restart the emulator and retry"
        }))
    raise CloudStreamInterruptError(istr({
        CN: "重启模拟器后云游戏恢复仍失败，任务中断",
        EN: "Cloud game recovery still failed after emulator restart, tasks interrupted"
    }))


def launch_cloud_game() -> bool:
    """
    云游戏模式下，打开云平台并启动云游戏，直到云游戏建立

    前置条件：ACTIVITY_PATH 已被config解析为云平台入口
    返回是否成功，失败抛出异常
    """
    if is_cloud_streaming():
        logging.info(istr({
            CN: "云游戏已在运行，跳过启动",
            EN: "Cloud game is already running, skip launching"
        }))
        return True
    game_name = config.userconfigdict["CLOUD_GAME_NAME"]
    if not _recover_once(game_name):
        raise Exception(istr({
            CN: "未能建立云游戏，请检查上方日志（云平台打开失败/未找到游戏/开始游戏失败/建立超时）。若提示未找到游戏，请确认已在云平台里手动启动过一次该游戏",
            EN: "Failed to establish the cloud game, check logs above (platform open failed / game not found / start failed / timeout). If game not found, please make sure you have manually launched it once in the platform"
        }))
    logging.info(istr({
        CN: "云游戏就绪",
        EN: "Cloud game is ready"
    }))
    return True
