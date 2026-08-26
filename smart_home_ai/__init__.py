"""Smart Home AI package: people tracking, stable occupancy and fan control."""

from .config import FanConfig, OccupancyConfig
from .processing_logic.fan_controller import ThreeSpeedFanController
from .vision.occupancy import StableOccupancyEstimator

__all__ = [
    "FanConfig",
    "OccupancyConfig",
    "StableOccupancyEstimator",
    "ThreeSpeedFanController",
]
