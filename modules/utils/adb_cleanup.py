"""
ADB 应用清理工具：结束模拟器里所有已打开的用户应用并回到桌面

独立于 adb_utils 的原因：adb_utils 是上游高频修改的热点文件，
云游戏相关功能集中放在自有文件中，避免上游同步时产生冲突。
本模块不导出进 modules.utils 的通配命名空间，调用方显式 import。
"""
import re

from modules.utils import config, logging, subprocess_run
from modules.utils.adb_utils import get_now_running_app, get_config_adb_path, getNewestSeialNumber


def _should_skip_when_kill_all(package_name: str) -> bool:
    """结束所有应用时应当跳过的系统关键包（桌面/系统UI/输入法等）"""
    name = package_name.lower()
    skip_keywords = ["launcher", "systemui", "inputmethod"]
    return any(keyword in name for keyword in skip_keywords)


def get_recent_task_packages(use_config=None):
    """
    获取最近任务列表中打开过的用户应用包名（含当前前台应用）

    通过解析 dumpsys activity recents 里每条 Intent 的 cmp=组件信息提取包名
    """
    target_config = config if not use_config else use_config
    packages = []
    # 当前前台应用
    now_app = get_now_running_app(target_config)
    if now_app and "/" in now_app:
        packages.append(now_app.split("/")[0])
    # 最近任务里的应用
    output = subprocess_run([get_config_adb_path(target_config), "-s", getNewestSeialNumber(target_config),
                             'shell', 'dumpsys', 'activity', 'recents']).stdout
    for line in output.splitlines():
        # 兼容 cmp=com.pkg/.Act 和 cmp=ComponentInfo{com.pkg/.Act} 两种格式
        match_res = re.search(r"cmp=(?:ComponentInfo\{)?([\w.]+)/", line)
        if match_res:
            package_name = match_res.group(1)
            if package_name not in packages:
                packages.append(package_name)
    return packages


def kill_all_apps(use_config=None):
    """
    结束模拟器里所有已打开的用户应用，并按Home键回到桌面

    跳过桌面/系统UI/输入法等系统关键应用
    """
    target_config = config if not use_config else use_config
    packages = get_recent_task_packages(target_config)
    logging.info({"zh_CN": f"检测到已打开的应用: {packages}",
                  "en_US": f"Detected opened apps: {packages}"})
    stopped_count = 0
    for package_name in packages:
        if _should_skip_when_kill_all(package_name):
            continue
        subprocess_run([get_config_adb_path(target_config), "-s", getNewestSeialNumber(target_config),
                        'shell', 'am', 'force-stop', package_name])
        stopped_count += 1
        logging.info({"zh_CN": f"已结束应用: {package_name}",
                      "en_US": f"Killed app: {package_name}"})
    # 按Home键确保回到桌面
    subprocess_run([get_config_adb_path(target_config), "-s", getNewestSeialNumber(target_config),
                    'shell', 'input', 'keyevent', '3'])
    logging.info({"zh_CN": f"已结束 {stopped_count} 个应用并回到桌面",
                  "en_US": f"Killed {stopped_count} apps and returned to home screen"})
