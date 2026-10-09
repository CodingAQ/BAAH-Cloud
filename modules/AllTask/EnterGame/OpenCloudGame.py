"""
云游戏平台支持：打开云平台APP并启动云游戏，等待串流建立

流程基于集游社(com.jys)实测：
1. 打开云平台（竖屏首页）
2. OCR查找游戏名称，点击游戏入口（"玩过的游戏"列表里的图标在名称上方）
3. 在游戏详情页OCR查找并点击"开始游戏"
4. 等待前台切换为云平台串流Activity（实测约30-40s），并等待屏幕转为横屏
"""
import time

from modules.utils import (click, swipe, screenshot, config, ocr_area,
                           get_screenshot_cv_data, logging, istr, CN, EN,
                           OCR_LANG, sleep)
from modules.utils.adb_utils import (open_app, check_app_running,
                                     get_now_running_app, is_cloud_mode,
                                     is_cloud_streaming)


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
        # 可能点击后直接开始串流了
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
    return False


def _click_start_game() -> bool:
    """在游戏详情页OCR查找并点击"开始游戏"按钮，返回是否成功"""
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
            # 有些游戏点击入口后直接开始串流，没有详情页
            logging.info(istr({
                CN: f"未找到开始游戏按钮，等待页面变化 {i+1}/10",
                EN: f"Start game button not found, wait for page change {i+1}/10"
            }))
        sleep(3)
    return False


def _wait_stream_ready() -> bool:
    """
    等待云游戏串流建立（前台变为云平台串流Activity）并转为横屏

    返回是否成功
    """
    timeout = float(config.userconfigdict["CLOUD_STREAM_TIMEOUT"])
    start_time = time.time()
    logging.info(istr({
        CN: f"等待云游戏串流建立，超时时间 {timeout} 秒",
        EN: f"Waiting for cloud game stream, timeout {timeout} seconds"
    }))
    while time.time() - start_time < timeout:
        screenshot()
        if is_cloud_streaming():
            logging.info(istr({
                CN: "云游戏串流已建立，等待画面转为横屏",
                EN: "Cloud game stream established, waiting for landscape"
            }))
            # 等待串流画面转为横屏（云平台的串流页会自动旋转）
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
    return False


def launch_cloud_game() -> bool:
    """
    云游戏模式下，打开云平台并启动云游戏，直到串流建立

    前置条件：ACTIVITY_PATH 已被config解析为云平台入口
    返回是否成功，失败抛出异常
    """
    game_name = config.userconfigdict["CLOUD_GAME_NAME"]
    if is_cloud_streaming():
        logging.info(istr({
            CN: "云游戏已在串流中，跳过启动",
            EN: "Cloud game is already streaming, skip launching"
        }))
        return True
    # 1. 打开云平台
    if not _open_cloud_platform():
        raise Exception(istr({
            CN: "云平台打开失败，请检查 CLOUD_PLATFORM_ENTRY 配置 以及 模拟器内是否安装了云平台APP",
            EN: "Failed to open cloud platform, please check CLOUD_PLATFORM_ENTRY and whether the platform app is installed"
        }))
    # 2. 查找并点击游戏入口
    if not _find_and_click_game(game_name):
        raise Exception(istr({
            CN: f"未能在云平台界面找到游戏：{game_name}，请确认已在云平台里手动启动过一次该游戏（出现在玩过的游戏列表中）",
            EN: f"Cannot find game {game_name} in the cloud platform, please make sure you have manually launched it once (appears in the history list)"
        }))
    # 3. 点击开始游戏
    if not _click_start_game():
        raise Exception(istr({
            CN: "未能开始云游戏（未找到开始游戏按钮或串流超时）",
            EN: "Failed to start cloud game (start button not found or stream timeout)"
        }))
    # 4. 等待串流建立
    if not _wait_stream_ready():
        raise Exception(istr({
            CN: f"等待云游戏串流超时({config.userconfigdict['CLOUD_STREAM_TIMEOUT']}秒)",
            EN: f"Timeout waiting for cloud game stream ({config.userconfigdict['CLOUD_STREAM_TIMEOUT']} seconds)"
        }))
    logging.info(istr({
        CN: "云游戏串流就绪",
        EN: "Cloud game stream is ready"
    }))
    return True
