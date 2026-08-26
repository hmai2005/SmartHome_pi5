import unittest

from smart_home_ai.config import OccupancyConfig
from smart_home_ai.models import TrackedPerson
from smart_home_ai.vision.occupancy import StableOccupancyEstimator


def person(track_id: int, confidence: float = 0.9) -> TrackedPerson:
    return TrackedPerson(
        track_id=track_id,
        confidence=confidence,
        bbox_xyxy=(10.0, 10.0, 50.0, 100.0),
        center_point=(30.0, 55.0),
    )


class OccupancyTests(unittest.TestCase):
    def test_track_requires_confirmation_and_rise_debounce(self) -> None:
    #kiểm tra quy trình xác nhận và khử rung khi person tăng
        cfg = OccupancyConfig(
            confirm_hits=2, # Cần ít nhất 2 lần hit để xác nhận track
            confirm_window_s=1.0,  # Cửa sổ thời gian xác nhận là 1 giây
            rise_hold_s=0.1, # Cần giữ nguyên số lượng mới trong 0.1s mới cập nhật
        )
        estimator = StableOccupancyEstimator(cfg)
        shape = (720, 1280)

        self.assertEqual(estimator.update([person(1)], 0.0, shape), 0)
        self.assertEqual(estimator.update([person(1)], 0.05, shape), 0)
        self.assertEqual(estimator.update([person(1)], 0.20, shape), 1)

    def test_missing_detection_is_kept_during_grace_period(self) -> None:
    #chống đếm hụt người khi bị che khuất
        cfg = OccupancyConfig(
            confirm_hits=1, # Chỉ cần 1 hit là xác nhận ngay
            rise_hold_s=0.0, # Cập nhật tăng ngay lập tức (không chờ debounce)
            missing_grace_s=0.8, # Giữ lại track trong 0.8s khi bị mất detection
        )
        estimator = StableOccupancyEstimator(cfg)
        shape = (720, 1280)

        estimator.update([person(1)], 0.0, shape)
        estimator.update([person(1)], 0.01, shape)
        self.assertEqual(estimator.update([], 0.5, shape), 1)


if __name__ == "__main__":
    unittest.main()
