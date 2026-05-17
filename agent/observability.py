"""结构化日志：便于把 stderr 反馈与主循环事件对齐到同一套 logger。"""

from __future__ import annotations

import logging
import sys
from typing import Final

_LOG: Final = "agent.production"

#verbose=False（默认）生产环境，verbose=True调试开发
def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    root = logging.getLogger(_LOG)
    root.setLevel(level)
    if root.handlers:
        return
    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)s [%(name)s] %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root.addHandler(h)

#￥获取 Logger，层级结构便于按模块过滤
def get_logger(name: str | None = None) -> logging.Logger:
    return logging.getLogger(f"{_LOG}.{name}" if name else _LOG)
