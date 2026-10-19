"""服务层：承载业务规则与状态流转，上接路由、下接仓储。"""

from services.trace_recorder import TraceRecorder

__all__ = ["TraceRecorder"]
