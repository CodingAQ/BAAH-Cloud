class EmulatorBlockError(Exception):
    """
    模拟器卡顿错误，通常发生在游戏启动阶段
    """
    def __init__(self, ErrorInfo):
        super().__init__(self)
        self.errorinfo = ErrorInfo

    def __str__(self):
        return self.errorinfo


class CloudStreamInterruptError(Exception):
    """
    云游戏中断且恢复失败的错误（已包含一次模拟器重启重试）。

    与 EmulatorBlockError 的区别：云游戏中断通常是云平台侧/网络问题，
    重启模拟器大概率无效，因此主循环捕获本异常后不应关闭模拟器，
    而应走断点续跑（RETRY_WHEN_ERROR）流程。
    """
    def __init__(self, ErrorInfo):
        super().__init__(self)
        self.errorinfo = ErrorInfo

    def __str__(self):
        return self.errorinfo