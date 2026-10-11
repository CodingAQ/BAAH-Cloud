"""
游戏环境就绪判断与恢复的统一入口（本地游戏 / 云游戏的差异在此收敛）

游戏侧模块（Loginin / Task.back_to_home / InEvent 等）只依赖本模块的中性接口，
不需要知道当前运行在本地模式还是云游戏模式：
- is_game_ready():     游戏环境是否就绪（本地=游戏在前台；云=云游戏串流运行中）
- ensure_game_ready(): 环境未就绪时自动恢复（本地=重新打开游戏；云=重进云游戏），返回耗时秒
- is_cloud_mode():     运行环境类型查询（转发，供个别需要区分云/本地的业务规则使用，如云模式不支持包体更新）

注意：本模块不导出进 modules.utils 的通配命名空间，调用方显式 import。
"""
from modules.utils import config, sleep, logging
from modules.utils.adb_utils import (check_app_running, open_app, is_cloud_mode,
                                     is_cloud_streaming)


def is_game_ready() -> bool:
    """
    游戏环境是否就绪

    - 本地模式：游戏进程在前台
    - 云游戏模式：前台为云平台的云游戏页（串流运行中）
    """
    if is_cloud_mode():
        return is_cloud_streaming()
    return check_app_running(config.userconfigdict["ACTIVITY_PATH"])


def ensure_game_ready() -> float:
    """
    确保游戏环境就绪，未就绪时自动恢复：

    - 本地模式：游戏不在前台则重新打开（约2秒）
    - 云游戏模式：云游戏中断则重进（详情页直达或完整流程，恢复失败降级链见 OpenCloudGame）

    返回恢复/打开耗时（秒）；本来就就绪时返回 0.0
    """
    if is_game_ready():
        return 0.0
    if not is_cloud_mode():
        open_app(config.userconfigdict["ACTIVITY_PATH"])
        logging.warn({"zh_CN": "游戏未在前台，尝试打开游戏",
                      "en_US": "The game is not in the foreground, try to open the game"})
        sleep(2)
        return 2.0
    # 延迟导入避免循环依赖（OpenCloudGame -> adb_utils -> ...）
    from modules.AllTask.EnterGame.OpenCloudGame import recover_cloud_game
    return recover_cloud_game()
