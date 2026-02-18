"""日志配置模块"""
import logging
import sys
from datetime import datetime
from pathlib import Path
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


# 日志格式
CONSOLE_FORMAT = "%(asctime)s │ %(levelname)-7s │ %(name)-12s │ %(message)s"
FILE_FORMAT = "%(asctime)s │ %(levelname)-7s │ %(name)-15s │ %(filename)s:%(lineno)d │ %(message)s"
DATE_FORMAT = "%H:%M:%S"
FILE_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ColoredFormatter(logging.Formatter):
    """带颜色的控制台日志格式化器"""

    # ANSI 颜色代码
    COLORS = {
        "DEBUG": "\033[36m",     # 青色
        "INFO": "\033[32m",      # 绿色
        "WARNING": "\033[33m",   # 黄色
        "ERROR": "\033[31m",     # 红色
        "CRITICAL": "\033[35m",  # 紫色
    }
    RESET = "\033[0m"

    def format(self, record):
        # 添加颜色
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"
        return super().format(record)


def setup_logging(
    level: str = "INFO",
    log_dir: str = "logs",
    log_to_file: bool = True,
    log_to_console: bool = True,
    max_file_size: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> logging.Logger:
    """
    配置日志系统

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: 日志文件目录
        log_to_file: 是否输出到文件
        log_to_console: 是否输出到控制台
        max_file_size: 单个日志文件最大大小
        backup_count: 保留的日志文件数量

    Returns:
        根日志记录器
    """
    # 获取根日志记录器
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # 清除已有的处理器
    root_logger.handlers.clear()

    # 控制台处理器
    if log_to_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.DEBUG)

        # Windows 下检测是否支持颜色
        if sys.platform == "win32":
            try:
                import os
                os.system("")  # 启用 ANSI 转义序列
                console_handler.setFormatter(ColoredFormatter(CONSOLE_FORMAT, DATE_FORMAT))
            except Exception:
                console_handler.setFormatter(logging.Formatter(CONSOLE_FORMAT, DATE_FORMAT))
        else:
            console_handler.setFormatter(ColoredFormatter(CONSOLE_FORMAT, DATE_FORMAT))

        root_logger.addHandler(console_handler)

    # 文件处理器
    if log_to_file:
        log_path = Path(log_dir)
        log_path.mkdir(parents=True, exist_ok=True)

        # 主日志文件（按大小轮转）
        main_log_file = log_path / "news_funnel.log"
        file_handler = RotatingFileHandler(
            main_log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(FILE_FORMAT, FILE_DATE_FORMAT))
        root_logger.addHandler(file_handler)

        # 错误日志文件（单独记录 ERROR 及以上）
        error_log_file = log_path / "error.log"
        error_handler = RotatingFileHandler(
            error_log_file,
            maxBytes=max_file_size,
            backupCount=backup_count,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(logging.Formatter(FILE_FORMAT, FILE_DATE_FORMAT))
        root_logger.addHandler(error_handler)

    # 设置第三方库的日志级别（减少噪音）
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("openai").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy").setLevel(logging.WARNING)
    logging.getLogger("aiosqlite").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的日志记录器

    Args:
        name: 日志记录器名称（通常使用模块名）

    Returns:
        日志记录器
    """
    return logging.getLogger(name)


# 便捷函数：获取各模块的日志记录器
def get_main_logger() -> logging.Logger:
    return get_logger("main")


def get_fetcher_logger() -> logging.Logger:
    return get_logger("fetcher")


def get_processor_logger() -> logging.Logger:
    return get_logger("processor")


def get_notifier_logger() -> logging.Logger:
    return get_logger("notifier")


def get_database_logger() -> logging.Logger:
    return get_logger("database")
