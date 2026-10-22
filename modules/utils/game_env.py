"""
游戏环境就绪判断与恢复的统一入口（本地游戏 / 云游戏的差异在此收敛）

游戏侧模块（Loginin / Task.back_to_home / InEvent 等）只依赖本模块的中性接口，
不需要知道当前运行在本地模式还是云游戏模式：
- is_game_ready():     游戏环境是否就绪（本地=游戏在前台；云=云游戏串流运行中）
- ensure_game_ready(): 环境未就绪时自动恢复（本地=重新打开游戏；云=重进云游戏），返回耗时秒
- is_cloud_mode():     运行环境类型查询（供个别需要区分云/本地的业务规则使用，如云模式不支持包体更新）
- is_cloud_streaming():云游戏是否处于串流运行状态

注意：本模块不导出进 modules.utils 的通配命名空间，调用方显式 import。
原定义在 adb_utils 中的两个云函数已迁入本文件——adb_utils 是上游高频修改的热点文件，
云游戏功能集中放在自有文件，避免上游同步冲突。
"""
from modules.utils import config, sleep, logging
from modules.utils.adb_utils import check_app_running, open_app


def is_cloud_mode(use_config=None) -> bool:
    """
    判断当前配置是否使用云游戏平台运行游戏（RUN_PLATFORM 为 CLOUD_ 开头）
    """
    target_config = config if not use_config else use_config
    return str(target_config.userconfigdict.get("RUN_PLATFORM", "LOCAL")).upper().startswith("CLOUD_")


def is_cloud_streaming(use_config=None) -> bool:
    """
    判断云游戏是否已处于串流运行状态（前台为云平台的串流Activity）

    云游戏模式下，游戏画面运行在云端，前台包名始终是云平台自己的包名，
    因此"游戏是否打开"需判断前台activity是否为平台的串流页
    """
    if not is_cloud_mode(use_config):
        return False
    target_config = config if not use_config else use_config
    # 延迟导入避免循环依赖
    from modules.configs.settingMaps import cloud2stream_activity
    stream_activity = cloud2stream_activity.get(target_config.userconfigdict["RUN_PLATFORM"], "")
    if not stream_activity:
        # 平台没有配置串流页特征，退化为判断云平台是否在前台
        return check_app_running(target_config.userconfigdict["CLOUD_PLATFORM_ENTRY"], printit=False)
    # 延迟导入避免循环依赖
    from modules.utils.adb_utils import get_now_running_app
    now_app = get_now_running_app(target_config)
    return stream_activity in now_app


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
