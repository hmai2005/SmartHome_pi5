"""Bộ lọc số người ổn định dựa trên track ID theo thời gian."""

from __future__ import annotations

import math
from typing import Dict, Iterable, Optional, Sequence, Tuple

from ..config import OccupancyConfig
from ..models import FrameShape, TrackState, TrackedPerson


class StableOccupancyEstimator:
    """Xác nhận track, chống mất detection ngắn và debounce số người."""

    def __init__(self, config: Optional[OccupancyConfig] = None) -> None:
        self.cfg = config or OccupancyConfig()
        self.tracks: Dict[int, TrackState] = {}
        self.stable_count = 0
        self.pending_count: Optional[int] = None
        self.pending_since: Optional[float] = None
        self.last_candidate_count = 0

    #tính khoảng cách tối đa 8%
    def _calculate_relink_distance(self, frame_shape: FrameShape) -> float:
        height, width = frame_shape
        return self.cfg.relink_distance_ratio * math.hypot(width, height)

    #tìm tập hợp các track_id cũ có thể tái sử dụng 
    #và khởi tạo tập hợp rỗng reusable_ids
    def _get_reusable_old_ids(
        self,
        detected_ids: set[int],
        now: float,
    ) -> set[int]:
        reusable_ids: set[int] = set()

        for track_id, state in self.tracks.items():
            age = now - state.last_seen #tính thời gian từ lần cuối thấy track
            if (
                track_id not in detected_ids
                and state.confirmed
                and 0.0 <= age <= self.cfg.relink_max_age_s
            ):
                reusable_ids.add(track_id)

        return reusable_ids #trả về danh sách ID cũ hợp lệ

    #tìm track cũ gần nhất so với vị trí hiện tại của person mới
    def _find_nearest_old_track(
        self,
        person: TrackedPerson,
        reusable_old_ids: Iterable[int],
    ) -> Tuple[Optional[int], float]:
        best_old_id: Optional[int] = None
        best_distance = float("inf")

        for old_id in reusable_old_ids:
            distance = math.dist(
                person.center_point,
                self.tracks[old_id].last_point,
            )
            if distance < best_distance:
                best_old_id = old_id
                best_distance = distance

        return best_old_id, best_distance #cập nhật ID cũ và khoảng cách ngắn hơn

    #ghép nối các ID mới xuất hiện với các ID cũ bị mất tạm thời
    def _relink_new_ids(
        self,
        persons: Sequence[TrackedPerson],
        now: float,
        frame_shape: FrameShape,
    ) -> None:
        detected_ids = {person.track_id for person in persons}
        new_persons = [
            person for person in persons if person.track_id not in self.tracks
        ]
        if not new_persons:
            return

        max_distance = self._calculate_relink_distance(frame_shape)
        reusable_old_ids = self._get_reusable_old_ids(detected_ids, now)

        for person in new_persons:
            old_id, distance = self._find_nearest_old_track(
                person,
                reusable_old_ids,
            )
            if old_id is None or distance > max_distance:
                continue

            self.tracks[person.track_id] = self.tracks.pop(old_id)
            reusable_old_ids.remove(old_id)

    @staticmethod #tạo một đối tượng trackState ghi lại thời gian thấy lần đầu, lần cuối và ví trí center
    def _create_track_state(person: TrackedPerson, now: float) -> TrackState:
        return TrackState(
            first_seen=now,
            last_seen=now,
            last_point=person.center_point,
        )

    def _get_or_create_track_state(
        self,
        person: TrackedPerson,
        now: float,
    ) -> TrackState:
        state = self.tracks.get(person.track_id)
        if state is None:
            state = self._create_track_state(person, now)
            self.tracks[person.track_id] = state
        return state

    #Loại bỏ các mốc thời gian detect có độ tin cậy cao (strong hit) 
    # đã nằm ngoài cửa sổ thời gian xác nhận
    def _remove_expired_hits(self, state: TrackState, now: float) -> None:
        cutoff = now - self.cfg.confirm_window_s
        while state.strong_hit_times and state.strong_hit_times[0] < cutoff:
            state.strong_hit_times.popleft()

    def _update_single_track(self, person: TrackedPerson, now: float) -> None:
        state = self._get_or_create_track_state(person, now)
        state.last_seen = now
        state.last_point = person.center_point

        self._remove_expired_hits(state, now)
        if person.confidence >= self.cfg.confirm_confidence:
            state.strong_hit_times.append(now)

        if (
            not state.confirmed
            and len(state.strong_hit_times) >= self.cfg.confirm_hits
        ):
            state.confirmed = True

    # Tìm tất cả các track không còn xuất hiện quá lâu (thời gian vắng mặt lớn hơn TTL stale_track_ttl_s)
    # và xóa hoàn toàn khỏi bộ nhớ self.tracks.
    def _remove_stale_tracks(self, now: float) -> None:
        stale_ids = [
            track_id
            for track_id, state in self.tracks.items()
            if now - state.last_seen > self.cfg.stale_track_ttl_s
        ]
        for track_id in stale_ids:
            del self.tracks[track_id]

    #Đếm tổng số lượng track thỏa mãn 2 điều kiện
    def _count_active_confirmed_tracks(self, now: float) -> int:
        return sum(
            1
            for state in self.tracks.values()
            if state.confirmed
            and now - state.last_seen <= self.cfg.missing_grace_s
        )

    #hủy trạng thái chờ
    def _reset_pending_count(self) -> None:
        self.pending_count = None
        self.pending_since = None

    def _start_pending_count(self, count: int, now: float) -> None:
        self.pending_count = count
        self.pending_since = now

    def _candidate_is_ready(self, candidate_count: int, now: float) -> bool:
        if self.pending_since is None:
            return False

        hold_time = (
            self.cfg.rise_hold_s
            if candidate_count > self.stable_count
            else self.cfg.fall_hold_s
        )
        return now - self.pending_since >= hold_time

    def _apply_count_debounce(
        self,
        candidate_count: int,
        now: float,
    ) -> int:
        if candidate_count == self.stable_count:
            self._reset_pending_count()
            return self.stable_count

        if candidate_count != self.pending_count:
            self._start_pending_count(candidate_count, now)
            return self.stable_count

        #cập nhật số người mới
        if self._candidate_is_ready(candidate_count, now):
            self.stable_count = candidate_count
            self._reset_pending_count()

        return self.stable_count

    def update(
        self,
        persons: Sequence[TrackedPerson],
        now: float,
        frame_shape: FrameShape,
    ) -> int:
        """Cập nhật estimator và trả về số người đã ổn định."""

        self._relink_new_ids(persons, now, frame_shape)

        for person in persons:
            self._update_single_track(person, now)

        self._remove_stale_tracks(now)
        candidate_count = self._count_active_confirmed_tracks(now)
        self.last_candidate_count = candidate_count
        return self._apply_count_debounce(candidate_count, now)

    def debug_text(self, now: float) -> str:
        del now
        confirmed = sum(
            1 for state in self.tracks.values() if state.confirmed
        )
        pending = "-" if self.pending_count is None else str(self.pending_count)
        return (
            f"candidate={self.last_candidate_count} "
            f"stable={self.stable_count} "
            f"confirmed_tracks={confirmed} "
            f"pending={pending}"
        )
