"""
状态机模块
显式管理Agent运行状态，防止隐式Bug
"""

from enum import Enum, auto
from typing import Callable, Dict, List


class AgentState(Enum):
    """Agent状态枚举"""
    IDLE = auto()          # 空闲
    THINKING = auto()      # 思考中
    ACTING = auto()        # 执行工具中
    OBSERVING = auto()     # 等待观察结果
    FINISHED = auto()      # 任务完成
    ERROR = auto()         # 出错
    PAUSED = auto()        # 暂停


class StateMachine:
    """
    状态机
    
    定义合法状态转换，拒绝非法跳转
    """

    # 合法转换规则
    TRANSITIONS = {
        AgentState.IDLE: [AgentState.THINKING, AgentState.PAUSED],
        AgentState.THINKING: [AgentState.ACTING, AgentState.FINISHED, AgentState.ERROR],
        AgentState.ACTING: [AgentState.OBSERVING, AgentState.ERROR],
        AgentState.OBSERVING: [AgentState.THINKING, AgentState.ERROR],
        AgentState.FINISHED: [AgentState.IDLE],
        AgentState.ERROR: [AgentState.IDLE, AgentState.THINKING],
        AgentState.PAUSED: [AgentState.IDLE, AgentState.THINKING],
    }

    def __init__(self, initial: AgentState = AgentState.IDLE):
        self.state = initial
        self.history: List[AgentState] = [initial]
        self.callbacks: Dict[AgentState, List[Callable]] = {
            s: [] for s in AgentState
        }

    def transition(self, new_state: AgentState) -> bool:
        """
        尝试状态转换
        
        Returns:
            转换成功返回True，非法转换返回False
        """
        if new_state not in self.TRANSITIONS.get(self.state, []):
            print(f"⚠️ 非法状态转换: {self.state.name} -> {new_state.name}")
            return False

        self.state = new_state
        self.history.append(new_state)

        # 触发回调
        for cb in self.callbacks.get(new_state, []):
            cb(new_state)

        return True

    def on(self, state: AgentState, callback: Callable):
        """注册状态进入回调"""
        self.callbacks[state].append(callback)

    def is_(self, state: AgentState) -> bool:
        """判断是否处于某状态"""
        return self.state == state

    def can(self, state: AgentState) -> bool:
        """判断能否转换到某状态"""
        return state in self.TRANSITIONS.get(self.state, [])

    def __str__(self) -> str:
        return f"State({self.state.name})"
