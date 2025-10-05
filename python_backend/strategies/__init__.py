"""Strategies module"""
from .base import BaseStrategy, Signal, Trade
from .sma_crossover import SMACrossoverStrategy
from .rsi_mean_revert import RSIMeanReversionStrategy
from .macd_trend_follow import MACDTrendFollowStrategy

# Strategy registry
STRATEGIES = {
    'sma_crossover': SMACrossoverStrategy,
    'rsi_mean_revert': RSIMeanReversionStrategy,
    'macd_trend_follow': MACDTrendFollowStrategy,
}


def get_strategy(strategy_id: str, parameters: dict = None) -> BaseStrategy:
    """
    Get strategy instance by ID
    
    Args:
        strategy_id: Strategy identifier
        parameters: Strategy parameters
    
    Returns:
        Strategy instance
    
    Raises:
        ValueError: If strategy not found
    """
    strategy_class = STRATEGIES.get(strategy_id)
    if not strategy_class:
        raise ValueError(f"Strategy '{strategy_id}' not found")
    
    return strategy_class(parameters or {})


def list_strategies() -> list:
    """
    List all available strategies
    
    Returns:
        List of strategy information dictionaries
    """
    strategies = []
    for strategy_id, strategy_class in STRATEGIES.items():
        instance = strategy_class()
        strategies.append({
            'id': strategy_id,
            'name': instance.name,
            'description': instance.description,
            'parameters': instance.parameters,
        })
    return strategies


__all__ = [
    'BaseStrategy',
    'Signal',
    'Trade',
    'SMACrossoverStrategy',
    'RSIMeanReversionStrategy',
    'MACDTrendFollowStrategy',
    'get_strategy',
    'list_strategies',
    'STRATEGIES',
]
