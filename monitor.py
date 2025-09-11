"""
시스템 리소스 모니터링 모듈

시스템 리소스를 모니터링하고 향후 Redis 연동을 위한 데이터 구조화
- CPU, 메모리, GPU 사용률 모니터링
- 프로세스별 리소스 사용량 추적
- Redis 연동 인터페이스 준비 (TODO)
"""

import os
import time
import threading
import logging
import psutil
from collections import deque
from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime

try:
    import GPUtil
    GPU_AVAILABLE = True
except ImportError:
    GPU_AVAILABLE = False
    GPUtil = None

from .config import RTSPConfig

logger = logging.getLogger(__name__)

@dataclass
class SystemStats:
    """시스템 통계"""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    disk_usage_percent: float
    process_cpu_percent: float
    process_memory_mb: float
    cpu_temperature: Optional[float] = None
    gpu_info: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리로 변환 (Redis 전송용)"""
        data = {
            'timestamp': self.timestamp,
            'datetime': datetime.fromtimestamp(self.timestamp).isoformat(),
            'cpu_percent': self.cpu_percent,
            'memory_percent': self.memory_percent,
            'disk_usage_percent': self.disk_usage_percent,
            'process_cpu_percent': self.process_cpu_percent,
            'process_memory_mb': self.process_memory_mb
        }
        
        if self.cpu_temperature is not None:
            data['cpu_temperature'] = self.cpu_temperature
        
        if self.gpu_info:
            data['gpu_info'] = self.gpu_info
            
        return data

class SystemMonitor:
    """시스템 리소스 모니터링 (Redis 연동 준비)"""
    
    def __init__(self, config: RTSPConfig):
        self.config = config
        self.monitoring_thread = None
        self.running = False
        
        # 통계 히스토리 (최근 5분간)
        history_size = int(300 / config.monitoring_interval)  # 5분 / 간격
        self.stats_history = deque(maxlen=history_size)
        
        # 프로세스 정보
        self.process = psutil.Process()
        
        # GPU 정보 초기화
        self.gpu_available = GPU_AVAILABLE
        if self.gpu_available:
            try:
                self.gpus = GPUtil.getGPUs()
                if not self.gpus:
                    self.gpu_available = False
            except Exception as e:
                logger.warning(f"GPU 초기화 실패: {e}")
                self.gpu_available = False
        
        logger.info(f"SystemMonitor 초기화 완료 (GPU: {'사용 가능' if self.gpu_available else '사용 불가'})")
    
    def start_monitoring(self):
        """모니터링 시작"""
        if self.running:
            logger.warning("모니터링이 이미 실행 중입니다")
            return
        
        self.running = True
        self.monitoring_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitoring_thread.start()
        logger.info("시스템 모니터링 시작")
    
    def stop_monitoring(self):
        """모니터링 중지"""
        if not self.running:
            return
        
        self.running = False
        if self.monitoring_thread:
            self.monitoring_thread.join(timeout=2)
        logger.info("시스템 모니터링 중지")
    
    def _monitor_loop(self):
        """모니터링 메인 루프"""
        while self.running:
            try:
                stats = self._collect_stats()
                self.stats_history.append(stats)
                
                # TODO: Redis에 통계 전송
                # self._send_to_redis(stats)
                
                time.sleep(self.config.monitoring_interval)
                
            except Exception as e:
                logger.error(f"모니터링 루프 오류: {e}")
                time.sleep(self.config.monitoring_interval)
    
    def _collect_stats(self) -> SystemStats:
        """현재 시스템 상태 수집"""
        try:
            # 시스템 CPU 및 메모리
            cpu_percent = psutil.cpu_percent()
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')
            
            # 프로세스 리소스
            process_cpu = self.process.cpu_percent()
            process_memory = self.process.memory_info().rss / (1024 * 1024)  # MB
            
            # CPU 온도
            cpu_temp = self._get_cpu_temperature()
            
            # GPU 정보
            gpu_info = self._get_gpu_info()
            
            return SystemStats(
                timestamp=time.time(),
                cpu_percent=cpu_percent,
                memory_percent=memory.percent,
                disk_usage_percent=disk.percent,
                process_cpu_percent=process_cpu,
                process_memory_mb=process_memory,
                cpu_temperature=cpu_temp,
                gpu_info=gpu_info
            )
            
        except Exception as e:
            logger.error(f"시스템 통계 수집 오류: {e}")
            # 최소한의 정보라도 반환
            return SystemStats(
                timestamp=time.time(),
                cpu_percent=0,
                memory_percent=0,
                disk_usage_percent=0,
                process_cpu_percent=0,
                process_memory_mb=0
            )
    
    def _get_cpu_temperature(self) -> Optional[float]:
        """CPU 온도 가져오기"""
        try:
            temps = psutil.sensors_temperatures()
            if not temps:
                return None
            
            # 다양한 센서 이름 시도
            sensor_names = ['coretemp', 'k10temp', 'cpu_thermal', 'acpi']
            
            for sensor_name in sensor_names:
                if sensor_name in temps:
                    temp_list = temps[sensor_name]
                    if temp_list:
                        # 패키지 온도나 첫 번째 코어 온도 사용
                        for temp in temp_list:
                            if 'Package' in temp.label or 'Core 0' in temp.label:
                                return temp.current
                        # 패키지 온도가 없으면 첫 번째 온도 사용
                        return temp_list[0].current
            
            # 위의 센서들이 없으면 첫 번째 센서의 첫 번째 온도 사용
            for sensor_temps in temps.values():
                if sensor_temps:
                    return sensor_temps[0].current
            
            return None
            
        except Exception as e:
            logger.debug(f"CPU 온도 가져오기 실패: {e}")
            return None
    
    def _get_gpu_info(self) -> Optional[Dict[str, Any]]:
        """GPU 정보 가져오기"""
        if not self.gpu_available:
            return None
        
        try:
            gpus = GPUtil.getGPUs()
            if not gpus:
                return None
            
            gpu_data = {
                'timestamp': time.time(),
                'gpus': []
            }
            
            for i, gpu in enumerate(gpus):
                gpu_data['gpus'].append({
                    'id': i,
                    'name': gpu.name,
                    'load_percent': gpu.load * 100,  # 사용률 (%)
                    'memory_used_mb': gpu.memoryUsed,
                    'memory_total_mb': gpu.memoryTotal,
                    'memory_percent': (gpu.memoryUsed / gpu.memoryTotal) * 100 if gpu.memoryTotal > 0 else 0,
                    'temperature': gpu.temperature
                })
            
            return gpu_data
            
        except Exception as e:
            logger.warning(f"GPU 정보 가져오기 실패: {e}")
            return None
    
    def get_current_stats(self) -> Optional[SystemStats]:
        """현재 리소스 사용량 반환"""
        if not self.stats_history:
            return None
        return self.stats_history[-1]
    
    def get_history(self) -> list:
        """전체 히스토리 반환"""
        return list(self.stats_history)
    
    def get_summary_stats(self) -> Dict[str, Any]:
        """요약 통계 반환"""
        if not self.stats_history:
            return {}
        
        # CPU 통계
        cpu_values = [stat.cpu_percent for stat in self.stats_history]
        process_cpu_values = [stat.process_cpu_percent for stat in self.stats_history]
        
        # 메모리 통계
        memory_values = [stat.memory_percent for stat in self.stats_history]
        process_memory_values = [stat.process_memory_mb for stat in self.stats_history]
        
        # CPU 온도 통계
        cpu_temps = [stat.cpu_temperature for stat in self.stats_history if stat.cpu_temperature is not None]
        
        summary = {
            'monitoring_duration_minutes': len(self.stats_history) * self.config.monitoring_interval / 60,
            'cpu': {
                'system_avg': sum(cpu_values) / len(cpu_values),
                'system_max': max(cpu_values),
                'process_avg': sum(process_cpu_values) / len(process_cpu_values),
                'process_max': max(process_cpu_values)
            },
            'memory': {
                'system_avg_percent': sum(memory_values) / len(memory_values),
                'system_max_percent': max(memory_values),
                'process_avg_mb': sum(process_memory_values) / len(process_memory_values),
                'process_max_mb': max(process_memory_values)
            }
        }
        
        # CPU 온도 통계 추가
        if cpu_temps:
            summary['cpu']['temperature_avg'] = sum(cpu_temps) / len(cpu_temps)
            summary['cpu']['temperature_max'] = max(cpu_temps)
            summary['cpu']['temperature_min'] = min(cpu_temps)
        
        # GPU 통계
        if self.gpu_available:
            gpu_loads = []
            gpu_memory_percents = []
            gpu_temps = []
            
            for stat in self.stats_history:
                if stat.gpu_info and stat.gpu_info.get('gpus'):
                    for gpu in stat.gpu_info['gpus']:
                        gpu_loads.append(gpu['load_percent'])
                        gpu_memory_percents.append(gpu['memory_percent'])
                        if gpu.get('temperature') is not None:
                            gpu_temps.append(gpu['temperature'])
            
            if gpu_loads:
                summary['gpu'] = {
                    'load_avg_percent': sum(gpu_loads) / len(gpu_loads),
                    'load_max_percent': max(gpu_loads),
                    'memory_avg_percent': sum(gpu_memory_percents) / len(gpu_memory_percents),
                    'memory_max_percent': max(gpu_memory_percents)
                }
                
                if gpu_temps:
                    summary['gpu']['temperature_avg'] = sum(gpu_temps) / len(gpu_temps)
                    summary['gpu']['temperature_max'] = max(gpu_temps)
        
        return summary
    
    def _send_to_redis(self, stats: SystemStats):
        """Redis로 통계 전송 (향후 구현)"""
        # TODO: Redis 연동 구현
        # 
        # Redis 키 구조 예시:
        # - rtsp_monitor:{hostname}:current → 현재 상태
        # - rtsp_monitor:{hostname}:history:{timestamp} → 히스토리
        # - rtsp_monitor:{hostname}:summary → 요약 통계
        #
        # 구현 예시:
        # import redis
        # import socket
        # 
        # try:
        #     redis_client = redis.Redis(host='localhost', port=6379, db=0)
        #     hostname = socket.gethostname()
        #     
        #     # 현재 상태 저장
        #     redis_client.hset(
        #         f"rtsp_monitor:{hostname}:current",
        #         mapping=stats.to_dict()
        #     )
        #     
        #     # 히스토리 저장 (TTL 설정)
        #     redis_client.hset(
        #         f"rtsp_monitor:{hostname}:history:{int(stats.timestamp)}",
        #         mapping=stats.to_dict()
        #     )
        #     redis_client.expire(
        #         f"rtsp_monitor:{hostname}:history:{int(stats.timestamp)}",
        #         3600  # 1시간 후 만료
        #     )
        #     
        #     logger.debug(f"Redis에 통계 전송: {hostname}")
        #     
        # except Exception as e:
        #     logger.error(f"Redis 전송 실패: {e}")
        
        pass  # 현재는 구현하지 않음
    
    def save_stats_to_file(self, filepath: str):
        """통계를 파일로 저장"""
        try:
            import json
            
            data = {
                'collection_info': {
                    'start_time': self.stats_history[0].timestamp if self.stats_history else time.time(),
                    'end_time': self.stats_history[-1].timestamp if self.stats_history else time.time(),
                    'monitoring_interval': self.config.monitoring_interval,
                    'data_points': len(self.stats_history)
                },
                'summary': self.get_summary_stats(),
                'history': [stat.to_dict() for stat in self.stats_history]
            }
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            logger.debug(f"시스템 모니터링 통계 저장: {filepath}")
            
        except Exception as e:
            logger.error(f"통계 파일 저장 실패: {e}")
    
    def cleanup(self):
        """리소스 정리"""
        self.stop_monitoring()
        logger.info("시스템 모니터 정리 완료") 