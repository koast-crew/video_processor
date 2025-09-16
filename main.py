"""
메인 RTSP 처리 모듈

단일 RTSP 스트림을 2개 스레드로 처리하는 메인 클래스
- StreamReceiver: RTSP 스트림 수신
- FrameProcessor: YOLO 블러 처리 및 MP4 저장
- 통합 통계 수집 및 출력
- 종료 신호 처리
"""

import queue
import signal
import time
import logging
from typing import Dict, Any
import sys
import os

from .config import RTSPConfig
from .stream_receiver import StreamReceiver
from .frame_processor import FrameProcessor
from .monitor import SystemMonitor
from .blackbox_manager import BlackboxManager

# 로깅 설정
# run.py에서 통합 로깅을 초기화하므로 여기서는 중복 파일 핸들러를 추가하지 않습니다.
# 필요 시 환경변수 기반으로 레벨만 보정
log_level = os.getenv('LOG_LEVEL', 'DEBUG').upper()
logging.basicConfig(
    level=getattr(logging, log_level, logging.DEBUG),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class RTSPProcessor:
    """메인 RTSP 처리 클래스"""
    
    def __init__(self, config: RTSPConfig):
        self.config = config
        
        # 스레드 간 통신 큐
        self.frame_queue = queue.Queue(maxsize=config.frame_queue_size)
        
        # 컴포넌트 초기화
        self.stream_receiver = StreamReceiver(config, self.frame_queue)
        self.frame_processor = FrameProcessor(config, self.frame_queue)
        self.monitor = SystemMonitor(config) if config.enable_monitoring else None
        self.blackbox_manager = BlackboxManager(config) if config.blackbox_enabled else None
        
        # 상태 관리
        self.running = False
        self.start_time = None
        
        logger.info("RTSPProcessor 초기화 완료")
        logger.info(f"  RTSP URL: {config.rtsp_url}")
        logger.info(f"  임시 경로: {config.temp_output_path}")
        logger.info(f"  최종 경로: {config.final_output_path}")
        logger.info(f"  블러 모듈: {config.blur_module_path or '기본 블러'}")
        logger.info(f"  모니터링: {'활성화' if config.enable_monitoring else '비활성화'}")
        logger.info(f"  블랙박스 사용: {'활성화' if config.blackbox_enabled else '비활성화'}")
        if config.blackbox_enabled:
            logger.info(f"  블랙박스 API: {config.blackbox_api_url}")
        logger.info(f"  속도 임계값: {config.recording_speed_threshold} knots")
    
    def start(self):
        """처리 시작"""
        if self.running:
            logger.warning("이미 실행 중입니다")
            return
        
        logger.info("RTSP 처리 시작")
        self.running = True
        self.start_time = time.time()
        
        try:
            # 설정 검증
            if not self.config.validate():
                raise ValueError("설정 검증 실패")
            
            # 블랙박스 매니저 시작 및 연결 (활성화된 경우)
            if self.blackbox_manager:
                self.blackbox_manager.start()
                self.frame_processor.set_blackbox_manager(self.blackbox_manager)
                self.stream_receiver.set_blackbox_manager(self.blackbox_manager)
            
            # 모니터링 시작
            if self.monitor:
                self.monitor.start_monitoring()
            
            # 스레드 시작
            self.stream_receiver.start()
            self.frame_processor.start()
            
            logger.info("모든 스레드 시작 완료")
            logger.info(f"큐 크기: {self.config.frame_queue_size}")
            
        except Exception as e:
            logger.error(f"시작 중 오류: {e}")
            self.stop()
            raise
    
    def stop(self):
        """처리 중지"""
        if not self.running:
            return
        
        logger.info("RTSP 처리 중지 시작")
        self.running = False
        
        try:
            # 스레드 중지 신호
            if self.stream_receiver:
                self.stream_receiver.stop()
            if self.frame_processor:
                self.frame_processor.stop()
            
            # 스레드 종료 대기
            if self.stream_receiver.is_alive():
                self.stream_receiver.join(timeout=5)
                if self.stream_receiver.is_alive():
                    logger.warning("StreamReceiver 강제 종료")
            
            if self.frame_processor.is_alive():
                self.frame_processor.join(timeout=10)  # 영상 저장 완료 대기
                if self.frame_processor.is_alive():
                    logger.warning("FrameProcessor 강제 종료")
            
            # 블랙박스 매니저 중지
            if self.blackbox_manager:
                self.blackbox_manager.stop()
            
            # 모니터링 중지
            if self.monitor:
                self.monitor.stop_monitoring()
            
            # 최종 통계 출력
            self._print_final_statistics()
            
        except Exception as e:
            logger.error(f"종료 중 오류: {e}")
        
        logger.info("RTSP 처리 중지 완료")
    
    def get_statistics(self) -> Dict[str, Any]:
        """통합 통계 정보"""
        runtime = time.time() - self.start_time if self.start_time else 0
        
        stats = {
            'runtime_seconds': runtime,
            'status': 'running' if self.running else 'stopped',
            'config': {
                'rtsp_url': self.config.rtsp_url,
                'blur_enabled': self.config.blur_enabled,
                'monitoring_enabled': self.config.enable_monitoring,
                'frame_queue_size': self.config.frame_queue_size
            }
        }
        
        # 스트림 수신 통계
        if self.stream_receiver:
            stats['stream_receiver'] = self.stream_receiver.get_stats()
        
        # 프레임 처리 통계
        if self.frame_processor:
            stats['frame_processor'] = self.frame_processor.get_stats()
            stats['queue_status'] = self.frame_processor.get_queue_status()
        
        # 시스템 모니터링 통계
        if self.monitor:
            current_stats = self.monitor.get_current_stats()
            if current_stats:
                stats['system_stats'] = current_stats.to_dict()
            stats['system_summary'] = self.monitor.get_summary_stats()
        
        # 블랙박스 통계
        if self.blackbox_manager:
            stats['blackbox'] = self.blackbox_manager.get_statistics()
        
        return stats
    
    def _print_final_statistics(self):
        """최종 통계 출력"""
        try:
            stats = self.get_statistics()
            runtime = stats['runtime_seconds']
            
            logger.info("=" * 60)
            logger.info("최종 처리 통계")
            logger.info("=" * 60)
            logger.info(f"총 실행 시간: {runtime:.1f}초 ({runtime/60:.1f}분)")
            
            # 스트림 수신 통계
            if 'stream_receiver' in stats:
                recv_stats = stats['stream_receiver']
                logger.info(f"수신된 프레임: {recv_stats.get('received_frames', 0)}")
                logger.info(f"손실된 프레임: {recv_stats.get('lost_frames', 0)}")
                logger.info(f"수신 성공률: {100 - recv_stats.get('loss_rate', 0):.1f}%")
                logger.info(f"연결 시도 횟수: {recv_stats.get('connection_attempts', 0)}")
            
            # 프레임 처리 통계
            if 'frame_processor' in stats:
                proc_stats = stats['frame_processor']
                logger.info(f"처리된 프레임: {proc_stats.get('processed_frames', 0)}")
                logger.info(f"저장된 프레임: {proc_stats.get('saved_frames', 0)}")
                logger.info(f"블러 적용 프레임: {proc_stats.get('blur_applied_frames', 0)}")
                logger.info(f"평균 처리 시간: {proc_stats.get('avg_processing_time_ms', 0):.1f}ms")
                logger.info(f"저장 성공률: {proc_stats.get('save_rate', 0):.1f}%")
            
            # 시스템 리소스 요약
            if 'system_summary' in stats and stats['system_summary']:
                sys_stats = stats['system_summary']
                if 'cpu' in sys_stats:
                    logger.info(f"평균 CPU 사용률: {sys_stats['cpu'].get('system_avg', 0):.1f}%")
                    logger.info(f"프로세스 CPU 사용률: {sys_stats['cpu'].get('process_avg', 0):.1f}%")
                if 'memory' in sys_stats:
                    logger.info(f"평균 메모리 사용률: {sys_stats['memory'].get('system_avg_percent', 0):.1f}%")
                    logger.info(f"프로세스 메모리: {sys_stats['memory'].get('process_avg_mb', 0):.1f}MB")
            
            logger.info("=" * 60)
            
        except Exception as e:
            logger.error(f"최종 통계 출력 오류: {e}")
    
    def is_running(self) -> bool:
        """실행 상태 확인"""
        return self.running
    
    def wait_for_completion(self):
        """처리 완료 대기 (최대 시간 설정 시)"""
        if not self.config.max_duration_seconds:
            return
        
        remaining = self.config.max_duration_seconds
        logger.info(f"최대 {remaining}초 동안 처리 예정")
        
        while self.running and remaining > 0:
            time.sleep(min(5, remaining))  # 5초마다 체크
            remaining = self.config.max_duration_seconds - (time.time() - self.start_time)
            
            if remaining <= 0:
                logger.info("최대 처리 시간 도달, 자동 종료")
                self.stop()
                break

def create_signal_handler(processor: RTSPProcessor):
    """시그널 핸들러 생성"""
    def signal_handler(signum, frame):
        signal_name = signal.Signals(signum).name
        logger.info(f"{signal_name} 신호 수신, 정상 종료 시작")
        processor.stop()
        sys.exit(0)
    
    return signal_handler

def main():
    """메인 함수"""
    try:
        # 환경변수에서 설정 로드
        rtsp_url = os.getenv('RTSP_URL')
        if not rtsp_url:
            logger.error("RTSP_URL 환경변수가 설정되지 않았습니다")
            logger.info("사용법: RTSP_URL=rtsp://example.com/stream python -m video_processor.main")
            sys.exit(1)
        
        config = RTSPConfig.from_env(rtsp_url)
        
        # 프로세서 생성
        processor = RTSPProcessor(config)
        
        # 시그널 핸들러 등록
        signal_handler = create_signal_handler(processor)
        signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
        signal.signal(signal.SIGTERM, signal_handler)  # terminate
        
        # 처리 시작
        processor.start()
        
        # 메인 루프 (통계 출력)
        last_stats_time = 0
        stats_interval = 10  # 10초마다 통계 출력
        
        while processor.is_running():
            try:
                current_time = time.time()
                
                # 주기적 통계 출력
                if current_time - last_stats_time >= stats_interval:
                    stats = processor.get_statistics()
                    
                    # 간단한 현재 상태 + 최근 구간 FPS/드롭 출력
                    recv = stats.get('stream_receiver', {})
                    proc = stats.get('frame_processor', {})
                    queue_size = stats.get('queue_status', {}).get('queue_size', 0)
                    logger.info(
                        f"상태 - 수신 누적:{recv.get('received_frames',0)} 손실누적:{recv.get('lost_frames',0)} "
                        f"최근수신FPS:{recv.get('recent_received_fps',0):.2f} "
                        f"최근큐드롭:{recv.get('recent_queue_full_drops',0)} | "
                        f"처리누적:{proc.get('processed_frames',0)} 저장누적:{proc.get('saved_frames',0)} "
                        f"최근처리FPS:{proc.get('recent_processed_fps',0):.2f} 최근저장FPS:{proc.get('recent_saved_fps',0):.2f} | "
                        f"큐:{queue_size}"
                    )
                    
                    last_stats_time = current_time
                
                # 최대 시간 체크
                if config.max_duration_seconds:
                    elapsed = time.time() - processor.start_time
                    if elapsed >= config.max_duration_seconds:
                        logger.info("최대 처리 시간 도달")
                        break
                
                time.sleep(1)
                
            except KeyboardInterrupt:
                logger.info("키보드 인터럽트")
                break
        
        # 정상 종료
        processor.stop()
        
    except Exception as e:
        logger.error(f"메인 함수 오류: {e}")
        import traceback
        logger.error(f"상세 오류: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    main() 