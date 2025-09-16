#!/usr/bin/env python3
"""
블랙박스 데이터 관리 모듈
API에서 블랙박스 데이터를 주기적으로 수신하고 오버레이 및 녹화 조건을 관리
"""

import threading
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Callable
from dataclasses import dataclass

try:
    from .api_client import BlackboxAPIClient, BlackboxData
    from .config import RTSPConfig
except ImportError:
    from api_client import BlackboxAPIClient, BlackboxData
    from config import RTSPConfig

logger = logging.getLogger(__name__)

@dataclass
class OverlayData:
    """오버레이용 데이터 클래스"""
    vessel_name: str
    latitude: float
    longitude: float
    timestamp: datetime
    
class BlackboxManager:
    """블랙박스 데이터 관리자"""
    
    def __init__(self, config: RTSPConfig):
        self.config = config
        self.api_client = BlackboxAPIClient(
            base_url=config.blackbox_api_url,
            timeout=config.api_timeout
        )
        
        # 상태 관리
        self.running = False
        self.thread = None
        self.lock = threading.Lock()
        
        # 데이터 상태
        self.latest_blackbox_data: Optional[BlackboxData] = None
        self.latest_overlay_data: Optional[OverlayData] = None
        self.is_recording_allowed = True  # 초기값: 녹화 허용
        
        # 콜백 함수들 (외부에서 등록)
        self.recording_state_callback: Optional[Callable[[bool], None]] = None
        
        logger.info(f"BlackboxManager 초기화 완료")
        logger.info(f"  API URL: {config.blackbox_api_url}")
        logger.info(f"  폴링 간격: {config.api_poll_interval}초")
        logger.info(f"  속도 임계값: {config.recording_speed_threshold} knots")
    
    def start(self):
        """블랙박스 데이터 모니터링 시작"""
        if self.running:
            logger.warning("BlackboxManager가 이미 실행 중입니다")
            return
        
        self.running = True
        self.thread = threading.Thread(target=self._monitoring_loop, daemon=True)
        self.thread.start()
        
        logger.info("블랙박스 데이터 모니터링 시작됨")
    
    def stop(self):
        """블랙박스 데이터 모니터링 중지"""
        if not self.running:
            return
        
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        
        logger.info("블랙박스 데이터 모니터링 중지됨")
    
    def _monitoring_loop(self):
        """모니터링 메인 루프"""
        logger.info("블랙박스 데이터 모니터링 루프 시작")
        
        consecutive_failures = 0
        max_consecutive_failures = 5
        
        while self.running:
            try:
                # 블랙박스 데이터 조회
                blackbox_data = self.api_client.get_latest_gps()
                
                if blackbox_data:
                    consecutive_failures = 0  # 성공 시 실패 카운트 리셋
                    
                    with self.lock:
                        self.latest_blackbox_data = blackbox_data
                        self._update_overlay_data(blackbox_data)
                        self._check_recording_condition(blackbox_data)
                    
                    # logger.debug(f"블랙박스 데이터 업데이트: "
                    #            f"speed={blackbox_data.speed}, "
                    #            f"vessel={blackbox_data.vessel_name}")
                else:
                    consecutive_failures += 1
                    logger.warning(f"블랙박스 데이터 수신 실패 ({consecutive_failures}/{max_consecutive_failures})")
                    
                    # 연속 실패가 임계값을 넘으면 기본값 사용
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error("블랙박스 API 연결 문제 감지, 기본값으로 전환")
                        with self.lock:
                            self._use_default_values()
                
            except Exception as e:
                logger.error(f"블랙박스 모니터링 중 오류: {e}")
                consecutive_failures += 1
            
            # 폴링 간격만큼 대기
            time.sleep(self.config.api_poll_interval)
        
        logger.info("블랙박스 데이터 모니터링 루프 종료")
    
    def _update_overlay_data(self, blackbox_data: BlackboxData):
        """오버레이 데이터 업데이트"""
        # null 값 처리: 기본값 사용
        vessel_name = blackbox_data.vessel_name or self.config.overlay_config.vessel_name
        latitude = blackbox_data.latitude or self.config.overlay_config.latitude
        longitude = blackbox_data.longitude or self.config.overlay_config.longitude
        
        # 시간 처리: 블랙박스 시간이 없으면 서버 시간 사용
        if blackbox_data.recorded_date:
            timestamp = blackbox_data.recorded_date
        else:
            timestamp = datetime.now(timezone.utc)
        
        self.latest_overlay_data = OverlayData(
            vessel_name=vessel_name,
            latitude=latitude,
            longitude=longitude,
            timestamp=timestamp
        )
        
        # logger.debug(f"오버레이 데이터 업데이트: {vessel_name} @ {latitude},{longitude}")
    
    def _check_recording_condition(self, blackbox_data: BlackboxData):
        """녹화 조건 확인"""
        speed = blackbox_data.speed
        net_opt = blackbox_data.net_opt
        
        if speed is None:
            # 속도 정보가 없으면 녹화 허용 (기본값)
            new_recording_state = True
            logger.debug("속도 정보 없음, 녹화 허용")
        else:
            # 속도 기준으로 녹화 조건 판단
            new_recording_state = (speed <= self.config.recording_speed_threshold) or (net_opt in [1, 2])
            # logger.debug(f"속도 {speed} knots, 임계값 {self.config.recording_speed_threshold}, "
            #             f"녹화 {'허용' if new_recording_state else '중단'}")
        
        # 녹화 상태가 변경된 경우 콜백 호출
        if new_recording_state != self.is_recording_allowed:
            self.is_recording_allowed = new_recording_state
            
            if self.recording_state_callback:
                try:
                    self.recording_state_callback(new_recording_state)
                except Exception as e:
                    logger.error(f"녹화 상태 콜백 실행 중 오류: {e}")
            
            logger.info(f"녹화 상태 변경: {'시작' if new_recording_state else '중지'} "
                       f"(속도: {speed} knots)")
    
    def _use_default_values(self):
        """API 연결 실패 시 기본값 사용"""
        self.latest_overlay_data = OverlayData(
            vessel_name=self.config.overlay_config.vessel_name,
            latitude=self.config.overlay_config.latitude,
            longitude=self.config.overlay_config.longitude,
            timestamp=datetime.now()
        )
        
        # API 연결 실패 시에는 녹화 허용 (안전한 기본값)
        if not self.is_recording_allowed:
            self.is_recording_allowed = True
            if self.recording_state_callback:
                try:
                    self.recording_state_callback(True)
                except Exception as e:
                    logger.error(f"녹화 상태 콜백 실행 중 오류: {e}")
        
        logger.info("기본값으로 오버레이 데이터 설정됨")
    
    def get_overlay_data(self) -> Optional[OverlayData]:
        """현재 오버레이 데이터 반환"""
        with self.lock:
            return self.latest_overlay_data
    
    def get_blackbox_data(self) -> Optional[BlackboxData]:
        """현재 블랙박스 데이터 반환"""
        with self.lock:
            return self.latest_blackbox_data
    
    def is_recording_enabled(self) -> bool:
        """현재 녹화 허용 상태 반환"""
        with self.lock:
            return self.is_recording_allowed
    
    def set_recording_state_callback(self, callback: Callable[[bool], None]):
        """녹화 상태 변경 콜백 설정"""
        self.recording_state_callback = callback
        logger.info("녹화 상태 변경 콜백 등록됨")
    
    def get_statistics(self) -> dict:
        """통계 정보 반환"""
        with self.lock:
            return {
                'running': self.running,
                'has_blackbox_data': self.latest_blackbox_data is not None,
                'has_overlay_data': self.latest_overlay_data is not None,
                'recording_allowed': self.is_recording_allowed,
                'api_url': self.config.blackbox_api_url,
                'poll_interval': self.config.api_poll_interval,
                'speed_threshold': self.config.recording_speed_threshold
            } 