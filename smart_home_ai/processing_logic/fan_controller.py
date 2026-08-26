"""Điều khiển quạt ba cấp bằng Fuzzy Logic và máy trạng thái."""

from __future__ import annotations
from typing import Optional
from smart_home_ai.config import FanConfig, FuzzyFanConfig

class ThreeSpeedFanController:
    """
    Bộ điều khiển quạt ba cấp.
    Kiến trúc xử lý:
        Temperature + People Count
                    ↓
              Fuzzification
                    ↓
              Fuzzy Rule Base
                    ↓
           Sugeno Defuzzification
                    ↓
              Fuzzy Score
                    ↓
          Output Hysteresis
                    ↓
             Desired Level
                    ↓
             State Machine
                    ↓
             Current Level
    Level:
        0 = OFF
        1 = LOW
        2 = MEDIUM
        3 = HIGH
    """
    # =========================================================
    # FUZZY RULE BASE
    # =========================================================
    #                      PEOPLE
    #                Few    Medium    Many

    # Cool           LOW     LOW      MEDIUM
    # Comfortable    LOW     MEDIUM   HIGH
    # Warm           MEDIUM  HIGH     HIGH
    # Hot            HIGH    HIGH     HIGH
    # =========================================================
    _FUZZY_RULES = (
        ("cool", "few", "low"),
        ("cool", "medium", "low"),
        ("cool", "many", "medium"),

        ("comfortable", "few", "low"),
        ("comfortable", "medium", "medium"),
        ("comfortable", "many", "high"),

        ("warm", "few", "medium"),
        ("warm", "medium", "high"),
        ("warm", "many", "high"),

        ("hot", "few", "high"),
        ("hot", "medium", "high"),
        ("hot", "many", "high"),
    )
    def __init__(
        self,
        config: Optional[FanConfig] = None,
        fuzzy_config: Optional[FuzzyFanConfig] = None,
    ) -> None:
        self.cfg = config or FanConfig()
        self.fuzzy = fuzzy_config or FuzzyFanConfig()
        # =====================================================
        # FAN STATE MACHINE
        # =====================================================
        # Cấp quạt hiện đang được controller yêu cầu ESP32 chạy.
        self.level = 0
        # Cấp quạt đang chờ được xác nhận sau hold time.
        self.pending_level: Optional[int] = None
        # Thời điểm bắt đầu trạng thái chờ.
        self.pending_since: Optional[float] = None
        # Thời điểm đổi cấp gần nhất.
        self.last_change = -float("inf")
        # =====================================================
        # CURRENT INPUT
        # =====================================================
        self.people = 0
        self.temperature_c = 0.0
        # =====================================================
        # FUZZY RESULT
        # =====================================================
        # Giá trị đầu ra liên tục của Fuzzy.
        # 1.0 ≈ LOW
        # 2.0 ≈ MEDIUM
        # 3.0 ≈ HIGH
        self.fuzzy_score = 0.0
        # Mức quạt mà Fuzzy + hysteresis đang yêu cầu.
        self.desired_level = 0
        # Membership dùng để debug / dashboard.
        self.temperature_memberships: dict[str, float] = {}
        self.people_memberships: dict[str, float] = {}
        # Độ kích hoạt của từng fuzzy rule.
        self.rule_strengths: dict[str, float] = {}
    # =========================================================
    # GENERIC MEMBERSHIP FUNCTIONS
    # =========================================================
    @staticmethod
    def _left_shoulder(
        x: float,
        full_until: float,
        zero_at: float,
    ) -> float:
        """
        Hàm thuộc dạng vai trái.
        x <= full_until: μ = 1
        full_until < x < zero_at:  μ giảm tuyến tính
        x >= zero_at: μ = 0
        """
        if x <= full_until:
            return 1.0
        if x >= zero_at:
            return 0.0
        return (zero_at - x) / (zero_at - full_until)
    @staticmethod
    def _right_shoulder(
        x: float,
        zero_until: float,
        full_from: float,
    ) -> float:
        """
        Hàm thuộc dạng vai phải.
        x <= zero_until: μ = 0
        zero_until < x < full_from: μ tăng tuyến tính
        x >= full_from: μ = 1
        """
        if x <= zero_until:
            return 0.0
        if x >= full_from:
            return 1.0
        return (x - zero_until) / (full_from - zero_until)
    @staticmethod
    def _triangle( # hàm thuộc tam giác
        x: float,
        left: float,
        peak: float,
        right: float,
    ) -> float:
        """
        Hàm thuộc tam giác.
                  μ
                  1
                  /\\
                 /  \\
                /    \\
        --------      --------
             left  peak  right
        """
        if x <= left or x >= right:
            return 0.0
        if x == peak:
            return 1.0
        if x < peak:
            return (x - left) / (peak - left)
        return (right - x) / (right - peak)
    # =========================================================
    # TEMPERATURE FUZZIFICATION
    # =========================================================
    def _fuzzify_temperature(
        self,
        temperature_c: float,
    ) -> dict[str, float]:
        """
        Chuyển nhiệt độ thực thành các mức thuộc:
            cool
            comfortable
            warm
            hot
        """
        f = self.fuzzy
        return {
            "cool": self._left_shoulder(
                temperature_c,
                f.temp_cool_full_until_c,
                f.temp_cool_zero_at_c,
            ),
            "comfortable": self._triangle(
                temperature_c,
                f.temp_comfortable_left_c,
                f.temp_comfortable_peak_c,
                f.temp_comfortable_right_c,
            ),
            "warm": self._triangle(
                temperature_c,
                f.temp_warm_left_c,
                f.temp_warm_peak_c,
                f.temp_warm_right_c,
            ),
            "hot": self._right_shoulder(
                temperature_c,
                f.temp_hot_zero_until_c,
                f.temp_hot_full_from_c,
            ),
        }
    # =========================================================
    # PEOPLE FUZZIFICATION
    # =========================================================
    def _fuzzify_people(
        self,
        people: int,
    ) -> dict[str, float]:
        """
        Chuyển số người thành các tập mờ:
            few
            medium
            many
        """
        f = self.fuzzy
        value = float(people)
        return {
            "few": self._left_shoulder(
                value,
                f.people_few_full_until,
                f.people_few_zero_at,
            ),
            "medium": self._triangle(
                value,
                f.people_medium_left,
                f.people_medium_peak,
                f.people_medium_right,
            ),
            "many": self._right_shoulder(
                value,
                f.people_many_zero_until,
                f.people_many_full_from,
            ),
        }
    # =========================================================
    # FUZZY OUTPUT
    # =========================================================
    def _output_value(
        self,
        label: str,
    ) -> float:
        """Chuyển nhãn output Sugeno thành giá trị singleton."""
        if label == "low":
            return self.fuzzy.low_output
        if label == "medium":
            return self.fuzzy.medium_output
        if label == "high":
            return self.fuzzy.high_output
        raise ValueError(
            f"Unknown fuzzy output label: {label}"
        )
    # =========================================================
    # FUZZY INFERENCE
    # =========================================================
    def _calculate_fuzzy_score(
        self,
        people: int,
        temperature_c: float,
    ) -> float:
        """
        Thực hiện Zero-order Sugeno Fuzzy Inference.
        Bước 1:
            Fuzzification Temperature.
        Bước 2:
            Fuzzification People.
        Bước 3:
            Tính firing strength từng rule.
            AND được thực hiện bằng:
                w_i = min(mu_temperature, mu_people)
        Bước 4:
            Defuzzification bằng weighted average:

                    Σ(w_i * z_i)
            score = ------------
                       Σ(w_i)
        Trong đó:
            w_i = firing strength
            z_i = LOW/MEDIUM/HIGH = 1/2/3
        """
        self.temperature_memberships = (
            self._fuzzify_temperature(
                temperature_c
            )
        )
        self.people_memberships = (
            self._fuzzify_people(
                people
            )
        )
        weighted_sum = 0.0
        total_strength = 0.0
        self.rule_strengths = {}
        for (
            temperature_label,
            people_label,
            output_label,
        ) in self._FUZZY_RULES:
            temperature_mu = (
                self.temperature_memberships[
                    temperature_label
                ]
            )
            people_mu = (
                self.people_memberships[
                    people_label
                ]
            )
            # Fuzzy AND.
            strength = min(
                temperature_mu,
                people_mu,
            )
            output_value = self._output_value(
                output_label
            )
            rule_name = (
                f"{temperature_label}"
                f" + {people_label}"
                f" -> {output_label}"
            )
            self.rule_strengths[
                rule_name
            ] = strength
            if strength <= 0.0:
                continue
            weighted_sum += (
                strength * output_value
            )
            total_strength += strength
        # Trường hợp phòng vệ.
        # Với membership được thiết kế đúng,
        # trường hợp này không nên xảy ra khi people > 0.
        if total_strength <= 0.0:
            return self.fuzzy.low_output
        
        return weighted_sum / total_strength
    # =========================================================
    # FUZZY SCORE -> FAN LEVEL
    # =========================================================
    def _base_level_from_score(
        self,
        score: float,
    ) -> int:
        """
        Lượng tử hóa fuzzy score thành 3 cấp quạt.
        """
        if score < self.fuzzy.level_1_to_2_boundary:
            return 1
        if score < self.fuzzy.level_2_to_3_boundary:
            return 2
        return 3
    # =========================================================
    # OUTPUT HYSTERESIS
    # =========================================================
    def _target_with_hysteresis(
        self,
        score: float,
    ) -> int:
        """
        Chống rung cấp quạt quanh ranh giới fuzzy score.
        Ví dụ biên Level 2/3 = 2.5
        hysteresis = 0.1
        Khi đang Level 2:
            phải >= 2.6 mới lên Level 3.
        Khi đang Level 3:
            phải < 2.4 mới xuống Level 2.
        """
        # Khi quạt đang OFF và có người:
        # chọn trực tiếp level từ fuzzy score.
        if self.level == 0:
            return self._base_level_from_score(score)
        h = self.fuzzy.level_hysteresis
        boundary_12 = (
            self.fuzzy.level_1_to_2_boundary
        )
        boundary_23 = (
            self.fuzzy.level_2_to_3_boundary
        )
        # -----------------------------
        # CURRENT LEVEL = 1
        # -----------------------------
        if self.level == 1:
            if score >= boundary_23 + h:
                return 3
            if score >= boundary_12 + h:
                return 2
            return 1
        # -----------------------------
        # CURRENT LEVEL = 2
        # -----------------------------
        if self.level == 2:
            if score >= boundary_23 + h:
                return 3
            if score < boundary_12 - h:
                return 1
            return 2
        # ----------------------------
        # CURRENT LEVEL = 3
        # -----------------------------
        if score < boundary_12 - h:
            return 1
        if score < boundary_23 - h:
            return 2
        return 3
    # =========================================================
    # DESIRED FAN LEVEL
    # =========================================================
    def _choose_desired_level(
        self,
        people: int,
        temperature_c: float,
    ) -> int:
        """
        Quyết định mức quạt mong muốn.
        Nếu phòng không có người:
            desired = OFF
        Nếu có người:
            Temperature + People
            -> Fuzzy Logic
            -> desired level
        """
        # Vẫn tính membership nhiệt độ để diagnostics
        # luôn phản ánh dữ liệu hiện tại.
        self.temperature_memberships = (
            self._fuzzify_temperature(
                temperature_c
            )
        )
        # =====================================================
        # EMPTY ROOM POLICY
        # =====================================================
        if people <= 0:
            self.fuzzy_score = 0.0
            self.people_memberships = {
                "few": 0.0,
                "medium": 0.0,
                "many": 0.0,
            }
            self.rule_strengths = {}
            return 0
        # =====================================================
        # FUZZY CONTROL
        # =====================================================
        self.fuzzy_score = (
            self._calculate_fuzzy_score(
                people,
                temperature_c,
            )
        )
        return self._target_with_hysteresis(
            self.fuzzy_score
        )
    # =========================================================
    # STATE MACHINE
    # =========================================================
    def _required_hold_time(
        self,
        people: int,
        desired: int,
    ) -> float:
        """
        Xác định thời gian yêu cầu desired level
        phải duy trì trước khi đổi cấp thật.
        """
        # Không có người:
        # chờ vacancy delay trước khi OFF.
        if people <= 0:
            return self.cfg.vacancy_off_delay_s
        # Tăng cấp.
        if desired > self.level:
            return self.cfg.increase_hold_s
        # Giảm cấp.
        return self.cfg.decrease_hold_s
    def _reset_pending_level(self) -> None:
        """Xóa trạng thái chuyển cấp đang chờ."""
        self.pending_level = None
        self.pending_since = None
    def _start_pending_level(
        self,
        desired: int,
        now: float,
    ) -> None:
        """Bắt đầu đếm thời gian cho một desired level mới."""
        self.pending_level = desired
        self.pending_since = now
    def _can_commit(
        self,
        required_hold: float,
        now: float,
    ) -> bool:
        """Kiểm tra có đủ điều kiện đổi cấp thật hay chưa."""
        if self.pending_since is None:
            return False
        hold_time_ok = (
            now - self.pending_since
            >= required_hold
        )
        min_interval_ok = (
            now - self.last_change
            >= self.cfg.min_switch_interval_s
        )
        return (
            hold_time_ok
            and min_interval_ok
        )
    def _commit_level(
        self,
        desired: int,
        now: float,
    ) -> None:
        """Chính thức thay đổi cấp quạt."""
        self.level = desired
        self.last_change = now
        self._reset_pending_level()

    # =========================================================
    # PUBLIC API
    # =========================================================
    def update(
        self,
        people: int,
        temperature_c: float,
        now: float,
    ) -> int:
        """
        Cập nhật bộ điều khiển.
        Parameters
        ----------
        people:
            Số người đã được StableOccupancyEstimator lọc ổn định.
        temperature_c:
            Nhiệt độ thực tế đọc từ DHT11.
        now:
            monotonic timestamp.
        Returns
        -------
        int:
            Cấp quạt đã được State Machine chấp nhận:
            0 = OFF
            1 = LOW
            2 = MEDIUM
            3 = HIGH

        Lưu ý:
            Đây KHÔNG phải fuzzy desired level tức thời.
            Fuzzy desired level có thể xem qua:
                self.desired_level
        """
        # Chuẩn hóa input.
        self.people = max(
            0,
            int(people),
        )
        self.temperature_c = float(
            temperature_c
        )
        # =====================================================
        # 1. FUZZY DECISION
        # =====================================================
        desired = self._choose_desired_level(
            self.people,
            self.temperature_c,
        )
        self.desired_level = desired
        # =====================================================
        # 2. TEMPORAL FILTER
        # =====================================================
        required_hold = (
            self._required_hold_time(
                self.people,
                desired,
            )
        )
        # =====================================================
        # 3. KHÔNG CẦN ĐỔI CẤP
        # =====================================================
        if desired == self.level:
            self._reset_pending_level()
            return self.level
        # =====================================================
        # 4. XUẤT HIỆN MỤC TIÊU MỚI
        # =====================================================
        if desired != self.pending_level:
            self._start_pending_level(
                desired,
                now,
            )
            return self.level
        # =====================================================
        # 5. MỤC TIÊU VẪN ỔN ĐỊNH
        # =====================================================
        if self._can_commit(
            required_hold,
            now,
        ):
            self._commit_level(
                desired,
                now,
            )
        return self.level
    # =========================================================
    # DIAGNOSTICS
    # =========================================================
    def diagnostics(self) -> dict:
        """
        Trả thông tin chi tiết về quá trình suy luận.
        Sau này có thể publish qua MQTT để Node-RED hiển thị.
        """
        return {
            "control_mode": "FUZZY_AUTO",
            "temperature_c": round(
                self.temperature_c,
                2,
            ),
            "people": self.people,
            "fuzzy_score": round(
                self.fuzzy_score,
                3,
            ),
            # Fuzzy muốn quạt ở mức nào.
            "desired_level": self.desired_level,
            # State Machine đã cho phép chạy mức nào.
            "fan_level": self.level,
            # Nếu đang chờ đổi cấp.
            "pending_level": self.pending_level,
            "temperature_memberships": {
                name: round(value, 3)
                for name, value
                in self.temperature_memberships.items()
            },
            "people_memberships": {
                name: round(value, 3)
                for name, value
                in self.people_memberships.items()
            },
            "active_rules": {
                name: round(value, 3)
                for name, value
                in self.rule_strengths.items()
                if value > 0.0
            },
        }