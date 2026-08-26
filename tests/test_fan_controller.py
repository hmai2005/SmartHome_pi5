import unittest

from smart_home_ai.config import FanConfig
from smart_home_ai.processing_logic.fan_controller import ThreeSpeedFanController


class FanControllerTests(unittest.TestCase):
    def test_fan_increases_after_hold_time(self) -> None:
        cfg = FanConfig(increase_hold_s=0.5, min_switch_interval_s=0.0)
        fan = ThreeSpeedFanController(cfg)

        self.assertEqual(fan.update(1, 29.0, 0.0), 0)
        self.assertEqual(fan.update(1, 29.0, 0.4), 0)
        self.assertEqual(fan.update(1, 29.0, 0.6), 2)

    def test_vacancy_turns_fan_off_after_delay(self) -> None:
        cfg = FanConfig(
            increase_hold_s=0.0,  # Tăng cấp ngay lập tức
            vacancy_off_delay_s=1.0,  # Chờ 1.0s sau khi trống phòng mới tắt quạt
            min_switch_interval_s=0.0,
        )
        fan = ThreeSpeedFanController(cfg)
        fan.update(1, 29.0, 0.0)
        fan.update(1, 29.0, 0.1)
        self.assertEqual(fan.level, 2)

        self.assertEqual(fan.update(0, 29.0, 0.2), 2)
        self.assertEqual(fan.update(0, 29.0, 1.3), 0)


if __name__ == "__main__":
    unittest.main()
